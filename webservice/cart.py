"""장바구니 (/api/cart). 로그인한 회원만 쓴다.

회원마다 장바구니 하나. 가격은 저장하지 않고 열 때마다 최신 소매가로 붙인다.
그래야 '지난주보다 얼마 더 드는지'가 오늘 값으로 나온다.

가격은 장보기 브리핑(db.get_briefing)과 같은 자료에서 꺼낸다. 첫 화면 목록과
장바구니가 같은 품목에 서로 다른 값을 말하지 않도록 한 곳에서 가져온다.
철이 지나 브리핑에 없는 품목만 상세(db.get_detail)로 마지막 조사 가격을 찾는다.

모든 쓰기 API 는 바뀐 뒤의 장바구니 전체를 돌려준다. 화면은 받은 대로 다시 그리면 된다.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import auth
import db

router = APIRouter(prefix="/api/cart", tags=["cart"])

# 장보기 합계라 소매만 담는다. 도매가는 10kg · 상자 단위라 합계에 섞으면 숫자가 의미를 잃는다.
MARKET = db.RETAIL
QTY_MIN, QTY_MAX = 1, 99
# 한 사람이 담을 수 있는 줄 수. 품목이 100개 남짓이라 이 이상은 실수거나 장난이다.
MAX_LINES = 50


class AddIn(BaseModel):
    item_code: str
    kind_code: str
    rank_name: str | None = None      # 비우면 대표 등급
    qty: int = Field(1, ge=QTY_MIN, le=QTY_MAX)


class QtyIn(BaseModel):
    qty: int = Field(..., ge=QTY_MIN, le=QTY_MAX)


def _rows(user_no):
    return db._query("""
        SELECT CART_NO, ITEM_CODE, KIND_CODE, RANK_NAME, QTY
        FROM   TBL_CART_ITEM
        WHERE  USER_NO = :u
        ORDER  BY ADDED_AT, CART_NO
    """, {"u": user_no})


def _priced(user_no):
    """담긴 줄마다 최신 소매가 · 1주 변화 · 평년가를 붙인다."""
    rows = _rows(user_no)
    brief = {}
    if rows:
        brief = {(c["item_code"], c["kind_code"], c["rank_name"]): c
                 for c in db.get_briefing(market=MARKET)["items"]}

    items = []
    for r in rows:
        key = (r["item_code"], r["kind_code"], r["rank_name"])
        line = {"cart_no": int(r["cart_no"]), "item_code": key[0], "kind_code": key[1],
                "rank_name": key[2], "qty": int(r["qty"])}
        c = brief.get(key)
        if c:
            line.update(item_name=c["item_name"], kind_name=c["kind_name"],
                        category=c["category"], unit=c["unit"], date=c["date"],
                        price=c["price"], change_7d=c["change_7d"],
                        normal=c["normal"], current=True)
        else:
            # 철이 지나 브리핑에서 빠진 품목. 마지막 조사 가격을 '지금 값이 아님' 표시와 함께 준다
            d = db.get_detail(*key, chart_days=7, market=MARKET)
            if d is None:
                line.update(item_name=None, current=False, price=None)
            else:
                wk = next((x for x in d["compares"] if x["target_offset"] == 7 and x["available"]), None)
                line.update(item_name=d["item_name"], kind_name=d["kind_name"],
                            category=d["category"], unit=d["unit"], date=d["date"],
                            price=d["price"], change_7d=wk["change_pct"] if wk else None,
                            normal=d["normal"], current=False)
        items.append(line)
    return {"market": MARKET, "count": len(items), "items": items}


def _owned(conn, cart_no, user_no):
    """그 줄이 이 회원 것인지. 남의 줄 번호를 넣어도 건드리지 못하게 한다."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM TBL_CART_ITEM WHERE CART_NO = :c AND USER_NO = :u",
                    {"c": cart_no, "u": user_no})
        if cur.fetchone() is None:
            raise HTTPException(404, "장바구니에 없는 품목입니다")


@router.get("")
def get_cart(user: dict = Depends(auth.require_user)):
    return _priced(user["user_no"])


@router.post("")
def add(body: AddIn, user: dict = Depends(auth.require_user)):
    """담기. 이미 담긴 품종 · 등급이면 수량을 더한다 (최대 99)."""
    products = {i["item_code"]: i for i in db.list_products(MARKET)}
    it = products.get(body.item_code)
    if not it or not any(k["kind_code"] == body.kind_code for k in it["kinds"]):
        raise HTTPException(404, "없는 품목입니다")
    rank = db._resolve_rank(body.item_code, body.kind_code, body.rank_name, MARKET)
    if rank is None or not db._series(body.item_code, body.kind_code, rank, limit=1, market=MARKET):
        raise HTTPException(404, "그 등급은 소매 가격 자료가 없습니다")

    uno = user["user_no"]
    with db._init_pool().acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM TBL_CART_ITEM WHERE USER_NO = :u", {"u": uno})
            (n,) = cur.fetchone()
            cur.execute("""
                SELECT 1 FROM TBL_CART_ITEM
                WHERE  USER_NO = :u AND ITEM_CODE = :i AND KIND_CODE = :k AND RANK_NAME = :r
            """, {"u": uno, "i": body.item_code, "k": body.kind_code, "r": rank})
            exists = cur.fetchone() is not None
            if not exists and n >= MAX_LINES:
                raise HTTPException(400, f"장바구니에는 {MAX_LINES}가지까지 담을 수 있어요")
            # 같은 품목을 두 번 눌러도 줄이 늘지 않도록 MERGE 로 한 번에 처리한다
            cur.execute("""
                MERGE INTO TBL_CART_ITEM t
                USING (SELECT :u AS USER_NO, :i AS ITEM_CODE, :k AS KIND_CODE, :r AS RANK_NAME
                       FROM dual) s
                ON (t.USER_NO = s.USER_NO AND t.ITEM_CODE = s.ITEM_CODE
                    AND t.KIND_CODE = s.KIND_CODE AND t.RANK_NAME = s.RANK_NAME)
                WHEN MATCHED THEN UPDATE SET t.QTY = LEAST(:qmax, t.QTY + :q)
                WHEN NOT MATCHED THEN
                    INSERT (CART_NO, USER_NO, ITEM_CODE, KIND_CODE, RANK_NAME, QTY)
                    VALUES (SEQ_CART_ITEM.NEXTVAL, s.USER_NO, s.ITEM_CODE, s.KIND_CODE, s.RANK_NAME, :q)
            """, {"u": uno, "i": body.item_code, "k": body.kind_code, "r": rank,
                  "q": body.qty, "qmax": QTY_MAX})
        conn.commit()
    return _priced(uno)


@router.patch("/{cart_no}")
def set_qty(cart_no: int, body: QtyIn, user: dict = Depends(auth.require_user)):
    with db._init_pool().acquire() as conn:
        _owned(conn, cart_no, user["user_no"])
        with conn.cursor() as cur:
            cur.execute("UPDATE TBL_CART_ITEM SET QTY = :q WHERE CART_NO = :c",
                        {"q": body.qty, "c": cart_no})
        conn.commit()
    return _priced(user["user_no"])


@router.delete("/{cart_no}")
def remove(cart_no: int, user: dict = Depends(auth.require_user)):
    with db._init_pool().acquire() as conn:
        _owned(conn, cart_no, user["user_no"])
        with conn.cursor() as cur:
            cur.execute("DELETE FROM TBL_CART_ITEM WHERE CART_NO = :c", {"c": cart_no})
        conn.commit()
    return _priced(user["user_no"])


@router.delete("")
def clear(user: dict = Depends(auth.require_user)):
    with db._init_pool().acquire() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM TBL_CART_ITEM WHERE USER_NO = :u", {"u": user["user_no"]})
        conn.commit()
    return _priced(user["user_no"])
