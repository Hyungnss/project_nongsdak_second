"""웹 조회 SQL(backend/db.py)과 회원 · 장바구니 API 를 실제 PostgreSQL 로 돌려 본다.

시험 데이터는 한 품종의 짧은 가격 이력을 직접 넣어 만든다.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from tests.conftest import add_price

db = app_module.db
TODAY = date(2026, 11, 17)


def _series(conn, days=40, item="211", kind="01", rank="상품", start=1000.0, step=10.0, **kw):
    """평일만 days 일치 가격 (오래된 것부터 start 원, 하루에 step 원씩 오른다)."""
    d, n, out = TODAY, 0, []
    while n < days:
        if d.weekday() < 5:
            out.append(d)
            n += 1
        d -= timedelta(days=1)
    for i, day in enumerate(reversed(out)):
        add_price(conn, day.isoformat(), item=item, kind=kind, rank=rank,
                  price=start + step * i, normal=2000.0, year_ago=900.0, **kw)
    return out[0]                                   # 가장 최근 조사일


@pytest.fixture
def client(pg_db):
    return TestClient(app_module.app)


# ── 조회 ─────────────────────────────────────────────────────────────────
def test_meta_reads_dates_and_last_fetch(pg_db):
    _series(pg_db)
    pg_db.execute("""INSERT INTO TBL_FETCH_LOG (SURVEY_DATE, MARKET_TYPE, STATUS, ROWS_UPSERTED)
                     VALUES ('2026-11-17', '소매', 'OK', 40)""")
    m = db.get_meta("소매")
    assert m["latest"] == "2026-11-17" and m["latest_full"] == "2026-11-17"
    assert m["rows"] == 40 and m["items"] == 1
    u = m["updated_at"]
    assert u["survey_date"] == "2026-11-17" and u["status"] == "OK"
    assert "+" not in u["at"] and u["age_minutes"] >= 0      # 화면에는 시간대 없는 한국 시각


def test_detail_compares_with_nearest_survey_day(pg_db):
    _series(pg_db)
    d = db.get_detail("211", "01", market="소매")
    assert d["date"] == "2026-11-17" and d["price"] == 1390.0
    day = next(c for c in d["compares"] if c["label"] == "어제")
    assert day["date"] == "2026-11-16" and day["days_ago"] == 1     # 직전 조사일 (11-17 은 화요일)
    assert d["normal"] == 2000.0 and d["year_ago"] == 900.0
    assert d["chart"][-1]["date"] == "2026-11-17"


def test_zero_or_missing_prices_are_not_shown(pg_db):
    _series(pg_db)
    pg_db.execute("""UPDATE TBL_DAILY_PRICE SET PRICE_TODAY = NULL
                     WHERE SURVEY_DATE = '2026-11-17'""")
    assert db.get_detail("211", "01", market="소매")["date"] == "2026-11-16"


def test_list_products_prefers_latest_name_when_kamis_renames(pg_db):
    """KAMIS 가 품종 이름만 바꾸면(계란 특란 -> XL) 새 이름 · 오늘 날짜로 보여야 한다."""
    _series(pg_db, item="9903", kind="21", rank="일반란", item_name="계란", kind_name="특란10구",
            unit="10구", category="500", category_name="축산물")
    pg_db.execute("""UPDATE TBL_DAILY_PRICE SET KIND_NAME = 'XL10구'
                     WHERE SURVEY_DATE >= '2026-10-27'""")
    (egg,) = db.list_products("소매")
    (kind,) = egg["kinds"]
    assert kind["kind_name"] == "XL10구" and kind["days_stale"] == 0


def test_markets_do_not_mix(pg_db):
    _series(pg_db)
    _series(pg_db, start=30000.0, market="도매", kind_name="가을(10kg)", unit="10kg")
    assert db.get_detail("211", "01", market="소매")["price"] < 2000
    assert db.get_detail("211", "01", market="도매")["price"] > 30000


def test_briefing_and_api_routes(client, pg_db):
    _series(pg_db)
    b = client.get("/api/briefing").json()
    assert b["count"] == 1 and b["items"][0]["change_pct"] == pytest.approx(0.7, abs=0.1)
    it = b["items"][0]
    # 어제 · 1주 · 1달 전 가격과 날짜 ('지금 사기 좋아요' 카드의 비교 칸)
    assert it["prev_price"] > 0 and it["week_price"] > 0 and it["month_price"] > 0
    assert it["prev_date"] > it["week_date"] > it["month_date"]
    assert it["change_30d"] == pytest.approx((it["price"] / it["month_price"] - 1) * 100, abs=0.1)
    assert it["fc_7d"] is None                       # 아직 예측이 없다

    # 1주 뒤 예상 — 가장 최근 기준일의 7일 예측 (예전 예측 · 다른 기간은 고르지 않는다)
    last = date.fromisoformat(it["date"])
    for base, h, price in [(last - timedelta(days=7), 7, 1111), (last, 7, 2222), (last, 28, 3333)]:
        pg_db.execute("""INSERT INTO TBL_PRICE_FORECAST (BASE_DATE, MARKET_TYPE, ITEM_CODE, KIND_CODE, RANK_NAME, H,
                            TARGET_DATE, BASE_PRICE, PRICE, MODEL, MODEL_VERSION)
                         VALUES (%s, '소매', '211', '01', '상품', %s, %s, 1000, %s, 'lgbm', 'lgbm-retail-x')""",
                      (base, h, base + timedelta(days=h), price))
    it = client.get("/api/briefing").json()["items"][0]
    assert it["fc_7d"] == 2222 and it["fc_7d_date"] == (last + timedelta(days=7)).isoformat()
    for path in ["/api/meta", "/api/products", "/api/detail?item=211", "/api/movers", "/api/fortune"]:
        assert client.get(path).status_code == 200, path


# ── 회원 · 장바구니 ─────────────────────────────────────────────────────
def test_signup_login_and_cart_flow(client, pg_db):
    _series(pg_db)
    acct = {"login_id": "tester_01", "password": "test-pass-1234", "nickname": "시험"}
    r = client.post("/api/auth/signup", json=acct)
    assert r.status_code == 200
    assert client.post("/api/auth/signup", json=acct).status_code == 409    # 아이디 중복
    assert client.get("/api/auth/me").json()["user"]["login_id"] == "tester_01"

    # 같은 품종을 다시 담으면 줄이 늘지 않고 수량이 더해진다 (최대 99)
    client.post("/api/cart", json={"item_code": "211", "kind_code": "01", "qty": 2})
    cart = client.post("/api/cart", json={"item_code": "211", "kind_code": "01", "qty": 98}).json()
    (line,) = cart["items"]
    assert line["qty"] == 99 and line["price"] == 1390.0

    no = line["cart_no"]
    assert client.patch(f"/api/cart/{no}", json={"qty": 3}).json()["items"][0]["qty"] == 3
    assert client.delete(f"/api/cart/{no}").json()["items"] == []

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").json()["user"] is None
    assert client.post("/api/auth/login", json={**acct, "password": "wrong-pass"}).status_code == 401
    assert client.post("/api/auth/login", json=acct).status_code == 200


def test_session_expires_in_db_time(client, pg_db):
    client.post("/api/auth/signup", json={"login_id": "tester_02", "password": "test-pass-1234",
                                          "nickname": "시험"})
    days = pg_db.execute("SELECT EXTRACT(DAY FROM EXPIRES_AT - now()) FROM TBL_USER_SESSION").fetchone()[0]
    assert 13 <= days <= 14
