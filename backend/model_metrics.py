"""예측 모델 지표 — /metrics 에 모델 상태를 같이 내보낸다 (Prometheus 가 긁고 Grafana 가 그린다).

Grafana 에 DB 접속을 주지 않으려고, 웹이 DB 를 읽어 지표로 바꿔 준다 (모니터링 쪽 권한이 늘지 않는다).
Prometheus 가 30초마다 긁지만 DB 는 CACHE_SECONDS 에 한 번만 읽는다. DB 를 못 읽으면 이 지표만 빠지고
/metrics 자체는 그대로 나온다 (요청 지표까지 끊기지 않게).

지표 (market = 소매 · 도매)
  nongsdak_model_info{market,model,version,name}         1 — 지금 서비스 예측을 낸 모델 (가장 최근 예측의 모델)
                                                          name = 사람이 읽는 이름 (예: LightGBM · 11월 23일 학습)
  nongsdak_model_gate_score{market,model}                 마지막 학습의 게이트 점수 (model=lgbm) · 같은 기간 blend (model=blend)
                                                          · 같은 기간 챔피언 (model=champion — 비교했을 때만)
  nongsdak_model_gate_passed{market}                      마지막 학습이 게이트를 넘었나 (1/0)
  nongsdak_model_trained_timestamp_seconds{market}        마지막 학습 시각 (unix) — Grafana 에서 '몇 시간 전'
  nongsdak_model_runs{market,result}                      학습 횟수 (passed · failed)
  nongsdak_forecast_rows{market,model}                    가장 최근 기준일의 예측 행 수
  nongsdak_forecast_base_date_timestamp_seconds{market}   가장 최근 예측의 기준일 — 예측이 멈췄는지
  nongsdak_price_latest_timestamp_seconds{market}         가장 최근 가격 조사일 — 수집이 멈췄는지
  nongsdak_forecast_eval_ape{market,h}                    최근 28일(목표일 기준) 예측 vs 실제 평균 % 오차 (0.05 = 5%)
  nongsdak_forecast_eval_direction{market,h}              같은 기간 오를지 내릴지 맞힌 비율
  nongsdak_forecast_eval_count{market,h}                  채점된 예측 수 (첫 1주 정답이 나오기 전엔 0)
"""

import time
from datetime import datetime, time as dtime

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import REGISTRY

import config
import db
import model_names

CACHE_SECONDS = 60
EVAL_DAYS = 28

_cache = {"at": 0.0, "families": []}


def _ts(d):
    """DATE → unix 초 (한국 시각 자정)."""
    return datetime.combine(d, dtime(0)).replace(tzinfo=config.KST).timestamp()


def _families():
    q = db._query
    info = GaugeMetricFamily("nongsdak_model_info", "지금 서비스 예측을 낸 모델", labels=["market", "model", "version", "name"])
    rows = GaugeMetricFamily("nongsdak_forecast_rows", "가장 최근 기준일의 예측 행 수", labels=["market", "model"])
    base = GaugeMetricFamily("nongsdak_forecast_base_date_timestamp_seconds", "가장 최근 예측의 기준일", labels=["market"])
    for r in q("""
        SELECT f.MARKET_TYPE AS market, f.MODEL AS model, f.MODEL_VERSION AS version, f.BASE_DATE AS base_date,
               COUNT(*) AS n
        FROM   TBL_PRICE_FORECAST f
        JOIN  (SELECT MARKET_TYPE, MAX(BASE_DATE) AS d FROM TBL_PRICE_FORECAST GROUP BY 1) m
               ON m.MARKET_TYPE = f.MARKET_TYPE AND m.d = f.BASE_DATE
        GROUP  BY 1, 2, 3, 4
    """):
        info.add_metric([r["market"], r["model"], r["version"], model_names.describe(r["model"], r["version"])["label"]], 1)
        rows.add_metric([r["market"], r["model"]], r["n"])
        base.add_metric([r["market"]], _ts(r["base_date"]))

    score = GaugeMetricFamily("nongsdak_model_gate_score", "마지막 학습의 게이트 점수 (낮을수록 좋음)", labels=["market", "model"])
    passed = GaugeMetricFamily("nongsdak_model_gate_passed", "마지막 학습이 게이트를 넘었나", labels=["market"])
    trained = GaugeMetricFamily("nongsdak_model_trained_timestamp_seconds", "마지막 학습 시각", labels=["market"])
    for r in q("""
        SELECT DISTINCT ON (MARKET_TYPE) MARKET_TYPE AS market, SCORE::float8 AS score, BLEND_SCORE::float8 AS blend,
               CHAMPION_SCORE::float8 AS champion, PASSED AS passed, TRAINED_AT AS trained_at
        FROM   TBL_MODEL_RUN ORDER BY MARKET_TYPE, TRAINED_AT DESC
    """):
        score.add_metric([r["market"], "lgbm"], r["score"])
        score.add_metric([r["market"], "blend"], r["blend"])
        if r["champion"] is not None:       # 배포된 모델이 없었거나 비교를 건너뛴 학습은 내보내지 않는다
            score.add_metric([r["market"], "champion"], r["champion"])
        passed.add_metric([r["market"]], 1 if r["passed"] else 0)
        trained.add_metric([r["market"]], r["trained_at"].timestamp())
    runs = GaugeMetricFamily("nongsdak_model_runs", "학습 횟수", labels=["market", "result"])
    for r in q("SELECT MARKET_TYPE AS market, PASSED AS passed, COUNT(*) AS n FROM TBL_MODEL_RUN GROUP BY 1, 2"):
        runs.add_metric([r["market"], "passed" if r["passed"] else "failed"], r["n"])

    price = GaugeMetricFamily("nongsdak_price_latest_timestamp_seconds", "가장 최근 가격 조사일", labels=["market"])
    for r in q("SELECT MARKET_TYPE AS market, MAX(SURVEY_DATE) AS d FROM TBL_DAILY_PRICE GROUP BY 1"):
        price.add_metric([r["market"]], _ts(r["d"]))

    ape = GaugeMetricFamily("nongsdak_forecast_eval_ape", "최근 예측 vs 실제 평균 % 오차", labels=["market", "h"])
    direc = GaugeMetricFamily("nongsdak_forecast_eval_direction", "최근 오를지 내릴지 맞힌 비율", labels=["market", "h"])
    cnt = GaugeMetricFamily("nongsdak_forecast_eval_count", "채점된 예측 수", labels=["market", "h"])
    for r in q("""
        SELECT MARKET_TYPE AS market, H AS h, COUNT(*) AS n, AVG(APE)::float8 AS ape,
               AVG(DIRECTION_OK::int)::float8 AS dir
        FROM   V_FORECAST_EVAL
        WHERE  ACTUAL_DATE >= CURRENT_DATE - %(days)s
        GROUP  BY 1, 2
    """, {"days": EVAL_DAYS}):
        ape.add_metric([r["market"], str(r["h"])], r["ape"])
        direc.add_metric([r["market"], str(r["h"])], r["dir"])
        cnt.add_metric([r["market"], str(r["h"])], r["n"])
    return [info, rows, base, score, passed, trained, runs, price, ape, direc, cnt]


class ModelCollector:
    """prometheus_client 의 사용자 정의 수집기 — /metrics 를 만들 때마다 collect() 가 불린다."""

    def collect(self):
        now = time.monotonic()
        if now - _cache["at"] >= CACHE_SECONDS:
            try:
                _cache["families"] = _families()
            except Exception:           # DB 가 잠깐 안 돼도 /metrics(요청 지표)는 그대로 나가게 — 이 지표만 빠진다
                _cache["families"] = []
            _cache["at"] = now
        yield from _cache["families"]

    def describe(self):
        return []                       # 등록할 때 collect() 를 미리 부르지 않게 (DB 없이도 앱이 뜨게)


_registered = False


def register():
    global _registered
    if not _registered:
        REGISTRY.register(ModelCollector())
        _registered = True


def clear_cache():
    _cache["at"] = 0.0
