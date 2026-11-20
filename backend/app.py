"""농스닥 웹서비스 — PostgreSQL 기반 FastAPI.

시세는 TBL_DAILY_PRICE 만 사용한다. 모든 시세 API 가 ?market=retail|wholesale 을 받는다 (기본 소매).
회원가입 · 로그인은 auth.py 에 있다 (TBL_USER · TBL_USER_SESSION). 시세는 로그인 없이 본다.
장바구니는 cart.py 에 있다 (TBL_CART_ITEM). 로그인한 회원만 쓴다.
보여주는 것은 두 가지다.
  1. 품목을 고르면 오늘 가격과 어제·1주일전·2주일전·1개월전 대비 변동
  2. 어제 대비 / 일주일 대비 많이 싸진·비싸진 품목 Top 5

실행:
    uv run uvicorn backend.app:app --reload
    -> http://127.0.0.1:8000
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent))

import api_v1  # noqa: E402
import apikeys  # noqa: E402
import forecast  # noqa: E402
import auth  # noqa: E402
import cart  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402

# 화면 파일은 루트의 frontend/ 에 있다. 주소는 예전처럼 /static/... 으로 낸다.
STATIC_DIR = Path(__file__).resolve().parent.parent / "frontend"

# 모든 API 가 받는 시장 구분. 기본값 retail 이라 market 을 안 붙이던 예전 호출은 그대로 소매를 본다.
Market = Literal["retail", "wholesale"]
MARKET_Q = Query("retail", description="retail=소매 · wholesale=도매")


@asynccontextmanager
async def lifespan(app):
    """기동할 때 커넥션 풀을 먼저 만든다.

    그냥 두면 첫 요청이 들어올 때 붙느라 첫 사용자만 기다리게 되므로 미리 만들어 둔다.
    DB 가 안 떠 있어도 서버는 뜨게 한다 — 그래야 화면에 오류를 보여줄 수 있다.
    """
    try:
        db._init_pool()
        print("PostgreSQL 커넥션 풀 준비 완료")
    except Exception as e:
        print(f"PostgreSQL 연결 실패 — 첫 요청 때 다시 시도합니다: {e}")
    yield


app = FastAPI(
    title="농스닥",
    description="KAMIS 소매·도매 시세로 오늘 가격과 최근 변동을 보여주는 서비스",
    version=config.APP_VERSION,
    lifespan=lifespan,
    # 화면용 API(/api/*) 문서는 내놓지 않는다 — 화면에 맞춰 언제든 바뀌는 내부 API 라서.
    # 바깥에 공개하는 API 와 문서는 /api/v1 (api_v1.py) 에 따로 있다: /api/v1/docs
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# 회원가입 · 로그인 (/api/auth/*). 시세 API 는 로그인 없이 그대로 열려 있다.
app.include_router(auth.router)
# 장바구니 (/api/cart/*). 로그인한 회원만 쓴다 (TBL_CART_ITEM).
app.include_router(cart.router)
# 공개 API 키 발급 · 폐기 · 사용량 (/api/keys/*). 로그인한 회원만 (TBL_API_KEY).
app.include_router(apikeys.router)
# 가격 예측 (/api/forecast). 화면용 — collector/predict.py 가 매일 만든 예측을 꺼낸다 (TBL_PRICE_FORECAST).
app.include_router(forecast.router)
# 공개 API (/api/v1/*). API 키로 부른다. 문서는 /api/v1/docs
app.mount("/api/v1", api_v1.v1)


@app.get("/api/meta")
def meta(market: Market = MARKET_Q):
    """데이터 기간과 규모."""
    return db.get_meta(db.MARKETS[market])


@app.get("/api/products")
def products(market: Market = MARKET_Q):
    """품목 -> 품종 목록. 등급은 대표 등급이 자동으로 붙는다."""
    items = db.list_products(db.MARKETS[market])
    return {
        "count": len(items),
        "kinds": sum(len(i["kinds"]) for i in items),
        "items": items,
    }


@app.get("/api/detail")
def detail(
    item: str = Query(..., description="품목코드"),
    kind: str | None = Query(None, description="품종코드 (생략 시 첫 품종)"),
    rank: str | None = Query(None, description="등급 (생략 시 대표 등급)"),
    days: int = Query(90, ge=7, le=365, description="차트에 담을 최근 일수"),
    market: Market = MARKET_Q,
):
    """한 품종의 오늘 가격과 시점별 비교."""
    mkt = db.MARKETS[market]
    if kind is None:
        items = {i["item_code"]: i for i in db.list_products(mkt)}
        if item not in items:
            raise HTTPException(404, f"없는 품목코드예요: {item}")
        kind = items[item]["default_kind"]

    d = db.get_detail(item, kind, rank, chart_days=days, market=mkt)
    if d is None:
        raise HTTPException(404, f"가격 자료가 없어요: {item}/{kind}")
    return d


@app.get("/api/movers")
def movers(
    offset: int = Query(1, description="비교 기준 일수 (1=직전 조사일, 7=일주일 전)"),
    limit: int = Query(5, ge=1, le=20),
    market: Market = MARKET_Q,
):
    """많이 오른/내린 품목. 품목당 대표 등급 하나만 집계한다."""
    if offset not in (1, 7, 14, 30):
        raise HTTPException(400, "offset 은 1, 7, 14, 30 중 하나여야 해요")
    return db.get_movers(offset=offset, limit=limit, market=db.MARKETS[market])


@app.get("/api/fortune")
def fortune(
    offset: int = Query(1, description="비교 기준 일수 (1=직전 조사일)"),
    market: Market = MARKET_Q,
):
    """포춘쿠키 후보 — 비교 가능한 품목 전부. 화면에서 하나를 무작위로 뽑는다."""
    if offset not in (1, 7, 14, 30):
        raise HTTPException(400, "offset 은 1, 7, 14, 30 중 하나여야 해요")
    return db.get_fortune(offset=offset, market=db.MARKETS[market])


@app.get("/api/briefing")
def briefing(market: Market = MARKET_Q):
    """장보기 브리핑 — 지금 조사되는 품목 전부를 평년가 · 1주 변화 · 최근 추이와 함께."""
    return db.get_briefing(market=db.MARKETS[market])


@app.get("/api/health")
def health():
    """서버와 DB 가 살아 있는지. 컨테이너 healthcheck 와 배포 직후 확인이 부른다.

    DB 에 SELECT 1 을 보내 본다. 실패하면 503 — 서버만 떠 있고 DB 를 못 보는 상태를
    '정상' 으로 보지 않기 위해서다.
    """
    try:
        db._query("SELECT 1 AS ok")
    except Exception as e:
        raise HTTPException(503, f"DB 에 접속할 수 없어요: {type(e).__name__}")
    return {"ok": True, "version": config.APP_VERSION}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/developers")
def developers():
    """공개 API 소개 · 키 발급 · 사용량 · 문서 (frontend/developers.html)."""
    return FileResponse(STATIC_DIR / "developers.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
