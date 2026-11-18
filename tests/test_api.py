"""backend/app.py — API 라우트가 올바르게 응답하는지.

CI(GitHub 서버)에서는 이 PC 의 Oracle 에 접속할 수 없다. 그래서 DB 를 부르는 함수
(db.get_meta 등)를 '정해진 값을 돌려주는 가짜 함수' 로 바꿔 끼우고, API 가 그 값을
받아 올바른 주소 · 상태 코드 · 모양으로 내보내는지만 본다.
실제 DB 와 함께 하는 확인은 로컬에서 서버를 띄워 한다.
"""

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module

db = app_module.db   # app.py 가 쓰는 바로 그 db 모듈 (여기를 바꿔 끼워야 API 에 반영된다)

PRODUCTS = [
    {"item_code": "211", "item_name": "배추", "category": "채소류", "default_kind": "01",
     "kinds": [{"kind_code": "01", "kind_name": "가을(1포기)", "rank_name": "상품"}]},
]


@pytest.fixture
def calls(monkeypatch):
    """DB 함수를 가짜로 바꾸고, 어떤 시장(market)으로 불렸는지 기록한다."""
    log = []

    def fake(name, result):
        def _f(*args, **kwargs):
            log.append((name, args, kwargs))
            return result(*args, **kwargs) if callable(result) else result
        monkeypatch.setattr(db, name, _f)

    fake("get_meta", lambda market: {"market": market, "latest": "2026-11-17", "rows": 10})
    fake("list_products", PRODUCTS)
    fake("get_briefing", lambda market: {"market": market, "count": 0, "items": []})
    fake("get_detail", lambda item, kind, rank, chart_days, market:
         {"item_code": item, "kind_code": kind, "market": market, "price": 3980.0}
         if item == "211" else None)
    # 로그인 쿠키가 없으면 DB 를 안 보지만, 혹시 보더라도 접속하지 않게 막아 둔다
    monkeypatch.setattr(db, "_init_pool", lambda: pytest.fail("시험 중에 실제 DB 에 접속하려 했다"))
    return log


@pytest.fixture
def client(calls):
    # `with TestClient(...)` 로 열지 않는다 — 그러면 lifespan 이 돌며 DB 풀을 만들려 한다.
    return TestClient(app_module.app)


def test_meta_default_is_retail(client, calls):
    r = client.get("/api/meta")
    assert r.status_code == 200
    assert r.json()["market"] == "소매"


def test_meta_wholesale(client):
    assert client.get("/api/meta?market=wholesale").json()["market"] == "도매"


def test_unknown_market_is_rejected(client):
    assert client.get("/api/meta?market=foo").status_code == 422


def test_products_and_briefing(client):
    assert client.get("/api/products").status_code == 200
    r = client.get("/api/briefing")
    assert r.status_code == 200 and r.json()["items"] == []


def test_detail_uses_default_kind_when_kind_missing(client):
    r = client.get("/api/detail?item=211")
    assert r.status_code == 200
    assert r.json()["kind_code"] == "01"     # PRODUCTS 의 default_kind


def test_detail_unknown_item_is_404(client):
    assert client.get("/api/detail?item=0000").status_code == 404
    assert client.get("/api/detail?item=0000&kind=00").status_code == 404


def test_detail_requires_item(client):
    assert client.get("/api/detail").status_code == 422


def test_cart_needs_login(client):
    assert client.get("/api/cart").status_code == 401


def test_me_without_login_is_null(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 200


def test_frontend_files_are_served(client):
    """화면 파일은 frontend/ 에 있지만 주소는 /static/... 이다 (폴더를 옮겨도 주소는 그대로)."""
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()
    for path in ["/static/auth.js", "/static/cart.js", "/static/auth.css", "/static/cart.css",
                 "/static/logo.png", "/static/favicon.png"]:
        assert client.get(path).status_code == 200, path


def test_health_ok(client, monkeypatch):
    monkeypatch.setattr(db, "_query", lambda *a, **k: [{"ok": 1}])
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_health_503_when_db_down(client, monkeypatch):
    """서버만 떠 있고 DB 를 못 보면 '정상' 이 아니다 — 배포 확인 · 컨테이너 healthcheck 가 이걸 본다."""
    def down(*a, **k):
        raise ConnectionError("db down")
    monkeypatch.setattr(db, "_query", down)
    assert client.get("/api/health").status_code == 503
