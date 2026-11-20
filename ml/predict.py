"""서빙용 예측 — 품종 · 등급마다 '마지막 조사일' 을 기준으로 1 · 2 · 4주 뒤 가격을 낸다.

백테스트(ml/backtest.py)와 같은 규칙을 쓴다. 다른 점은 기준일이 과거의 여러 날이 아니라 '지금' 하나라는 것.

모델 (2026-11-21~)
  lgbm  — LightGBM A (가격만). 서버가 매주 학습하고 게이트를 넘은 모델 (ml/model.py · current.json).
          시장마다 모델 하나, 화면의 모든 등급을 같은 모델로 예측한다.
  blend — 기준선. naive(기준일 가격)와 계절 프로파일의 평균 = '예년 계절 변화의 절반만큼 바뀐다'.
          배포된 LightGBM 이 없거나 불러오다 실패하면 이걸로 예측한다 (서비스가 비지 않게).
          계절 프로파일을 못 만드는 품종(과거 자료 2년 미만)은 naive 로 메우고 FALLBACK 으로 표시한다.
예측마다 MODEL · MODEL_VERSION 이 남아 어떤 모델이 낸 숫자인지 추적된다 (docs/ML_서빙.md).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml import baselines
from ml.dataset import HORIZONS, frame_to_series

MODEL = "blend"                    # 기준선 (LightGBM 이 없을 때)
MODEL_VERSION = "blend-1"          # 규칙이 바뀌면 올린다
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
    model: str = MODEL
    model_version: str = MODEL_VERSION


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
    """blend — 시계열 하나의 마지막 조사일 기준 예측. 쓰는 값은 전부 그날까지의 가격이다."""
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


def serving_samples(series, horizons=HORIZONS):
    """시계열마다 '마지막 조사일 → h 일 뒤' 표본 (LightGBM 특성을 만들 모양). 목표일은 기준일 + h."""
    rows = []
    for s in series:
        i = len(s.dates) - 1
        for h in horizons:
            rows.append({"sid": s.sid, "category_code": s.category_code, "i": i, "origin": s.dates[i], "h": h,
                         "target_date": s.dates[i] + np.timedelta64(h, "D"), "p0": float(s.prices[i])})
    return pd.DataFrame(rows)


def forecast_lgbm(series, market, booster, version, horizons=HORIZONS):
    """LightGBM — 학습과 같은 특성(features.build)으로 마지막 조사일의 1 · 2 · 4주 뒤."""
    from ml import model  # noqa: PLC0415

    smp = serving_samples(series, horizons)
    price = model.predict_prices(booster, {s.sid: s for s in series}, smp)
    if not np.isfinite(price).all():
        raise ValueError(f"LightGBM 예측에 NaN · 무한대 {int((~np.isfinite(price)).sum())}개")
    by = {s.sid: s for s in series}
    day = lambda v: np.datetime64(v, "D")          # noqa: E731 — DataFrame 을 거치며 Timestamp 가 된 날짜를 blend 와 같은 모양으로
    return [Forecast(market, by[r.sid].item_code, by[r.sid].kind_code, by[r.sid].rank_name, day(r.origin), r.p0,
                     int(r.h), day(r.target_date), round(float(p), 2), False, model.MODEL_NAME, version)
            for r, p in zip(smp.itertuples(), price)]


def forecast_market(query, market, horizons=HORIZONS, log=print):
    """시장 하나의 예측 전부. 시장 최신 조사일에서 STALE_DAYS 넘게 끊긴 품종은 뺀다.

    배포된 LightGBM 이 있으면 그것으로, 없거나 실패하면 blend 로.
    """
    series = load_all_series(query, market)
    if not series:
        return []
    latest = max(s.dates[-1] for s in series)
    keep = [s for s in series if (latest - s.dates[-1]).astype(int) <= STALE_DAYS]
    try:
        from ml import model  # noqa: PLC0415

        current = model.load_current(market)
        if current is not None:
            booster, meta = current
            return forecast_lgbm(keep, market, booster, meta["version"], horizons)
    except Exception as ex:      # 모델 파일 · lightgbm 문제로 예측이 비지 않게 — blend 로 대신한다
        log(f"  {market}: LightGBM 예측 실패 → blend 로 대신 — {type(ex).__name__}: {ex}")
    return [f for s in keep for f in forecast_series(s, market, horizons)]
