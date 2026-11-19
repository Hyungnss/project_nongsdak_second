"""공개 API(/api/v1) · API 키(/api/keys) — 실제 PostgreSQL 로 확인한다.

키 발급 · 폐기 · 한도, 호출 제한(분당 · 하루), 사용량 기록, 오류 모양, 엔드포인트 응답.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from tests.conftest import add_price

api_v1 = app_module.api_v1
apikeys = app_module.apikeys


@pytest.fixture
def client(pg_db):
    return TestClient(app_module.app)


def _signup(client, login_id="apiuser_1"):
    r = client.post("/api/auth/signup", json={"login_id": login_id, "password": "test-pass-1234",
                                              "nickname": "시험"})
    assert r.status_code in (200, 201), r.text


def _key(client, name="시험 키"):
    r = client.post("/api/keys", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _prices(conn, days=20, end=date(2026, 11, 18)):
    for i in range(days):
        d = (end - timedelta(days=days - 1 - i)).isoformat()
        add_price(conn, d, price=1000.0 + 10 * i, normal=1500.0)
        add_price(conn, d, rank="중품", price=800.0 + 10 * i)
        add_price(conn, d, item="111", kind="01", item_name="쌀", kind_name="20kg", unit="20kg",
                  category="100", category_name="식량작물", price=50000.0)


# ── 키 ────────────────────────────────────────────────────────────────────
def test_keys_need_login(client):
    assert client.get("/api/keys").status_code == 401
    assert client.post("/api/keys", json={"name": "x"}).status_code == 401


def test_key_issue_list_revoke(client, pg_db):
    _signup(client)
    k = _key(client)
    assert k["key"].startswith("nsk_") and len(k["key"]) == 47
    assert k["prefix"] == k["key"][:12]

    # 원문은 저장하지 않는다 — 해시만
    stored = pg_db.execute("SELECT KEY_HASH, KEY_PREFIX FROM TBL_API_KEY").fetchone()
    assert stored[0] == apikeys.key_hash(k["key"]) and k["key"] not in stored

    listed = client.get("/api/keys").json()
    assert [x["key_no"] for x in listed["keys"]] == [k["key_no"]]
    assert "key" not in listed["keys"][0]                  # 목록에는 원문이 없다

    h = {"X-API-Key": k["key"]}
    assert client.get("/api/v1/items", headers=h).status_code == 200
    assert client.delete(f"/api/keys/{k['key_no']}").json()["keys"] == []
    r = client.get("/api/v1/items", headers=h)
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_api_key"


def test_key_limit_per_user(client):
    _signup(client)
    for i in range(apikeys.MAX_KEYS):
        _key(client, f"k{i}")
    assert client.post("/api/keys", json={"name": "하나 더"}).status_code == 409
    assert client.post("/api/keys", json={"name": "  "}).status_code == 400


def test_cannot_revoke_someone_elses_key(client):
    _signup(client, "owner_01")
    k = _key(client)
    client.post("/api/auth/logout")
    _signup(client, "other_01")
    assert client.delete(f"/api/keys/{k['key_no']}").status_code == 404


# ── 인증 · 오류 모양 ──────────────────────────────────────────────────────
def test_v1_requires_key_with_error_shape(client):
    r = client.get("/api/v1/items")
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "missing_api_key", "message": r.json()["error"]["message"]}}
    r = client.get("/api/v1/items", headers={"X-API-Key": "nsk_not-a-real-key"})
    assert r.json()["error"]["code"] == "invalid_api_key"


def test_status_needs_no_key(client, pg_db):
    _prices(pg_db, days=3)
    r = client.get("/api/v1/status")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["api_version"] == "v1"
    assert body["data"]["retail"]["latest_date"] == "2026-11-18"
    assert set(body["data"]) == {"retail", "wholesale"}


def test_validation_error_shape(client):
    _signup(client)
    h = {"X-API-Key": _key(client)["key"]}
    r = client.get("/api/v1/prices/history", headers=h)          # item · kind 빠짐
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_parameter"
    r = client.get("/api/v1/items?market=nowhere", headers=h)
    assert r.status_code == 422


# ── 엔드포인트 ────────────────────────────────────────────────────────────
def test_items_latest_history_changes(client, pg_db):
    _prices(pg_db)
    _signup(client)
    h = {"X-API-Key": _key(client)["key"]}

    items = client.get("/api/v1/items", headers=h).json()
    assert items["meta"]["count"] == 2
    cabbage = next(i for i in items["data"] if i["item_code"] == "211")
    assert [r["rank"] for r in cabbage["kinds"][0]["ranks"]] == ["상품", "중품"]
    assert client.get("/api/v1/items?category=100", headers=h).json()["meta"]["count"] == 1

    latest = client.get("/api/v1/prices/latest?item=211&rank=상품", headers=h).json()
    assert latest["data"] == [{
        "survey_date": "2026-11-18", "item_code": "211", "item_name": "배추",
        "kind_code": "01", "kind_name": "가을(1포기)", "rank": "상품", "unit": "1포기",
        "category_code": "200", "price": 1190.0, "price_1y_ago": None, "price_normal": 1500.0,
    }]
    assert client.get("/api/v1/prices/latest?item=999", headers=h).status_code == 404

    hist = client.get("/api/v1/prices/history?item=211&kind=01&rank=상품&start=2026-11-10&end=2026-11-18",
                      headers=h).json()
    assert [d["survey_date"] for d in hist["data"]][0] == "2026-11-10" and hist["meta"]["count"] == 9
    r = client.get("/api/v1/prices/history?item=211&kind=01&start=2024-01-01&end=2026-11-18", headers=h)
    assert r.status_code == 422                                   # 366일 초과

    ch = client.get("/api/v1/changes?period=1d", headers=h).json()
    up = next(c for c in ch["data"] if c["item_code"] == "211")
    assert up["price"] == 1190.0 and up["prev_price"] == 1180.0 and up["change_pct"] == 0.8


def test_markets_do_not_mix(client, pg_db):
    add_price(pg_db, "2026-11-18", price=1000.0, market="소매")
    add_price(pg_db, "2026-11-18", price=700.0, market="도매")
    _signup(client)
    h = {"X-API-Key": _key(client)["key"]}
    r = client.get("/api/v1/prices/latest?market=wholesale", headers=h).json()
    assert [d["price"] for d in r["data"]] == [700.0] and r["meta"]["market"] == "wholesale"


# ── 호출 제한 · 사용량 ────────────────────────────────────────────────────
def test_rate_limit_per_minute_is_per_user(client, monkeypatch):
    monkeypatch.setitem(apikeys.PLANS, "free", {"per_minute": 3, "per_day": 100})
    _signup(client)
    a, b = _key(client, "a")["key"], _key(client, "b")["key"]

    r = client.get("/api/v1/items", headers={"X-API-Key": a})
    assert r.headers["X-RateLimit-Limit"] == "3" and r.headers["X-RateLimit-Remaining"] == "2"
    client.get("/api/v1/items", headers={"X-API-Key": a})
    client.get("/api/v1/items", headers={"X-API-Key": b})        # 다른 키여도 같은 회원
    r = client.get("/api/v1/items", headers={"X-API-Key": b})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["Retry-After"]) >= 1


def test_daily_quota_survives_restart(client, pg_db, monkeypatch):
    """하루 한도는 DB 의 오늘 사용량에서 이어 센다 — 재시작(메모리 초기화)해도 풀리지 않는다."""
    monkeypatch.setitem(apikeys.PLANS, "free", {"per_minute": 100, "per_day": 2})
    _signup(client)
    h = {"X-API-Key": _key(client)["key"]}
    assert client.get("/api/v1/items", headers=h).status_code == 200
    assert client.get("/api/v1/items", headers=h).status_code == 200

    api_v1.limiter.reset()                                         # 재시작 흉내
    r = client.get("/api/v1/items", headers=h)
    assert r.status_code == 429 and r.json()["error"]["code"] == "daily_quota_exceeded"


def test_usage_is_recorded_and_reported(client, pg_db):
    _prices(pg_db, days=3)
    _signup(client)
    h = {"X-API-Key": _key(client)["key"]}
    client.get("/api/v1/items", headers=h)
    client.get("/api/v1/items", headers=h)
    client.get("/api/v1/prices/latest?item=999", headers=h)       # 404
    client.get("/api/v1/status")                                    # 키 없음 — 세지 않는다

    rows = pg_db.execute("""SELECT ENDPOINT, STATUS_CLASS, CALLS FROM TBL_API_USAGE_DAILY
                            ORDER BY ENDPOINT""").fetchall()
    assert rows == [("/items", "2xx", 2), ("/prices/latest", "4xx", 1)]
    assert pg_db.execute("SELECT LAST_USED_AT IS NOT NULL FROM TBL_API_KEY").fetchone()[0]

    u = client.get("/api/keys/usage?days=7").json()
    assert u["today"]["calls"] == 3 and u["today"]["remaining"] == apikeys.PLANS["free"]["per_day"] - 3
    assert len(u["daily"]) == 7 and u["daily"][-1]["errors"] == 1
    assert u["by_endpoint"][0] == {"endpoint": "/items", "calls": 2}


def test_cors_allows_browsers_without_cookies(client):
    r = client.options("/api/v1/items", headers={
        "Origin": "https://example.com", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-API-Key"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in r.headers


def test_internal_docs_hidden_and_v1_docs_public(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    spec = client.get("/api/v1/openapi.json").json()
    assert set(spec["paths"]) == {"/status", "/items", "/prices/latest", "/prices/history", "/changes"}
    assert client.get("/api/v1/docs").status_code == 200
