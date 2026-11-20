"""가격 예측 조회 — 화면용 /api/forecast (로그인 · 키 없음).

예측은 collector/predict.py 가 매일 TBL_PRICE_FORECAST 에 넣어 둔다. 여기서는 그 품종의 가장 최근 예측을 꺼낸다.
응답 모양은 화면(frontend/forecast.js)과 맞춘 약속이다 — 필드를 빼거나 이름을 바꾸지 않는다.

  GET /api/forecast?item=211&kind=03&rank=상품&market=retail
  {
    "item_code": "211", "kind_code": "03", "rank": "상품", "unit": "1포기",
    "base_date": "2026-11-20", "base_price": 2390, "model": "blend",
    "points": [{"h": 7, "target_date": "2026-11-27", "price": 2310, "change_pct": -3.3}, ...]
  }
  · rank 를 생략하면 대표 등급(화면과 같은 규칙)
  · 예측이 없는 품종(철 지남 · 자료 부족)은 "points": [] — 404 가 아니다 (화면이 예측 칸만 숨기면 되게)
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

import db

router = APIRouter(prefix="/api", tags=["forecast"])

Market = Literal["retail", "wholesale"]


def representative_rank(item, kind, market):
    for it in db.list_products(market):
        if it["item_code"] == item:
            for k in it["kinds"]:
                if k["kind_code"] == kind:
                    return k["rank_name"], k["unit"]
    return None, None


def latest_forecast(item, kind, rank, market):
    """그 품종 · 등급의 가장 최근 기준일 예측 (모델이 여럿이면 가장 늦게 만든 것)."""
    return db._query("""
        SELECT DISTINCT ON (H) H, BASE_DATE, BASE_PRICE::float8 AS base_price, TARGET_DATE,
               PRICE::float8 AS price, MODEL, MODEL_VERSION, FALLBACK
        FROM   TBL_PRICE_FORECAST
        WHERE  MARKET_TYPE = %(m)s AND ITEM_CODE = %(i)s AND KIND_CODE = %(k)s AND RANK_NAME = %(r)s
          AND  BASE_DATE = (SELECT MAX(BASE_DATE) FROM TBL_PRICE_FORECAST
                            WHERE MARKET_TYPE = %(m)s AND ITEM_CODE = %(i)s AND KIND_CODE = %(k)s
                              AND RANK_NAME = %(r)s)
        ORDER  BY H, CREATED_AT DESC
    """, {"m": market, "i": item, "k": kind, "r": rank})


def shape(item, kind, rank, unit, rows):
    if not rows:
        return {"item_code": item, "kind_code": kind, "rank": rank, "unit": unit,
                "base_date": None, "base_price": None, "model": None, "points": []}
    base_price = rows[0]["base_price"]
    return {
        "item_code": item, "kind_code": kind, "rank": rank, "unit": unit,
        "base_date": rows[0]["base_date"].isoformat(),
        "base_price": round(base_price),
        "model": rows[0]["model"],
        "model_version": rows[0]["model_version"],
        "points": [{
            "h": int(r["h"]),
            "target_date": r["target_date"].isoformat(),
            "price": round(r["price"]),
            "change_pct": round((r["price"] / base_price - 1) * 100, 1),
        } for r in rows],
    }


def get_forecast(item, kind, rank, market):
    mkt = db.MARKETS[market]
    rep_rank, unit = representative_rank(item, kind, mkt)
    if rep_rank is None:
        raise HTTPException(404, f"없는 품종이에요: {item}/{kind}")
    rank = rank or rep_rank
    return shape(item, kind, rank, unit, latest_forecast(item, kind, rank, mkt))


@router.get("/forecast")
def forecast(
    item: str = Query(..., description="품목코드"),
    kind: str = Query(..., description="품종코드"),
    rank: str | None = Query(None, description="등급 (생략하면 대표 등급)"),
    market: Market = Query("retail", description="retail=소매 · wholesale=도매"),
):
    """한 품종의 1 · 2 · 4주 뒤 예상 가격."""
    return get_forecast(item, kind, rank, market)
