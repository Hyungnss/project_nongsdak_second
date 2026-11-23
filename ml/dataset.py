"""DB → 품종별 일별 가격 시계열 → 예측 표본 (기준일 · 예측 기간 · 목표일 · 정답).

시계열 하나 = (시장, 품목, 품종, 대표 등급). 대표 등급은 화면과 같은 규칙(db.list_products)으로 고른다.
가격이 있는 조사일만 담는다 (주말 · 공휴일 · 철 지난 날은 없다).

예측 표본 규칙 (일별 · 2026-11-19 결정)
  · 기준일 t 는 그 품종의 조사일이다. t 의 가격까지 알고 있다고 본다 (17:30 수집 뒤 예측).
  · 예측 기간 h 일 뒤의 목표일은 't + h 이후 첫 조사일' 이다. 단 t + h 에서 tol(기본 3)일 안이어야 한다.
    주말이면 월요일로 넘어가고, 긴 연휴나 품종 철이 끝나 3일 안에 조사가 없으면 표본에서 뺀다.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HORIZONS = (7, 14, 28)
TOLERANCE = 3


@dataclass
class Series:
    """한 품종의 조사일 · 가격 · 평년가. dates 는 오름차순 datetime64[D]."""
    sid: str
    item_code: str
    kind_code: str
    rank_name: str
    category_code: str
    name: str
    dates: np.ndarray
    prices: np.ndarray
    normals: np.ndarray


def load_series(market="소매", min_obs=60):
    """DB 에서 대표 등급 시계열을 읽는다. 관측이 min_obs 보다 적은 품종은 뺀다."""
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "backend"))
    import db  # noqa: PLC0415  (backend/db.py — 화면과 같은 대표 등급 규칙)

    reps = {(it["item_code"], k["kind_code"]): k["rank_name"]
            for it in db.list_products(market) for k in it["kinds"]}
    rows = db._query("""
        SELECT ITEM_CODE, KIND_CODE, RANK_NAME, CATEGORY_CODE, ITEM_NAME, KIND_NAME,
               SURVEY_DATE, PRICE_TODAY::float8 AS price, PRICE_NORMAL::float8 AS normal
        FROM   TBL_DAILY_PRICE
        WHERE  MARKET_TYPE = %(m)s AND PRICE_TODAY > 0
        ORDER  BY ITEM_CODE, KIND_CODE, RANK_NAME, SURVEY_DATE
    """, {"m": market})
    if not rows:
        return []                      # 그 시장 자료가 없다 (예: 도매를 아직 안 받은 DB)
    df = pd.DataFrame(rows)
    df = df[[reps.get((i, k)) == r for i, k, r in zip(df.item_code, df.kind_code, df.rank_name)]]
    return frame_to_series(df, min_obs)


def frame_to_series(df, min_obs=60):
    out = []
    for (item, kind, rank), g in df.groupby(["item_code", "kind_code", "rank_name"], sort=True):
        if len(g) < min_obs:
            continue
        last = g.iloc[-1]
        out.append(Series(
            sid=f"{item}/{kind}/{rank}", item_code=item, kind_code=kind, rank_name=rank,
            category_code=str(last.category_code), name=f"{last.item_name} {last.kind_name} {rank}",
            dates=g.survey_date.to_numpy(dtype="datetime64[D]"),
            prices=g.price.to_numpy(dtype=float),
            normals=g.normal.to_numpy(dtype=float),
        ))
    return out


def make_samples(series, horizons=HORIZONS, tol=TOLERANCE, start=None, end=None):
    """예측 표본 표. 열: sid · i(기준일 위치) · origin · h · j(목표일 위치) · target_date · p0 · y.

    start · end 는 기준일 범위 (포함). 목표일이 없는 표본은 만들지 않는다.
    """
    start = np.datetime64(start, "D") if start is not None else None
    end = np.datetime64(end, "D") if end is not None else None
    parts = []
    for s in series:
        d, p = s.dates, s.prices
        keep = np.ones(len(d), bool)
        if start is not None:
            keep &= d >= start
        if end is not None:
            keep &= d <= end
        i = np.flatnonzero(keep)
        if not len(i):
            continue
        for h in horizons:
            want = d[i] + np.timedelta64(h, "D")
            j = np.searchsorted(d, want, side="left")
            ok = j < len(d)
            ok[ok] &= (d[j[ok]] - want[ok]) <= np.timedelta64(tol, "D")
            if not ok.any():
                continue
            ii, jj = i[ok], j[ok]
            parts.append(pd.DataFrame({
                "sid": s.sid, "category_code": s.category_code, "i": ii, "origin": d[ii], "h": h,
                "j": jj, "target_date": d[jj], "p0": p[ii], "y": p[jj],
            }))
    if not parts:
        return pd.DataFrame(columns=["sid", "category_code", "i", "origin", "h", "j", "target_date", "p0", "y"])
    return pd.concat(parts, ignore_index=True)


def value_near(s, when, tol=TOLERANCE, upto=None):
    """when 에 가장 가까운 조사일(±tol 일)의 가격. upto 위치보다 뒤의 값은 쓰지 않는다 (누수 방지).

    when · upto 는 배열이다 (표본마다 하나씩). 없으면 NaN.
    """
    d, p = s.dates, s.prices
    when = np.asarray(when, dtype="datetime64[D]")
    k = np.searchsorted(d, when, side="left")
    best = np.full(len(when), np.nan)
    gap = np.full(len(when), np.inf)
    for cand in (k - 1, k):
        okc = (cand >= 0) & (cand < len(d))
        if upto is not None:
            okc &= cand <= np.asarray(upto)
        c = np.where(okc, cand, 0)
        g = np.abs((d[c] - when).astype("int64")).astype(float)
        g[~okc] = np.inf
        better = g < gap
        best[better] = p[c][better]
        gap[better] = g[better]
    best[gap > tol] = np.nan
    return best
