"""공개 API(/api/v1) 키 — 발급 · 목록 · 폐기 · 사용량 (회원 전용, /api/keys/*).

키는 로그인한 회원만 받는다. 이 라우터는 로그인 쿠키로 동작하고(화면 /developers 가 부른다),
발급받은 키로 부르는 쪽은 api_v1.py 다.

설계 메모
  · 키 형식은 'nsk_' + 무작위 43자. 앞의 nsk_ 는 눈으로(또는 비밀 검사 도구가) 농스닥 키를
    알아보게 하려는 것이다.
  · DB 에는 SHA-256 만 둔다. 원문은 발급 응답에서 한 번만 보여 준다.
    비밀번호처럼 느린 해시(scrypt)를 쓰지 않는 이유: 키는 사람이 고른 값이 아니라 256비트 무작위라
    맞춰 보기 공격이 성립하지 않고, 요청마다 확인하므로 빨라야 한다. (세션 토큰과 같은 방식)
  · 폐기한 키의 행은 지우지 않는다. 사용량 기록이 그 키를 가리키고 있어서다.
"""

import hashlib
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
import config
import db

router = APIRouter(prefix="/api/keys", tags=["keys"])

KEY_PREFIX = "nsk_"
PREFIX_LEN = 12          # 화면에 보여 줄 앞부분 (nsk_ + 8자)
MAX_KEYS = 3             # 회원 한 명이 동시에 가질 수 있는 키
NAME_MAX = 40

# 요금제별 한도. 한도는 키가 아니라 '회원' 단위로 센다 — 키를 여러 개 만들어 늘리지 못하게.
PLANS = {
    "free": {"per_minute": 60, "per_day": 1000},
}


def new_key():
    return KEY_PREFIX + secrets.token_urlsafe(32)


def key_hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def find_active_key(raw):
    """키 원문으로 살아 있는 키를 찾는다. 없거나 폐기됐으면 None."""
    if not raw or not raw.startswith(KEY_PREFIX):
        return None
    rows = db._query("""
        SELECT k.KEY_NO, k.USER_NO, k.PLAN
        FROM   TBL_API_KEY k
        WHERE  k.KEY_HASH = %(h)s AND k.REVOKED_AT IS NULL
    """, {"h": key_hash(raw)})
    return rows[0] if rows else None


def calls_today(user_no):
    """이 회원의 오늘(한국 날짜) 호출 수 — 모든 키 합계."""
    r = db._query("""
        SELECT COALESCE(SUM(u.CALLS), 0) AS n
        FROM   TBL_API_USAGE_DAILY u JOIN TBL_API_KEY k ON k.KEY_NO = u.KEY_NO
        WHERE  k.USER_NO = %(u)s AND u.USAGE_DATE = %(d)s
    """, {"u": user_no, "d": config.now_kst().date()})
    return int(r[0]["n"])


def _key_out(r):
    return {
        "key_no": r["key_no"],
        "name": r["name"],
        "prefix": r["key_prefix"],
        "plan": r["plan"],
        "created_at": r["created_at"].isoformat(),
        "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None,
    }


def _active_keys(user_no):
    return db._query("""
        SELECT KEY_NO, NAME, KEY_PREFIX, PLAN, CREATED_AT, LAST_USED_AT
        FROM   TBL_API_KEY
        WHERE  USER_NO = %(u)s AND REVOKED_AT IS NULL
        ORDER  BY KEY_NO
    """, {"u": user_no})


# ── API ───────────────────────────────────────────────────────────────────
class KeyIn(BaseModel):
    name: str


@router.get("")
def list_keys(user: dict = Depends(auth.require_user)):
    return {"max_keys": MAX_KEYS, "keys": [_key_out(r) for r in _active_keys(user["user_no"])]}


@router.post("", status_code=201)
def create_key(body: KeyIn, user: dict = Depends(auth.require_user)):
    """새 키를 만든다. 응답의 key 는 이번 한 번만 볼 수 있다."""
    name = body.name.strip()
    if not 1 <= len(name) <= NAME_MAX:
        raise HTTPException(400, f"키 이름은 1~{NAME_MAX}자로 적어 주세요")

    raw = new_key()
    with db._init_pool().connection() as conn, conn.cursor() as cur:
        # 같은 회원이 동시에 여러 번 눌러도 한도를 넘지 않게 회원 행을 잠그고 센다
        cur.execute("SELECT 1 FROM TBL_USER WHERE USER_NO = %(u)s FOR UPDATE", {"u": user["user_no"]})
        cur.execute("""SELECT COUNT(*) AS n FROM TBL_API_KEY
                       WHERE USER_NO = %(u)s AND REVOKED_AT IS NULL""", {"u": user["user_no"]})
        if cur.fetchone()["n"] >= MAX_KEYS:
            raise HTTPException(409, f"키는 {MAX_KEYS}개까지 만들 수 있어요. 안 쓰는 키를 지운 뒤 다시 만들어 주세요")
        cur.execute("""
            INSERT INTO TBL_API_KEY (USER_NO, NAME, KEY_PREFIX, KEY_HASH)
            VALUES (%(u)s, %(n)s, %(p)s, %(h)s)
            RETURNING KEY_NO, NAME, KEY_PREFIX, PLAN, CREATED_AT, LAST_USED_AT
        """, {"u": user["user_no"], "n": name, "p": raw[:PREFIX_LEN], "h": key_hash(raw)})
        row = cur.fetchone()
    return {**_key_out(row), "key": raw}


@router.delete("/{key_no}")
def revoke_key(key_no: int, user: dict = Depends(auth.require_user)):
    """키를 폐기한다. 바로 쓸 수 없게 된다 (되돌릴 수 없다)."""
    with db._init_pool().connection() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE TBL_API_KEY SET REVOKED_AT = now()
            WHERE  KEY_NO = %(k)s AND USER_NO = %(u)s AND REVOKED_AT IS NULL
        """, {"k": key_no, "u": user["user_no"]})
        if cur.rowcount == 0:
            raise HTTPException(404, "없는 키예요")
    return list_keys(user)


@router.get("/usage")
def usage(days: int = 30, user: dict = Depends(auth.require_user)):
    """최근 며칠의 하루별 호출 수 · 오류 · 응답 시간, 엔드포인트별 합계, 오늘 남은 한도.

    폐기한 키의 사용량도 합친다 — 오늘 한도는 회원 단위라 지운 키로 쓴 것도 센다.
    """
    days = max(1, min(days, 90))
    today = config.now_kst().date()
    since = today - timedelta(days=days - 1)
    params = {"u": user["user_no"], "since": since}

    daily = db._query("""
        SELECT u.USAGE_DATE                                             AS d,
               SUM(u.CALLS)                                             AS calls,
               SUM(CASE WHEN u.STATUS_CLASS <> '2xx' THEN u.CALLS END)  AS errors,
               SUM(u.TOTAL_MS)                                          AS total_ms,
               MAX(u.MAX_MS)                                            AS max_ms
        FROM   TBL_API_USAGE_DAILY u JOIN TBL_API_KEY k ON k.KEY_NO = u.KEY_NO
        WHERE  k.USER_NO = %(u)s AND u.USAGE_DATE >= %(since)s
        GROUP  BY u.USAGE_DATE
    """, params)
    by_day = {r["d"]: r for r in daily}
    series = []
    for i in range(days):
        d = since + timedelta(days=i)
        r = by_day.get(d)
        calls = int(r["calls"]) if r else 0
        series.append({
            "date": d.isoformat(),
            "calls": calls,
            "errors": int(r["errors"] or 0) if r else 0,
            "avg_ms": round(int(r["total_ms"]) / calls, 1) if calls else None,
            "max_ms": int(r["max_ms"]) if r else None,
        })

    endpoints = db._query("""
        SELECT u.ENDPOINT AS endpoint, SUM(u.CALLS) AS calls
        FROM   TBL_API_USAGE_DAILY u JOIN TBL_API_KEY k ON k.KEY_NO = u.KEY_NO
        WHERE  k.USER_NO = %(u)s AND u.USAGE_DATE >= %(since)s
        GROUP  BY u.ENDPOINT ORDER BY calls DESC
    """, params)

    limits = PLANS["free"]
    used = series[-1]["calls"]
    return {
        "plan": "free",
        "limits": limits,
        "today": {"date": today.isoformat(), "calls": used,
                  "remaining": max(0, limits["per_day"] - used)},
        "daily": series,
        "by_endpoint": [{"endpoint": r["endpoint"], "calls": int(r["calls"])} for r in endpoints],
    }
