"""농스닥 공개 API v1 — /api/v1/* (API 키 필요).

화면이 쓰는 /api/* 와 따로 둔다. 화면에 맞춰 응답을 바꿔도 외부 사용자의 코드가 깨지지 않게,
여기 응답 모양은 v1 이 살아 있는 동안 '필드를 더하기만' 한다 (빼거나 이름을 바꾸려면 v2).

app.py 가 이 앱을 /api/v1 에 붙인다(mount). 그래서 문서도 따로 나온다 — /api/v1/docs.

요청 하나가 지나가는 길
  1. CORS            : 다른 사이트의 브라우저에서도 부를 수 있게 (키 방식이라 쿠키는 받지 않는다)
  2. require_key     : X-API-Key 확인 → 분당 · 하루 한도 확인 → 남은 횟수를 응답 헤더에
  3. 엔드포인트       : DB 조회 → {"data": ..., "meta": ...}
  4. record_usage    : (날짜 · 키 · 엔드포인트 · 상태) 합계에 1 을 더한다

호출 제한을 어디에 두나
  · 분당  : 이 프로세스의 메모리. 서버 한 대 · uvicorn 프로세스 하나라 충분하고, 재시작으로 지워져도
            길어야 1분치라 문제없다. 서버나 프로세스를 늘리면 공유 저장소(Redis 등)로 옮겨야 한다.
  · 하루  : 처음 보는 (회원, 날짜) 는 DB(TBL_API_USAGE_DAILY)에서 읽어 시작하고 그 뒤로 메모리에서 센다.
            재시작해도 DB 에서 다시 읽으니 한도가 초기화되지 않는다.
  · 둘 다 키가 아니라 '회원' 단위다. 키 3개를 만들어 한도를 3배로 늘리지 못하게.
"""

import threading
import time
from datetime import date, timedelta
from typing import Literal

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

import apikeys
import forecast as fc
import config
import db

API_VERSION = "v1"
SOURCE = "KAMIS 농산물유통정보 (한국농수산식품유통공사)"
MAX_HISTORY_DAYS = 366
LATEST_WINDOW_DAYS = 30      # prices/latest 는 최근 이만큼 안에 조사된 품종만
ITEMS_TTL = 600              # 초. 전체 기간(10년)을 묶는 무거운 조회라 10분 캐시한다 — 자료는 하루 한 번 바뀐다

Market = Literal["retail", "wholesale"]
MARKET_Q = Query("retail", description="retail=소매 · wholesale=도매")
PERIODS = {"1d": 1, "1w": 7, "2w": 14, "1m": 30}

DESCRIPTION = f"""
농산물 · 축수산물 **소매 · 도매 가격**을 날마다 모아 제공합니다.

* 출처: {SOURCE}
* 갱신: 매일 17:30 (한국 시각) — KAMIS 가 17:00 에 공표한 값을 받습니다
* 인증: 모든 요청에 `X-API-Key` 헤더 (`/status` 제외). 키는 [개발자 페이지](/developers)에서 발급합니다
* 한도: 회원당 분당 {apikeys.PLANS['free']['per_minute']}회 · 하루 {apikeys.PLANS['free']['per_day']:,}회 (한국 날짜 기준).
  남은 횟수는 응답 헤더 `X-RateLimit-*` 로 알려 드립니다

모든 응답은 `{{"data": ..., "meta": ...}}`, 오류는 `{{"error": {{"code", "message"}}}}` 모양입니다.
"""

v1 = FastAPI(
    title="농스닥 API",
    version=f"{API_VERSION} · {config.APP_VERSION}",
    description=DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

v1.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,           # 쿠키는 받지 않는다 — 인증은 키로만
    allow_methods=["GET"],
    allow_headers=["X-API-Key"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset",
                    "X-RateLimit-Daily-Limit", "X-RateLimit-Daily-Remaining", "Retry-After"],
)


# ── 오류 ──────────────────────────────────────────────────────────────────
class ApiError(Exception):
    def __init__(self, status, code, message, headers=None):
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


def _error(status, code, message, headers=None):
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)


@v1.exception_handler(ApiError)
async def _api_error(request, e: ApiError):
    return _error(e.status, e.code, e.message, e.headers)


@v1.exception_handler(RequestValidationError)
async def _invalid(request, e: RequestValidationError):
    parts = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err.get("loc", []) if x not in ("query", "header"))
        parts.append(f"{loc}: {err.get('msg')}")
    return _error(422, "invalid_parameter", " / ".join(parts) or "요청 값이 올바르지 않아요")


@v1.exception_handler(StarletteHTTPException)
async def _http_error(request, e: StarletteHTTPException):
    code = {404: "not_found", 405: "method_not_allowed"}.get(e.status_code, "error")
    return _error(e.status_code, code, str(e.detail))


@v1.exception_handler(Exception)
async def _server_error(request, e: Exception):
    print(f"[api_v1] {request.url.path} 처리 중 오류: {type(e).__name__}: {e}")
    return _error(500, "internal_error", "서버에서 오류가 났어요. 잠시 뒤 다시 시도해 주세요")


# ── 호출 제한 ─────────────────────────────────────────────────────────────
class RateLimiter:
    """회원별 분당 · 하루 호출 수. 고정 창(fixed window) 방식.

    엔드포인트가 스레드풀에서 동시에 돌기 때문에 자물쇠 하나로 지킨다.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._minute = {}     # user_no -> (분 번호, 횟수)
        self._day = {}        # user_no -> (날짜, 횟수)

    def reset(self):
        with self._lock:
            self._minute.clear()
            self._day.clear()

    def hit(self, user_no, plan, seed_today):
        """한 번 쓴다. 한도를 넘으면 ApiError(429). 넘지 않으면 응답 헤더에 넣을 값을 돌려준다.

        seed_today: 이 회원의 오늘 사용량을 DB 에서 읽는 함수. 처음 볼 때만 부른다.
        """
        limits = apikeys.PLANS.get(plan, apikeys.PLANS["free"])
        now = time.time()
        minute = int(now // 60)
        reset_in = 60 - int(now % 60)
        today = config.now_kst().date()

        with self._lock:
            d = self._day.get(user_no)
            need_seed = d is None or d[0] != today
        if need_seed:
            seeded = seed_today()                      # DB 조회는 자물쇠 밖에서
            with self._lock:
                d = self._day.get(user_no)
                if d is None or d[0] != today:
                    self._day[user_no] = (today, seeded)

        with self._lock:
            m_no, m_cnt = self._minute.get(user_no, (minute, 0))
            if m_no != minute:
                m_no, m_cnt = minute, 0
            _, d_cnt = self._day[user_no]

            if d_cnt >= limits["per_day"]:
                raise ApiError(429, "daily_quota_exceeded",
                               f"하루 호출 한도({limits['per_day']:,}회)를 다 썼어요. 한국 시각 자정에 초기화돼요",
                               {"Retry-After": str(_seconds_to_kst_midnight())})
            if m_cnt >= limits["per_minute"]:
                raise ApiError(429, "rate_limited",
                               f"분당 호출 한도({limits['per_minute']}회)를 넘었어요. {reset_in}초 뒤에 다시 시도해 주세요",
                               {"Retry-After": str(reset_in)})

            self._minute[user_no] = (m_no, m_cnt + 1)
            self._day[user_no] = (today, d_cnt + 1)
            return {
                "X-RateLimit-Limit": str(limits["per_minute"]),
                "X-RateLimit-Remaining": str(limits["per_minute"] - m_cnt - 1),
                "X-RateLimit-Reset": str(reset_in),
                "X-RateLimit-Daily-Limit": str(limits["per_day"]),
                "X-RateLimit-Daily-Remaining": str(limits["per_day"] - d_cnt - 1),
            }


def _seconds_to_kst_midnight():
    now = config.now_kst()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))


limiter = RateLimiter()


def require_key(request: Request, response: Response):
    """X-API-Key 를 확인하고 호출 제한을 건다. 엔드포인트에 Depends 로 붙인다."""
    raw = request.headers.get("X-API-Key")
    if not raw:
        raise ApiError(401, "missing_api_key", "X-API-Key 헤더에 API 키를 넣어 주세요 (발급: /developers)")
    key = apikeys.find_active_key(raw.strip())
    if key is None:
        raise ApiError(401, "invalid_api_key", "API 키가 올바르지 않거나 폐기됐어요")

    # 한도에 걸린 요청(429)도 사용량에 4xx 로 남도록 키를 먼저 적어 둔다.
    # 그래서 재시작 직후 DB 에서 읽는 '오늘 사용량' 에는 거절된 호출도 들어가 조금 엄하게 센다.
    request.state.key_no = key["key_no"]
    headers = limiter.hit(key["user_no"], key["plan"], lambda: apikeys.calls_today(key["user_no"]))
    response.headers.update(headers)
    return key


# ── 사용량 기록 ───────────────────────────────────────────────────────────
def _record(key_no, endpoint, status, ms):
    status_class = f"{min(max(status // 100, 2), 5)}xx"
    with db._init_pool().connection() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO TBL_API_USAGE_DAILY (USAGE_DATE, KEY_NO, ENDPOINT, STATUS_CLASS, CALLS, TOTAL_MS, MAX_MS)
            VALUES (%(d)s, %(k)s, %(e)s, %(s)s, 1, %(ms)s, %(ms)s)
            ON CONFLICT (USAGE_DATE, KEY_NO, ENDPOINT, STATUS_CLASS) DO UPDATE
               SET CALLS    = TBL_API_USAGE_DAILY.CALLS + 1,
                   TOTAL_MS = TBL_API_USAGE_DAILY.TOTAL_MS + EXCLUDED.TOTAL_MS,
                   MAX_MS   = GREATEST(TBL_API_USAGE_DAILY.MAX_MS, EXCLUDED.MAX_MS)
        """, {"d": config.now_kst().date(), "k": key_no, "e": endpoint[:60], "s": status_class, "ms": ms})
        # 마지막 사용 시각은 1분에 한 번만 고친다 (매 요청마다 같은 행을 쓰지 않게)
        cur.execute("""
            UPDATE TBL_API_KEY SET LAST_USED_AT = now()
            WHERE  KEY_NO = %(k)s AND (LAST_USED_AT IS NULL OR LAST_USED_AT < now() - INTERVAL '1 minute')
        """, {"k": key_no})


@v1.middleware("http")
async def record_usage(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        await _record_safely(request, 500, start)      # 처리 중 예외도 5xx 로 남긴다
        raise
    await _record_safely(request, response.status_code, start)
    return response


async def _record_safely(request, status, start):
    key_no = getattr(request.state, "key_no", None)
    if key_no is None:                                 # 키 없는 요청 (/status · 401) 은 남기지 않는다
        return
    ms = int((time.perf_counter() - start) * 1000)
    route = request.scope.get("route")
    endpoint = getattr(route, "path", None) or "unknown"
    try:
        await run_in_threadpool(_record, key_no, endpoint, status, ms)
    except Exception as e:                             # 기록이 실패해도 응답은 그대로 보낸다
        print(f"[api_v1] 사용량 기록 실패: {type(e).__name__}: {e}")


# ── 응답 모양 ─────────────────────────────────────────────────────────────
def _num(v):
    return float(v) if v is not None else None


def _iso(v):
    return v.isoformat() if v is not None else None


def _envelope(data, market=None, **meta):
    m = {"api_version": API_VERSION, "source": SOURCE}
    if market is not None:
        m["market"] = market
    if isinstance(data, list):
        m["count"] = len(data)
    m.update(meta)
    return {"data": data, "meta": m}


# ── 엔드포인트 ────────────────────────────────────────────────────────────
@v1.get("/status", summary="데이터 상태 (키 필요 없음)")
def status():
    """시장별 데이터 기간 · 품목 수 · 마지막 수집 시각. 키 없이 부를 수 있다."""
    out = {}
    for name, mkt in db.MARKETS.items():
        m = db.get_meta(mkt)
        fetch = m.get("updated_at") or {}
        out[name] = {
            "earliest_date": m["earliest"],
            "latest_date": m["latest_full"] or m["latest"],
            "items": m["items"],
            "rows": m["rows"],
            "last_fetched_at": fetch.get("at"),
        }
    return _envelope(out, service_version=config.APP_VERSION)


_items_cache = {}


def _items(market):
    hit = _items_cache.get(market)
    if hit and time.time() - hit["at"] < ITEMS_TTL:
        return hit["data"]
    rows = db._query("""
        SELECT ITEM_CODE, KIND_CODE, RANK_NAME,
               (ARRAY_AGG(ITEM_NAME     ORDER BY SURVEY_DATE DESC))[1] AS item_name,
               (ARRAY_AGG(KIND_NAME     ORDER BY SURVEY_DATE DESC))[1] AS kind_name,
               (ARRAY_AGG(UNIT          ORDER BY SURVEY_DATE DESC))[1] AS unit,
               (ARRAY_AGG(CATEGORY_CODE ORDER BY SURVEY_DATE DESC))[1] AS category_code,
               (ARRAY_AGG(CATEGORY_NAME ORDER BY SURVEY_DATE DESC))[1] AS category_name,
               MIN(SURVEY_DATE) AS first_date, MAX(SURVEY_DATE) AS last_date
        FROM   TBL_DAILY_PRICE
        WHERE  MARKET_TYPE = %(m)s AND PRICE_TODAY > 0
        GROUP  BY ITEM_CODE, KIND_CODE, RANK_NAME
    """, {"m": market})
    items = {}
    for r in sorted(rows, key=lambda r: (r["item_code"], r["kind_code"], db.rank_key(r["rank_name"]))):
        it = items.setdefault(r["item_code"], {
            "item_code": r["item_code"], "item_name": r["item_name"],
            "category_code": r["category_code"], "category_name": r["category_name"],
            "kinds": {},
        })
        kd = it["kinds"].setdefault(r["kind_code"], {
            "kind_code": r["kind_code"], "kind_name": r["kind_name"], "unit": r["unit"], "ranks": [],
        })
        kd["ranks"].append({"rank": r["rank_name"], "first_date": _iso(r["first_date"]),
                            "last_date": _iso(r["last_date"])})
    data = [{**it, "kinds": list(it["kinds"].values())} for it in items.values()]
    _items_cache[market] = {"at": time.time(), "data": data}
    return data


@v1.get("/items", summary="품목 · 품종 · 등급 코드")
def items(
    market: Market = MARKET_Q,
    category: str | None = Query(None, description="부류코드 (100 식량작물 · 200 채소류 · 300 특용작물 · "
                                                   "400 과실류 · 500 축산물 · 600 수산물)"),
    key: dict = Depends(require_key),
):
    """다른 엔드포인트에 넣을 코드 목록. 등급마다 처음 · 마지막 조사일을 함께 준다."""
    data = _items(db.MARKETS[market])
    if category:
        data = [i for i in data if i["category_code"] == category]
    return _envelope(data, market)


def _price_row(r):
    return {
        "survey_date": _iso(r["survey_date"]),
        "item_code": r["item_code"], "item_name": r["item_name"],
        "kind_code": r["kind_code"], "kind_name": r["kind_name"],
        "rank": r["rank_name"], "unit": r["unit"],
        "category_code": r["category_code"],
        "price": _num(r["price_today"]),
        "price_1y_ago": _num(r["price_1y"]),
        "price_normal": _num(r["price_normal"]),
    }


@v1.get("/prices/latest", summary="최신 가격")
def prices_latest(
    market: Market = MARKET_Q,
    item: str | None = Query(None, description="품목코드 (생략하면 전체)"),
    kind: str | None = Query(None, description="품종코드 (item 과 함께)"),
    rank: str | None = Query(None, description="등급 (예: 상품)"),
    category: str | None = Query(None, description="부류코드"),
    key: dict = Depends(require_key),
):
    """품종 · 등급마다 가장 최근 조사일의 가격. 최근 30일 안에 조사된 것만 준다
    (철이 지나 조사가 끊긴 품종이 '오늘 가격' 처럼 보이지 않게). 날짜는 항목마다 survey_date 로 확인한다."""
    mkt = db.MARKETS[market]
    rows = db._query("""
        SELECT DISTINCT ON (ITEM_CODE, KIND_CODE, RANK_NAME)
               SURVEY_DATE, ITEM_CODE, ITEM_NAME, KIND_CODE, KIND_NAME, RANK_NAME, UNIT,
               CATEGORY_CODE, PRICE_TODAY, PRICE_1Y, PRICE_NORMAL
        FROM   TBL_DAILY_PRICE
        WHERE  MARKET_TYPE = %(m)s AND PRICE_TODAY > 0
          AND  SURVEY_DATE >= (SELECT MAX(SURVEY_DATE) FROM TBL_DAILY_PRICE WHERE MARKET_TYPE = %(m)s)
                              - %(win)s
          AND  (%(item)s::text IS NULL OR ITEM_CODE = %(item)s)
          AND  (%(kind)s::text IS NULL OR KIND_CODE = %(kind)s)
          AND  (%(rank)s::text IS NULL OR RANK_NAME = %(rank)s)
          AND  (%(cat)s::text  IS NULL OR CATEGORY_CODE = %(cat)s)
        ORDER  BY ITEM_CODE, KIND_CODE, RANK_NAME, SURVEY_DATE DESC
    """, {"m": mkt, "win": LATEST_WINDOW_DAYS, "item": item, "kind": kind, "rank": rank, "cat": category})
    if item and not rows:
        raise ApiError(404, "not_found", f"최근 {LATEST_WINDOW_DAYS}일 안에 조사된 가격이 없어요: {item}")
    data = [_price_row(r) for r in rows]
    latest = max((d["survey_date"] for d in data), default=None)
    return _envelope(data, market, latest_survey_date=latest)


@v1.get("/prices/history", summary="기간별 가격")
def prices_history(
    item: str = Query(..., description="품목코드"),
    kind: str = Query(..., description="품종코드"),
    rank: str | None = Query(None, description="등급 (생략하면 모든 등급)"),
    start: date | None = Query(None, description="시작일 YYYY-MM-DD (생략하면 end 90일 전)"),
    end: date | None = Query(None, description="종료일 YYYY-MM-DD (생략하면 최신 조사일)"),
    market: Market = MARKET_Q,
    key: dict = Depends(require_key),
):
    """한 품종의 일별 가격. 조사가 없는 날(주말 · 공휴일 등)은 빠진다. 한 번에 최대 366일."""
    mkt = db.MARKETS[market]
    if end is None:
        r = db._query("SELECT MAX(SURVEY_DATE) AS d FROM TBL_DAILY_PRICE WHERE MARKET_TYPE = %(m)s", {"m": mkt})
        end = r[0]["d"] or config.now_kst().date()
    if start is None:
        start = end - timedelta(days=90)
    if start > end:
        raise ApiError(422, "invalid_parameter", "start 가 end 보다 늦어요")
    if (end - start).days + 1 > MAX_HISTORY_DAYS:
        raise ApiError(422, "invalid_parameter", f"기간은 한 번에 {MAX_HISTORY_DAYS}일까지예요")

    rows = db._query("""
        SELECT SURVEY_DATE, ITEM_CODE, ITEM_NAME, KIND_CODE, KIND_NAME, RANK_NAME, UNIT,
               CATEGORY_CODE, PRICE_TODAY, PRICE_1Y, PRICE_NORMAL
        FROM   TBL_DAILY_PRICE
        WHERE  MARKET_TYPE = %(m)s AND ITEM_CODE = %(item)s AND KIND_CODE = %(kind)s
          AND  (%(rank)s::text IS NULL OR RANK_NAME = %(rank)s)
          AND  SURVEY_DATE BETWEEN %(s)s AND %(e)s
          AND  PRICE_TODAY > 0
        ORDER  BY RANK_NAME, SURVEY_DATE
    """, {"m": mkt, "item": item, "kind": kind, "rank": rank, "s": start, "e": end})
    if not rows:
        raise ApiError(404, "not_found", f"그 기간에 가격 자료가 없어요: {item}/{kind}")
    data = [_price_row(r) for r in rows]
    return _envelope(data, market, start=start.isoformat(), end=end.isoformat())


@v1.get("/changes", summary="가격 등락")
def changes(
    period: Literal["1d", "1w", "2w", "1m"] = Query("1d", description="비교 기준 — 1d 직전 조사일 · "
                                                                       "1w 1주 · 2w 2주 · 1m 1개월 전"),
    market: Market = MARKET_Q,
    key: dict = Depends(require_key),
):
    """품목마다 대표 등급 하나의 '지금 vs 기준 시점' 등락률. 많이 오른 순.

    기준 시점은 그 날짜에 가장 가까운 조사일이라 품목마다 조금씩 다를 수 있다 (prev_date 로 확인).
    최근 3일 안에 조사되지 않은 품종은 빠진다.
    """
    picked = db._compare_all(offset=PERIODS[period], market=db.MARKETS[market])
    data = [{
        "item_code": c["item_code"], "item_name": c["item_name"],
        "kind_code": c["kind_code"], "kind_name": c["kind_name"],
        "rank": c["rank_name"], "unit": c["unit"],
        "survey_date": c["date"], "price": c["price"],
        "prev_date": c["prev_date"], "prev_price": c["prev_price"],
        "change_pct": c["change_pct"],
    } for c in sorted(picked, key=lambda c: -c["change_pct"])]
    return _envelope(data, market, period=period)


@v1.get("/forecast", summary="가격 예측 (1 · 2 · 4주 뒤)")
def forecast(
    item: str = Query(..., description="품목코드"),
    kind: str = Query(..., description="품종코드"),
    rank: str | None = Query(None, description="등급 (생략하면 대표 등급)"),
    market: Market = MARKET_Q,
    key: dict = Depends(require_key),
):
    """한 품종 · 등급의 가장 최근 예측. 기준일(base_date)은 그 품종의 마지막 조사일이다.

    예측은 매일 17:30 가격 수집 뒤에 새로 만든다. meta.model · model_version 은 어떤 모델이 예측했는지다
    (모델이 바뀌어도 응답 모양은 그대로). 예측이 없는 품종(철 지남 · 자료 부족)은 data 가 빈 목록이다.
    """
    try:
        f = fc.get_forecast(item, kind, rank, market)
    except fc.HTTPException as e:
        raise ApiError(e.status_code, "not_found", str(e.detail)) from None
    return _envelope(f["points"], market, item_code=f["item_code"], kind_code=f["kind_code"], rank=f["rank"],
                     unit=f["unit"], base_date=f["base_date"], base_price=f["base_price"],
                     model=f["model"], model_version=f.get("model_version"))
