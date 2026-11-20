"""가격 예측 서빙 — collector/predict.py(매일 예측 저장) · /api/forecast · /api/v1/forecast · 예측 vs 실제 뷰.

실제 PostgreSQL 로 돈다. 가짜 가격(평일, 3년)을 넣고 예측을 만든 뒤 API 응답 모양(화면과의 약속)을 본다.
"""

from datetime import date, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from collector import predict as job
from ml import predict
from tests.conftest import add_price


def _fill(conn, item="211", kind="03", rank="상품", end=date(2026, 11, 18), years=3, market="소매", base=2000.0,
          start=None):
    d = start or end - timedelta(days=365 * years)
    while d <= end:
        if d.weekday() < 5:
            doy = d.timetuple().tm_yday
            add_price(conn, d.isoformat(), item=item, kind=kind, rank=rank, market=market,
                      price=round(base * (1 + 0.3 * np.sin(2 * np.pi * doy / 365))))
        d += timedelta(days=1)


@pytest.fixture
def conn(pg_db, tmp_path, monkeypatch):
    pg_db.execute("TRUNCATE TBL_PRICE_FORECAST")
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))      # 배포된 LightGBM 없음 → blend (LightGBM 경로는 test_pg_train)
    return pg_db


def test_predict_job_writes_three_horizons(conn):
    _fill(conn)
    _fill(conn, item="111", kind="01", start=date(2026, 3, 2))       # 한 해(달력)뿐 — 계절 모양을 못 만든다
    _fill(conn, item="232", kind="01", end=date(2026, 9, 1))         # 철 지난 품종 — 예측하지 않는다
    job.main(["--market", "소매"])
    rows = conn.execute("""SELECT ITEM_CODE, H, BASE_DATE, TARGET_DATE, MODEL, FALLBACK
                           FROM TBL_PRICE_FORECAST ORDER BY 1, 2""").fetchall()
    assert [(r[0], r[1]) for r in rows] == [("111", 7), ("111", 14), ("111", 28),
                                           ("211", 7), ("211", 14), ("211", 28)]
    assert all(r[2] == date(2026, 11, 18) and r[3] == r[2] + timedelta(days=r[1]) for r in rows)
    assert {r[4] for r in rows} == {predict.MODEL}
    assert [r[5] for r in rows if r[0] == "111"] == [True] * 3     # naive 로 메움
    assert [r[5] for r in rows if r[0] == "211"] == [False] * 3
    job.main(["--market", "소매"])                                    # 다시 돌려도 한 줄씩
    assert conn.execute("SELECT COUNT(*) FROM TBL_PRICE_FORECAST").fetchone()[0] == 6


def test_blend_is_half_of_seasonal_change(conn):
    """예측 = 기준일 가격 × (1 + 예년 변화율) / 2.

    가짜 자료는 1 + 0.3·sin(2π·연중일/365) 모양이라 10월 초가 가장 싸고 그 뒤로 오른다 — 11월 → 12월은 오른다.
    """
    _fill(conn)
    [s] = predict.load_all_series(app_module.db._query, "소매")
    f = predict.forecast_series(s, "소매")
    assert [x.h for x in f] == [7, 14, 28] and not any(x.fallback for x in f)
    shape = lambda d: 1 + 0.3 * np.sin(2 * np.pi * d.timetuple().tm_yday / 365)   # noqa: E731
    for x in f:
        full = shape(x.target_date.astype(object)) / shape(x.base_date.astype(object))   # 예년 변화율
        assert abs(x.price / x.base_price - (1 + full) / 2) < 0.02     # 절반만큼 (평활 · 반올림 오차 안)
    assert f[2].price > f[0].base_price                                # 11월 중순 → 12월 중순, 오름


def test_forecast_api_contract(conn):
    _fill(conn)
    job.main(["--market", "소매"])
    c = TestClient(app_module.app)
    r = c.get("/api/forecast?item=211&kind=03&market=retail").json()
    assert set(r) >= {"item_code", "kind_code", "rank", "unit", "base_date", "base_price", "model", "points"}
    assert r["rank"] == "상품" and r["unit"] == "1포기" and r["base_date"] == "2026-11-18" and r["model"] == "blend"
    assert [p["h"] for p in r["points"]] == [7, 14, 28]
    p = r["points"][0]
    assert p["target_date"] == "2026-11-25" and isinstance(p["price"], int)
    assert abs(p["change_pct"] - (p["price"] / r["base_price"] - 1) * 100) < 0.1     # 반올림 차이만

    # 예측이 없는 등급 → 404 가 아니라 빈 points (화면이 예측 칸만 숨긴다)
    empty = c.get("/api/forecast?item=211&kind=03&rank=중품&market=retail").json()
    assert empty["points"] == [] and empty["rank"] == "중품"
    assert c.get("/api/forecast?item=999&kind=01&market=retail").status_code == 404


def test_v1_forecast_needs_key_and_wraps(conn):
    _fill(conn)
    job.main(["--market", "소매"])
    c = TestClient(app_module.app)
    assert c.get("/api/v1/forecast?item=211&kind=03").status_code == 401
    c.post("/api/auth/signup", json={"login_id": "fc_user1", "password": "test-pass-1234", "nickname": "시험"})
    key = c.post("/api/keys", json={"name": "k"}).json()["key"]
    r = c.get("/api/v1/forecast?item=211&kind=03", headers={"X-API-Key": key}).json()
    assert r["meta"]["model"] == "blend" and r["meta"]["base_date"] == "2026-11-18"
    assert [p["h"] for p in r["data"]] == [7, 14, 28]


def test_eval_view_matches_actuals(conn):
    _fill(conn, end=date(2026, 11, 25))
    conn.execute("""INSERT INTO TBL_PRICE_FORECAST (BASE_DATE, MARKET_TYPE, ITEM_CODE, KIND_CODE, RANK_NAME, H,
                        TARGET_DATE, BASE_PRICE, PRICE, MODEL, MODEL_VERSION)
                    VALUES ('2026-11-18', '소매', '211', '03', '상품', 7, '2026-11-25', 1000, 1100, 'blend', 'blend-1')""")
    actual = conn.execute("""SELECT PRICE_TODAY FROM TBL_DAILY_PRICE WHERE SURVEY_DATE = '2026-11-25'""").fetchone()[0]
    ape, act = conn.execute("SELECT APE, ACTUAL FROM V_FORECAST_EVAL").fetchone()
    assert act == actual and abs(float(ape) - abs(1100 - float(actual)) / float(actual)) < 1e-9
