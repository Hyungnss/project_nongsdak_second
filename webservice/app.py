"""농스닥 웹서비스 — Oracle DB 기반 FastAPI.

시세는 TBL_DAILY_PRICE 만 사용한다. 모든 시세 API 가 ?market=retail|wholesale 을 받는다 (기본 소매).
회원가입 · 로그인은 auth.py 에 있다 (TBL_USER · TBL_USER_SESSION). 시세는 로그인 없이 본다.
보여주는 것은 두 가지다.
  1. 품목을 고르면 오늘 가격과 어제·1주일전·2주일전·1개월전 대비 변동
  2. 어제 대비 / 일주일 대비 많이 싸진·비싸진 품목 Top 5

실행:
    .venv\\Scripts\\python.exe -m uvicorn webservice.app:app --reload
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

import auth  # noqa: E402
import db  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"

# 모든 API 가 받는 시장 구분. 기본값 retail 이라 market 을 안 붙이던 예전 호출은 그대로 소매를 본다.
Market = Literal["retail", "wholesale"]
MARKET_Q = Query("retail", description="retail=소매 · wholesale=도매")


@asynccontextmanager
async def lifespan(app):
    """기동할 때 커넥션 풀을 먼저 만든다.

    풀은 지연 접속이라 그냥 두면 첫 요청이 들어올 때 붙는다. thick 모드 판별까지
    거치느라 첫 사용자만 몇 초를 기다리게 되므로 미리 만들어 둔다.
    DB 가 안 떠 있어도 서버는 뜨게 한다 — 그래야 화면에 오류를 보여줄 수 있다.
    """
    try:
        db._init_pool()
        print("Oracle 커넥션 풀 준비 완료")
    except Exception as e:
        print(f"Oracle 연결 실패 — 첫 요청 때 다시 시도합니다: {e}")
    yield


app = FastAPI(
    title="농스닥",
    description="KAMIS 소매·도매 시세로 오늘 가격과 최근 변동을 보여주는 서비스",
    lifespan=lifespan,
)

# 회원가입 · 로그인 (/api/auth/*). 시세 API 는 로그인 없이 그대로 열려 있다.
app.include_router(auth.router)


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
            raise HTTPException(404, f"없는 품목코드입니다: {item}")
        kind = items[item]["default_kind"]

    d = db.get_detail(item, kind, rank, chart_days=days, market=mkt)
    if d is None:
        raise HTTPException(404, f"가격 자료가 없습니다: {item}/{kind}")
    return d


@app.get("/api/movers")
def movers(
    offset: int = Query(1, description="비교 기준 일수 (1=직전 조사일, 7=일주일 전)"),
    limit: int = Query(5, ge=1, le=20),
    market: Market = MARKET_Q,
):
    """많이 오른/내린 품목. 품목당 대표 등급 하나만 집계한다."""
    if offset not in (1, 7, 14, 30):
        raise HTTPException(400, "offset 은 1, 7, 14, 30 중 하나여야 합니다")
    return db.get_movers(offset=offset, limit=limit, market=db.MARKETS[market])


@app.get("/api/fortune")
def fortune(
    offset: int = Query(1, description="비교 기준 일수 (1=직전 조사일)"),
    market: Market = MARKET_Q,
):
    """포춘쿠키 후보 — 비교 가능한 품목 전부. 화면에서 하나를 무작위로 뽑는다."""
    if offset not in (1, 7, 14, 30):
        raise HTTPException(400, "offset 은 1, 7, 14, 30 중 하나여야 합니다")
    return db.get_fortune(offset=offset, market=db.MARKETS[market])


@app.get("/api/briefing")
def briefing(market: Market = MARKET_Q):
    """장보기 브리핑 — 지금 조사되는 품목 전부를 평년가 · 1주 변화 · 최근 추이와 함께."""
    return db.get_briefing(market=db.MARKETS[market])


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
