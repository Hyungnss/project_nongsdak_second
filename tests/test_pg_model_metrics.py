"""예측 모델 지표 (backend/model_metrics.py) — 실제 PostgreSQL. /metrics 에 모델 상태가 나오는가."""

import re

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from collector import predict as job
from tests.test_pg_forecast import _fill

# 앱은 backend/ 를 경로에 넣고 `import model_metrics` 로 부른다 — 'backend.model_metrics' 와는 다른 모듈 객체라
# 앱이 쓰는 그 객체를 고친다
model_metrics = app_module.model_metrics


@pytest.fixture
def client(pg_db, tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))       # 배포된 LightGBM 없음 → blend 로 예측
    model_metrics.clear_cache()
    yield TestClient(app_module.app), pg_db
    model_metrics.clear_cache()


def _value(text, name, **labels):
    """지표 한 줄의 값. 라벨 순서와 상관없이 찾는다."""
    for line in text.splitlines():
        if not line.startswith(name + "{"):
            continue
        got = dict(re.findall(r'(\w+)="([^"]*)"', line[line.index("{"):line.index("}")]))
        if all(got.get(k) == v for k, v in labels.items()):
            return float(line.rsplit(" ", 1)[1])
    return None


def test_metrics_show_serving_model_gate_and_freshness(client):
    c, conn = client
    _fill(conn)
    job.main(["--market", "소매"])
    conn.execute("""INSERT INTO TBL_MODEL_RUN (MODEL_VERSION, MARKET_TYPE, MODEL, TRAINED_AT, DATA_END, TRAIN_ROWS,
                        HOLDOUT_START, HOLDOUT_END, SCORE, BLEND_SCORE, PARITY_DIFF, PASSED, REASON, DEPLOYED)
                    VALUES ('lgbm-retail-x', '소매', 'lgbm', '2026-11-22 07:43+09', '2026-11-21', 700000,
                            '2026-08-25', '2026-10-19', 1.0864, 1.1183, 0, TRUE, '통과', TRUE)""")
    t = c.get("/metrics").text
    assert _value(t, "nongsdak_model_info", market="소매", model="blend", version="blend-1") == 1
    assert _value(t, "nongsdak_forecast_rows", market="소매", model="blend") == 3
    assert _value(t, "nongsdak_model_gate_score", market="소매", model="lgbm") == pytest.approx(1.0864)
    assert _value(t, "nongsdak_model_gate_score", market="소매", model="blend") == pytest.approx(1.1183)
    assert _value(t, "nongsdak_model_gate_passed", market="소매") == 1
    assert _value(t, "nongsdak_model_runs", market="소매", result="passed") == 1
    # 2026-11-18(한국 자정) — 예측 기준일 · 가격 최신일
    assert _value(t, "nongsdak_forecast_base_date_timestamp_seconds", market="소매") == 1794927600
    assert _value(t, "nongsdak_price_latest_timestamp_seconds", market="소매") == 1794927600
    assert _value(t, "nongsdak_forecast_eval_count", market="소매", h="7") is None    # 아직 채점된 예측 없음


def test_metrics_survive_db_error(client, monkeypatch):
    """DB 를 못 읽어도 /metrics 는 200 — 요청 지표는 그대로, 모델 지표만 빠진다."""
    c, _ = client
    monkeypatch.setattr(model_metrics.db, "_query", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    r = c.get("/metrics")
    assert r.status_code == 200 and "nongsdak_model_info" not in r.text and "http_requests_total" in r.text


def test_metrics_show_champion_score_when_compared(client):
    c, conn = client
    conn.execute("""INSERT INTO TBL_MODEL_RUN (MODEL_VERSION, MARKET_TYPE, MODEL, TRAINED_AT, DATA_END, TRAIN_ROWS,
                        HOLDOUT_START, HOLDOUT_END, SCORE, BLEND_SCORE, CHAMPION_VERSION, CHAMPION_SCORE, PARITY_DIFF,
                        PASSED, REASON, DEPLOYED)
                    VALUES ('lgbm-retail-b', '소매', 'lgbm', '2026-11-29 03:10+09', '2026-11-28', 700000,
                            '2026-09-01', '2026-10-26', 1.0900, 1.1183, 'lgbm-retail-a', 1.0800, 0, FALSE,
                            '챔피언보다 나쁨 (1.090 ≥ 1.080)', FALSE),
                           ('lgbm-wholesale-a', '도매', 'lgbm', '2026-11-29 03:20+09', '2026-11-28', 600000,
                            '2026-09-01', '2026-10-26', 0.9500, 0.9900, NULL, NULL, 0, TRUE, '통과', TRUE)""")
    t = c.get("/metrics").text
    assert _value(t, "nongsdak_model_gate_score", market="소매", model="champion") == pytest.approx(1.08)
    assert _value(t, "nongsdak_model_gate_passed", market="소매") == 0
    assert _value(t, "nongsdak_model_gate_score", market="도매", model="champion") is None   # 비교 안 함 → 안 내보냄
    assert _value(t, "nongsdak_model_gate_score", market="도매", model="lgbm") == pytest.approx(0.95)
