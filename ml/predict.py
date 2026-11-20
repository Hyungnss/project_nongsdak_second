"""서빙용 예측 — 품종 · 등급마다 '마지막 조사일' 을 기준으로 1 · 2 · 4주 뒤 가격을 낸다.

백테스트(ml/backtest.py)와 같은 규칙을 쓴다. 다른 점은 기준일이 과거의 여러 날이 아니라 '지금' 하나라는 것.

모델 (2026-11-20)
  blend — naive(기준일 가격)와 계절 프로파일의 평균. '예년 계절 변화의 절반만큼 바뀐다'.
          학습이 필요 없어 서버에서 바로 돈다. LightGBM 이 더 낫다고 판단되면 MODEL 을 바꾼다
          (표 · API · 화면은 그대로 — docs/ML.md).
  계절 프로파일을 못 만드는 품종(과거 자료 2년 미만)은 naive 로 메우고 FALLBACK 으로 표시한다.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml import baselines
from ml.dataset import HORIZONS, frame_to_series

MODEL = "blend"
MODEL_VERSION = "blend-1"          # 규칙이 바뀌면 올린다 (예측마다 남아 추적된다)
STALE_DAYS = 7                     # 시장 최신 조사일보다 이만큼 오래된 품종은 예측하지 않는다 (철 지난 품종)


@dataclass
class Forecast:
    market: str
    item_code: str
    kind_code: str
    rank_name: str
    base_date: np.datetime64
    base_price: float
    h: int
    target_date: np.datetime64
    price: float
    fallback: bool


def load_all_series(query, market, min_obs=60):
    """그 시장의 모든 (품목, 품종, 등급) 시계열. 화면에서 어떤 등급을 골라도 예측이 있게."""
    rows = query("""
        SELECT ITEM_CODE, KIND_CODE, RANK_NAME, CATEGORY_CODE, ITEM_NAME, KIND_NAME,
               SURVEY_DATE, PRICE_TODAY::float8 AS price, PRICE_NORMAL::float8 AS normal
        FROM   TBL_DAILY_PRICE
        WHERE  MARKET_TYPE = %(m)s AND PRICE_TODAY > 0
        ORDER  BY ITEM_CODE, KIND_CODE, RANK_NAME, SURVEY_DATE
    """, {"m": market})
    if not rows:
        return []
    return frame_to_series(pd.DataFrame(rows), min_obs)


def forecast_series(s, market, horizons=HORIZONS):
    """시계열 하나의 마지막 조사일 기준 예측. 쓰는 값은 전부 그날까지의 가격이다."""
    base = s.dates[-1]
    p0 = float(s.prices[-1])
    prof = baselines.season_profile(s, base + np.timedelta64(1, "D"))    # 기준일까지의 자료만
    out = []
    for h in horizons:
        target = base + np.timedelta64(h, "D")
        ratio = np.nan
        if prof is not None:
            ratio = prof[baselines._doy([target])[0]] / prof[baselines._doy([base])[0]]
        fb = not np.isfinite(ratio)
        price = p0 if fb else p0 * (1 + ratio) / 2
        out.append(Forecast(market, s.item_code, s.kind_code, s.rank_name, base, p0, h, target,
                            round(float(price), 2), fb))
    return out


def forecast_market(query, market, horizons=HORIZONS):
    """시장 하나의 예측 전부. 시장 최신 조사일에서 STALE_DAYS 넘게 끊긴 품종은 뺀다."""
    series = load_all_series(query, market)
    if not series:
        return []
    latest = max(s.dates[-1] for s in series)
    keep = [s for s in series if (latest - s.dates[-1]).astype(int) <= STALE_DAYS]
    return [f for s in keep for f in forecast_series(s, market, horizons)]
