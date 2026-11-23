"""LightGBM 특성 — 그 품종의 가격 16개 + (소매만) 같은 품종의 도매 가격 3개.

모든 특성은 기준일 위치 i 이하의 값으로만 만든다 (tests/test_ml.py 가 미래 값을 바꿔 확인한다).
품목마다 가격 크기가 달라서(쌀 5만 원 · 깻잎 2천 원) 전부 비율(로그)로 만든다.
목표도 log(미래 가격 / 기준일 가격) 이다.

도매 특성 (2026-11-23 채택 — 소매는 도매를 늦게 따라간다. 소매 시험 기간 1.092 → 1.059, docs/ML_도매특성.md)
  wh_ret5 · wh_ret20  같은 (품목, 품종) 도매의 최근 5 · 20 조사일 로그 수익률
  wh_gap20            log(소매 기준일 가격 / 도매 최근 20 조사일 평균)
  도매 값은 **기준일 당일까지**(± TOLERANCE 일 안의 마지막 도매 조사일)만 쓴다 — 도매 · 소매 모두 17:30 에 같이 수집된다.
  도매가 없는 품종 · 그날 근처에 도매 조사가 없는 표본은 NaN (LightGBM 이 다룬다).
"""

import numpy as np
import pandas as pd

from ml.baselines import YEAR, _doy
from ml.dataset import TOLERANCE, value_near

CATEGORICAL = ["category_code", "item_code"]
WHOLESALE = ["wh_ret5", "wh_ret20", "wh_gap20"]


def _window_mean(p, i, w):
    c = np.concatenate([[0.0], np.cumsum(p)])
    lo = np.maximum(i + 1 - w, 0)
    return (c[i + 1] - c[lo]) / (i + 1 - lo)


def _lag(p, i, k):
    out = np.full(len(i), np.nan)
    ok = i - k >= 0
    out[ok] = p[i[ok] - k]
    return out


def _vol(logp, i, w):
    """최근 w 개 로그 수익률의 표준편차 (위치 i 까지). 자리가 모자라면 NaN."""
    r = pd.Series(np.concatenate([[np.nan], np.diff(logp)]))
    roll = r.rolling(w, min_periods=w).std(ddof=0).to_numpy()
    return roll[i]


def build(series, samples, wholesale=None):
    """표본마다 특성 행을 만든다. samples 와 같은 순서의 DataFrame.

    wholesale: 도매 시계열 목록 (소매 모델만) — 주면 맨 뒤에 WHOLESALE 3열을 더한다.

    메모리를 아낀다 (서버 2GB 에서 매주 학습하려고 — 표본 73만 행 기준 최대 944MB → 측정값은 docs/ML_서빙.md):
    전체 표를 여러 번 복사하지 않고(무한대 → NaN 은 열마다 제자리에서), 품목코드는 품종 수(약 300)만큼만 쪼갠다.
    """
    n = len(samples)
    cols = {}
    pos_of = pd.Series(np.arange(n), index=samples.index)
    for sid, g in samples.groupby("sid", sort=False):
        s = series[sid]
        p, logp = s.prices, np.log(s.prices)
        i = g.i.to_numpy()
        p0 = p[i]
        f = {
            "ma5": np.log(p0 / _window_mean(p, i, 5)),
            "ma20": np.log(p0 / _window_mean(p, i, 20)),
            "ma60": np.log(p0 / _window_mean(p, i, 60)),
            "ret5": np.log(p0 / _lag(p, i, 5)),
            "ret20": np.log(p0 / _lag(p, i, 20)),
            "ret60": np.log(p0 / _lag(p, i, 60)),
            "vol20": _vol(logp, i, 20),
            "gap": (s.dates[i] - s.dates[np.maximum(i - 1, 0)]).astype(int).astype(float),
            "lvl_1y": np.log(p0 / value_near(s, g.origin.to_numpy() - YEAR, TOLERANCE, upto=i)),
            "ly_change": np.log(value_near(s, g.target_date.to_numpy() - YEAR, TOLERANCE, upto=i)
                                / value_near(s, g.origin.to_numpy() - YEAR, TOLERANCE, upto=i)),
            "ly2_change": np.log(value_near(s, g.target_date.to_numpy() - 2 * YEAR, TOLERANCE, upto=i)
                                 / value_near(s, g.origin.to_numpy() - 2 * YEAR, TOLERANCE, upto=i)),
            "vs_normal": np.log(p0 / s.normals[i]),
        }
        doy = _doy(g.target_date.to_numpy())
        f["doy_sin"], f["doy_cos"] = np.sin(2 * np.pi * doy / 365), np.cos(2 * np.pi * doy / 365)
        f["dow"] = ((g.target_date.to_numpy().astype("datetime64[D]").astype(int) + 3) % 7).astype(float)
        pos = pos_of[g.index].to_numpy()
        for k, v in f.items():
            cols.setdefault(k, np.full(n, np.nan))[pos] = v
    for v in cols.values():
        v[np.isinf(v)] = np.nan
    cols["h"] = samples.h.to_numpy(dtype=float)
    feats = pd.DataFrame(cols, index=samples.index, copy=False)
    del cols
    item_of = {sid: sid.split("/")[0] for sid in samples["sid"].unique()}
    for c in CATEGORICAL:
        src = samples["sid"].map(item_of) if c == "item_code" else samples[c]
        feats[c] = src.astype("category")
    if wholesale is not None:
        for k, v in wholesale_columns(series, samples, wholesale).items():
            feats[k] = v
    return feats


def asof_position(s, days, tol=TOLERANCE):
    """days(기준일들) 마다 s 의 '그날 당일까지의 마지막 조사일' 위치. tol 일보다 오래됐으면 -1. 뒤의 값은 고르지 않는다."""
    days = np.asarray(days, dtype="datetime64[D]")
    pos = np.searchsorted(s.dates, days, side="right") - 1
    ok = pos >= 0
    ok[ok] &= (days[ok] - s.dates[pos[ok]]).astype(int) <= tol
    return np.where(ok, pos, -1)


def wholesale_columns(series, samples, wholesale):
    """소매 표본마다 같은 (품목, 품종) 도매의 기준일 당일까지 값으로 WHOLESALE 3열 (numpy 배열 dict)."""
    pair = {(w.item_code, w.kind_code): w for w in wholesale}
    n = len(samples)
    out = {c: np.full(n, np.nan) for c in WHOLESALE}
    pos_of = pd.Series(np.arange(n), index=samples.index)
    for sid, g in samples.groupby("sid", sort=False):
        s = series[sid]
        w = pair.get((s.item_code, s.kind_code))
        if w is None:
            continue
        rows = pos_of[g.index].to_numpy()
        pos = asof_position(w, g.origin.to_numpy())
        lp = np.log(w.prices)
        ok = pos >= 5
        out["wh_ret5"][rows[ok]] = lp[pos[ok]] - lp[pos[ok] - 5]
        ok = pos >= 20
        out["wh_ret20"][rows[ok]] = lp[pos[ok]] - lp[pos[ok] - 20]
        ok = pos >= 19
        c = np.concatenate([[0.0], np.cumsum(w.prices)])
        ma = (c[pos[ok] + 1] - c[pos[ok] - 19]) / 20
        out["wh_gap20"][rows[ok]] = np.log(s.prices[g.i.to_numpy()[ok]] / ma)
    return out


def target(samples):
    return np.log(samples.y.to_numpy(dtype=float) / samples.p0.to_numpy(dtype=float))
