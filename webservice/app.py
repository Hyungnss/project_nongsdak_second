"""농스닥 웹서비스 — Oracle DB 기반 FastAPI.

TBL_DAILY_PRICE 만 사용한다. 보여주는 것은 두 가지다.
  1. 품목을 고르면 오늘 가격과 어제·1주일전·2주일전·1개월전 대비 변동
  2. 어제 대비 / 일주일 대비 많이 싸진·비싸진 품목 Top 5

실행:
    .venv\\Scripts\\python.exe -m uvicorn webservice.app:app --reload
    -> http://127.0.0.1:8000
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"


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
    description="KAMIS 소매 시세로 오늘 가격과 최근 변동을 보여주는 서비스",
    lifespan=lifespan,
)


@app.get("/api/meta")
def meta():
    """데이터 기간과 규모."""
    return db.get_meta()


@app.get("/api/products")
def products():
    """품목 -> 품종 목록. 등급은 대표 등급이 자동으로 붙는다."""
    items = db.list_products()
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
):
    """한 품종의 오늘 가격과 시점별 비교."""
    if kind is None:
        items = {i["item_code"]: i for i in db.list_products()}
        if item not in items:
            raise HTTPException(404, f"없는 품목코드입니다: {item}")
        kind = items[item]["default_kind"]

    d = db.get_detail(item, kind, rank, chart_days=days)
    if d is None:
        raise HTTPException(404, f"가격 자료가 없습니다: {item}/{kind}")
    return d


@app.get("/api/movers")
def movers(
    offset: int = Query(1, description="비교 기준 일수 (1=직전 조사일, 7=일주일 전)"),
    limit: int = Query(5, ge=1, le=20),
):
    """많이 오른/내린 품목. 품목당 대표 등급 하나만 집계한다."""
    if offset not in (1, 7, 14, 30):
        raise HTTPException(400, "offset 은 1, 7, 14, 30 중 하나여야 합니다")
    return db.get_movers(offset=offset, limit=limit)


@app.get("/api/fortune")
def fortune(
    offset: int = Query(1, description="비교 기준 일수 (1=직전 조사일)"),
):
    """포춘쿠키 후보 — 비교 가능한 품목 전부. 화면에서 하나를 무작위로 뽑는다."""
    if offset not in (1, 7, 14, 30):
        raise HTTPException(400, "offset 은 1, 7, 14, 30 중 하나여야 합니다")
    return db.get_fortune(offset=offset)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
