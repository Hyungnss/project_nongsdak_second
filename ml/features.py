"""base 모델(LightGBM) 특성 — 가격만 쓴다. 기온 · 물가는 ③-1 에서 이 위에 더한다.

모든 특성은 기준일 위치 i 이하의 값으로만 만든다 (tests/test_ml.py 가 미래 값을 바꿔 확인한다).
품목마다 가격 크기가 달라서(쌀 5만 원 · 깻잎 2천 원) 전부 비율(로그)로 만든다.
목표도 log(미래 가격 / 기준일 가격) 이다.
"""

import numpy as np
import pandas as pd

from ml.baselines import YEAR, _doy
from ml.dataset import TOLERANCE, value_near

CATEGORICAL = ["category_code", "item_code"]


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


def build(series, samples):
    """표본마다 특성 행을 만든다. samples 와 같은 순서의 DataFrame.

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
    return feats


def target(samples):
    return np.log(samples.y.to_numpy(dtype=float) / samples.p0.to_numpy(dtype=float))
