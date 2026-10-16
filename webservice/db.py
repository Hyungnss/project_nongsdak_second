"""Oracle TBL_DAILY_PRICE 조회 계층.

웹서비스가 쓰는 모든 SQL 을 여기 모은다. app.py 는 이 함수들만 호출한다.

설계 메모
  · 비교 시점(어제·1주일전·1개월전)을 저장된 PRICE_1D/1W/1M 컬럼으로 계산하지 않는다.
    주말·공휴일 뒤에는 그 컬럼이 비기 때문이다 (2026-08-10 은 1일전가격이 29건뿐).
    대신 그 품종의 조사 이력에서 '가장 가까운 조사일'을 찾아 쓰고,
    실제 날짜와 며칠 차이인지를 함께 돌려준다.
  · PRICE_1Y / PRICE_NORMAL 은 250일치 데이터로 복원할 수 없으므로 저장된 값을 그대로 쓴다.
  · 등급은 자동으로 대표 등급 하나만 고른다 (상품/중품 -> 상품, 大/中/小 -> 大).
  · 소매·도매는 한 테이블에 MARKET_TYPE 으로 나뉘어 있다 (2026-10-15~). 모든 조회는
    **한 시장 안에서만** 한다 — 같은 품종·등급이 양쪽에 있어서, 조건 하나만 빠져도
    '1포기' 소매가와 '10kg' 도매가가 한 차트·한 순위에 섞인다.
    그래서 공개 함수는 전부 market 을 받고, 기본값은 지금까지와 같은 소매다.
"""

import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import oracledb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

# 접속 정보는 config.py 한 곳에서만 관리한다 (환경변수 -> .env -> 기본값).
USER, PASSWORD = config.DB_USER, config.DB_PASSWORD
DSN = config.DB_DSN
CLIENT_LIB_DIR = config.CLIENT_LIB_DIR

# 등급 우선순위. 앞에 있을수록 대표 등급으로 뽑힌다.
# 상하 관계가 있는 것만 순서가 의미 있고, 부위·원산지처럼 병렬인 값은
# 어차피 품종당 하나뿐이라 순서와 무관하다.
RANK_PRIORITY = [
    "1++등급", "1+등급", "1등급",        # 축산 등급
    "大", "中", "小",                     # 수산 크기
    "L과", "M과", "S과",                  # 과일 크기
    "대멸", "중멸", "세멸",               # 멸치 크기
    "상품", "중품",                       # 일반 등급
    "없음",
    "미국산", "호주산",                   # 원산지 (상하 관계 없음)
    "삼겹살", "목심", "갈비", "앞다리",   # 부위
    "육계(kg)", "절단육", "일반란", "흰우유",
]
_RANK_ORDER = {r: i for i, r in enumerate(RANK_PRIORITY)}

# 상세 화면에서 보여줄 비교 시점 (라벨, 목표 간격일)
COMPARE_POINTS = [("어제", 1), ("1주일 전", 7), ("2주일 전", 14), ("1개월 전", 30)]

# 목표 간격에서 이만큼 벗어나면 '가까운 조사일'로 인정하지 않는다.
#
# TOLERANCE[1] 이 11 인 이유 — 긴 연휴 다음 첫 조사일.
#   '어제'(offset=1)는 직전 조사일과의 간격이 이 값을 넘으면 _compare_all 이 그 품목을
#   통째로 버린다. 6 이던 때는 6일 연휴(조사일 간격 7일) 다음 첫 조사일에 급등락·등락 요약·
#   티커·포춘쿠키가 전부 0개가 됐다 (시뮬레이션으로 확인. 품목별 상세는 정상이었다).
#   11 이면 10일 연휴(간격 11일)까지 견딘다.
#   철 지난 품종이 섞일 걱정은 없다 — 그건 _compare_all 의 max_stale(3일)이 따로 거른다.
TOLERANCE = {1: 11, 7: 4, 14: 5, 30: 8}

# 최근 90일에 이만큼은 조사돼 있어야 '지금 쓰이는 품종·등급'으로 본다 (90일에 조사일 약 62일).
# list_products 와 _resolve_rank 가 같은 값을 써야 목록과 상세가 같은 등급을 가리킨다.
MIN_RECENT = 20

# API 의 market 값 -> TBL_DAILY_PRICE.MARKET_TYPE
MARKETS = {"retail": "소매", "wholesale": "도매"}
RETAIL = "소매"

_pool = None


def _init_pool():
    """커넥션 풀을 만든다.

    create_pool 은 실제 접속을 미루기 때문에, 여기서 먼저 단일 연결을 시도해
    thin/thick 모드를 판별한다. 풀을 먼저 만들면 DPY-3010 이 acquire 시점에
    터져서 폴백이 걸리지 않는다.
    """
    global _pool
    if _pool is not None:
        return _pool
    try:
        oracledb.connect(user=USER, password=PASSWORD, **DSN).close()
    except oracledb.Error as e:
        if "DPY-3010" not in str(e):
            raise
        # 이 DB 버전은 thin 모드를 지원하지 않는다 (Oracle 12.1 미만)
        oracledb.init_oracle_client(lib_dir=CLIENT_LIB_DIR)
    _pool = oracledb.create_pool(user=USER, password=PASSWORD, min=1, max=4,
                                 increment=1, **DSN)
    return _pool


def _query(sql, params=None):
    """SELECT 을 실행해 dict 목록으로 돌려준다."""
    with _init_pool().acquire() as conn, conn.cursor() as cur:
        cur.execute(sql, params or {})
        cols = [d[0].lower() for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def rank_key(rank):
    """등급 정렬 키. 목록에 없는 값은 뒤로 보낸다."""
    return _RANK_ORDER.get(rank, len(RANK_PRIORITY))


# ── 메타 ────────────────────────────────────────────────────────────────
# 마지막 수집이 이만큼 지났으면 화면에 경고를 띄운다.
# 수집은 하루 세 번이라 24시간을 넘겼다면 스케줄러가 죽은 것이다.
STALE_FETCH_HOURS = 24


def _last_fetch(market=RETAIL):
    """그 시장의 마지막 수집 성공 시각과 상태. TBL_FETCH_LOG 가 없으면 None.

    수집 로그는 자동화를 붙인 뒤에 생긴 테이블이라, 아직 07 을 실행하지 않은
    환경에서도 화면은 떠야 한다. 그래서 없으면 조용히 None 을 돌려준다.
    MARKET_TYPE 이 없던 시절의 기록은 전부 소매라 NVL 로 소매로 읽는다.
    """
    try:
        rows = _query("""
            SELECT * FROM (
                SELECT FETCHED_AT, SURVEY_DATE, STATUS, ROWS_UPSERTED
                FROM   TBL_FETCH_LOG
                WHERE  CATEGORY_CODE IS NULL AND STATUS IN ('OK', 'NO_DATA')
                  AND  NVL(MARKET_TYPE, '소매') = :m
                ORDER  BY LOG_NO DESC
            ) WHERE ROWNUM = 1
        """, {"m": market})
        # FETCH FIRST ... ROWS ONLY 는 12c 문법이라 이 DB(11g)에서 못 쓴다. ROWNUM 을 쓴다.
    except oracledb.DatabaseError:
        return None
    if not rows:
        return None

    r = rows[0]
    at = r["fetched_at"]
    age_h = (datetime.now() - at).total_seconds() / 3600
    return {
        "at": at.isoformat(timespec="seconds"),
        "survey_date": r["survey_date"].date().isoformat(),
        "status": r["status"],
        "age_minutes": int(age_h * 60),
        "stale": age_h > STALE_FETCH_HOURS,
    }


# '온전한 조사일'로 인정할 최소 비율. 최근 최대 조사량의 이만큼은 돼야 한다.
FULL_DAY_RATIO = 0.5


def _latest_full_day(market=RETAIL):
    """대부분의 품목에 값이 있는 최신 조사일.

    MAX(SURVEY_DATE) 를 그대로 쓰면 화면이 거짓말을 한다. 두 경우 때문이다.
      · 공표(17:00) 전에 수집한 날 — 축산물만 값이 있다. 2026-09-01 은 184행 중 29행뿐이었다.
      · 주말 — 축산물 29행만 온다.
    둘 다 '그 날짜로 조사가 있었다'고 말하기 어려운데, 정작 화면의 대부분 품목은
    그 전 조사일 값을 보여준다. 그래서 헤더에 적을 날짜는 따로 구한다.

    비율로 재는 이유는 절대 건수로 자르면 품목이 늘거나 줄 때 같이 흔들리기 때문이다.
    축산물만 오는 날(29건)은 최근 최대(약 179건)의 16% 라 어느 쪽으로도 걸러진다.
    """
    rows = _query("""
        SELECT SURVEY_DATE, COUNT(PRICE_TODAY) AS priced
        FROM   TBL_DAILY_PRICE
        WHERE  MARKET_TYPE = :m
          AND  SURVEY_DATE >= (SELECT MAX(SURVEY_DATE) - 60 FROM TBL_DAILY_PRICE
                               WHERE MARKET_TYPE = :m)
        GROUP  BY SURVEY_DATE
        ORDER  BY SURVEY_DATE DESC
    """, {"m": market})
    if not rows:
        return None
    peak = max(int(r["priced"]) for r in rows)
    if peak == 0:
        return None
    for r in rows:                      # 최신 날짜부터 훑는다
        if int(r["priced"]) >= peak * FULL_DAY_RATIO:
            return r["survey_date"].date()
    return None


def get_meta(market=RETAIL):
    r = _query("""
        SELECT MAX(SURVEY_DATE) AS latest,
               MIN(SURVEY_DATE) AS earliest,
               COUNT(*) AS rows_total,
               COUNT(DISTINCT ITEM_CODE) AS items
        FROM   TBL_DAILY_PRICE
        WHERE  MARKET_TYPE = :m
    """, {"m": market})[0]
    latest_priced = _query("""
        SELECT MAX(SURVEY_DATE) AS d FROM TBL_DAILY_PRICE
        WHERE  PRICE_TODAY IS NOT NULL AND MARKET_TYPE = :m
    """, {"m": market})[0]["d"]
    latest_full = _latest_full_day(market)
    return {
        "market": market,
        "latest": r["latest"].date().isoformat() if r["latest"] else None,
        "latest_priced": latest_priced.date().isoformat() if latest_priced else None,
        # 헤더에 적고, 상세가 얼마나 묵었는지 재는 기준. latest 와 다를 수 있다.
        "latest_full": latest_full.isoformat() if latest_full else None,
        "earliest": r["earliest"].date().isoformat() if r["earliest"] else None,
        "rows": int(r["rows_total"]),
        "items": int(r["items"]),
        # 자동 수집 상태. 아직 수집기를 안 붙였으면 None 이다.
        "updated_at": _last_fetch(market),
    }


# ── 품목 · 품종 목록 ────────────────────────────────────────────────────
# 요청마다 테이블 전체를 GROUP BY 하는 무거운 조회라 짧게 캐시한다.
# 수집은 하루 세 번뿐이라 이보다 짧게 잡을 이유가 없다.
PRODUCTS_TTL = 60          # 초
_products_cache = {}      # market -> {"at": 시각, "data": 목록}


def list_products(market=RETAIL):
    """품목 -> 품종 목록. 시장마다 60초 캐시를 앞에 둔다."""
    now = time.time()
    hit = _products_cache.get(market)
    if hit and now - hit["at"] < PRODUCTS_TTL:
        return hit["data"]
    out = _list_products_uncached(market)
    _products_cache[market] = {"at": now, "data": out}
    return out


def _list_products_uncached(market=RETAIL):
    """품목 -> 품종 계층. 품종마다 대표 등급 하나를 자동으로 고른다.

    기본 품종은 '가장 최근에 조사된 것'으로 잡는다.
    배추·무처럼 계절마다 품종이 바뀌는 품목이 있어서, 이름순으로 고르면
    철 지난 품종(예: 배추 '가을' 은 2025-12 이후 조사 없음)이 기본이 되어
    8개월 전 가격을 '오늘 시세'처럼 보여주게 된다.

    대표 등급 선별은 `_resolve_rank` 와 같은 규칙을 쓴다 (MIN_RECENT).
    한쪽만 고치면 목록에 적힌 등급과 상세가 보여주는 값이 어긋난다.
    """
    rows = _query("""
        SELECT ITEM_CODE, ITEM_NAME, KIND_CODE, KIND_NAME,
               RANK_NAME, UNIT, CATEGORY_NAME,
               MAX(SURVEY_DATE) AS latest,
               COUNT(*) AS obs_total,
               SUM(CASE WHEN SURVEY_DATE >=
                             (SELECT MAX(SURVEY_DATE) - 90 FROM TBL_DAILY_PRICE
                              WHERE MARKET_TYPE = :m)
                        THEN 1 ELSE 0 END) AS obs_recent
        FROM   TBL_DAILY_PRICE
        WHERE  PRICE_TODAY IS NOT NULL AND MARKET_TYPE = :m
        GROUP BY ITEM_CODE, ITEM_NAME, KIND_CODE, KIND_NAME,
                 RANK_NAME, UNIT, CATEGORY_NAME
    """, {"m": market})
    if not rows:
        return []
    global_latest = max(r["latest"] for r in rows).date()

    kinds = {}
    for r in rows:
        key = (r["item_code"], r["kind_code"])
        cur = kinds.get(key)
        # 등급 우선순위(상품·大)를 따르되, 최근 자료가 너무 적은 등급은 뒤로 보낸다.
        # 물오징어 大 는 8/14 에 한 번 조사됐을 뿐 최근 90일에 1건뿐이라
        # 그대로 고르면 차트가 안 그려진다.
        def score(x):
            return (0 if int(x["obs_recent"]) >= MIN_RECENT else 1,
                    rank_key(x["rank_name"]))
        if cur is None or score(r) < score(cur):
            kinds[key] = r

    items = {}
    for (item_code, kind_code), r in kinds.items():
        it = items.setdefault(item_code, {
            "item_code": item_code, "item_name": r["item_name"],
            "category": r["category_name"], "kinds": [],
        })
        latest = r["latest"].date()
        it["kinds"].append({
            "kind_code": kind_code,
            "kind_name": r["kind_name"],
            "rank_name": r["rank_name"],
            "unit": r["unit"],
            "latest": latest.isoformat(),
            "days_stale": (global_latest - latest).days,
            "obs_recent": int(r["obs_recent"]),
        })

    out = []
    for it in items.values():
        # 최근 조사된 것 우선 → 자료가 많은 것 → 이름순.
        # 건고추 '햇산화건' 처럼 8/14 에 한 번만 조사된 품종이 기본이 되면
        # 추이 차트를 못 그리므로 관측 수를 함께 본다.
        it["kinds"].sort(key=lambda k: (k["days_stale"], -k["obs_recent"], k["kind_name"]))
        it["default_kind"] = it["kinds"][0]["kind_code"]
        it["days_stale"] = it["kinds"][0]["days_stale"]
        out.append(it)
    return sorted(out, key=lambda i: i["item_name"])


def _series(item_code, kind_code, rank_name, limit=400, market=RETAIL):
    """한 품종의 가격 이력 (최근 것부터). 가격이 없는 날은 제외한다."""
    # FETCH FIRST 는 Oracle 12c 이상 문법이다. 이 DB 는 그보다 낮으므로 ROWNUM 을 쓴다.
    return _query("""
        SELECT * FROM (
            SELECT SURVEY_DATE, PRICE_TODAY, PRICE_1Y, PRICE_NORMAL,
                   ITEM_NAME, KIND_NAME, RANK_NAME, UNIT, CATEGORY_NAME
            FROM   TBL_DAILY_PRICE
            WHERE  MARKET_TYPE = :m
              AND  ITEM_CODE = :item AND KIND_CODE = :kind AND RANK_NAME = :rank
              AND  PRICE_TODAY IS NOT NULL
            ORDER BY SURVEY_DATE DESC
        ) WHERE ROWNUM <= :lim
    """, {"m": market, "item": item_code, "kind": kind_code, "rank": rank_name,
          "lim": limit})


def _nearest(rows, target_date, tolerance):
    """target_date 에 가장 가까운 조사일 행을 찾는다. 허용 오차를 넘으면 None."""
    best, best_gap = None, None
    for r in rows:
        gap = abs((r["survey_date"].date() - target_date).days)
        if best_gap is None or gap < best_gap:
            best, best_gap = r, gap
    if best is None or best_gap > tolerance:
        return None
    return best


def _resolve_rank(item_code, kind_code, rank_name=None, market=RETAIL):
    """등급을 지정하지 않았을 때 쓸 대표 등급을 고른다.

    등급 우선순위(상품·大)만 보면 안 된다. 오렌지 '네이블 호주'의 상품 등급은
    2025-11-25 이후 조사가 없어서, 그대로 고르면 9개월 전 가격을 오늘 시세로 보여준다.
    list_products 와 **같은 규칙**을 써야 목록에 적힌 등급과 상세가 보여주는 값이 어긋나지 않는다.
    """
    if rank_name:
        return rank_name
    rows = _query("""
        SELECT RANK_NAME,
               SUM(CASE WHEN SURVEY_DATE >=
                             (SELECT MAX(SURVEY_DATE) - 90 FROM TBL_DAILY_PRICE
                              WHERE MARKET_TYPE = :m)
                        THEN 1 ELSE 0 END) AS obs_recent
        FROM   TBL_DAILY_PRICE
        WHERE  MARKET_TYPE = :m
          AND  ITEM_CODE = :item AND KIND_CODE = :kind
          AND  PRICE_TODAY IS NOT NULL
        GROUP BY RANK_NAME
    """, {"m": market, "item": item_code, "kind": kind_code})
    if not rows:
        return None
    rows.sort(key=lambda r: (0 if int(r["obs_recent"]) >= MIN_RECENT else 1,
                             rank_key(r["rank_name"])))
    return rows[0]["rank_name"]


def get_detail(item_code, kind_code, rank_name=None, chart_days=90, market=RETAIL):
    """한 품종의 최신 가격과 시점별 비교."""
    rank_name = _resolve_rank(item_code, kind_code, rank_name, market)
    if rank_name is None:
        return None
    rows = _series(item_code, kind_code, rank_name, market=market)
    if not rows:
        return None

    today = rows[0]
    today_date = today["survey_date"].date()
    past = rows[1:]

    compares = []
    for label, offset in COMPARE_POINTS:
        target = today_date - timedelta(days=offset)
        # '어제'는 목표 날짜가 아니라 '직전 조사일'로 잡는다.
        # 주말·공휴일이 끼면 하루 전 자료가 아예 없기 때문이다.
        hit = past[0] if offset == 1 and past else _nearest(past, target, TOLERANCE[offset])
        if hit is None:
            compares.append({"label": label, "target_offset": offset, "available": False})
            continue
        d = hit["survey_date"].date()
        gap = (today_date - d).days
        prev = float(hit["price_today"])
        cur = float(today["price_today"])
        compares.append({
            "label": label,
            "target_offset": offset,
            "available": True,
            "date": d.isoformat(),
            "days_ago": gap,
            "price": prev,
            "change_pct": round((cur - prev) / prev * 100, 1) if prev else None,
            # 목표 간격과 실제 간격이 다르면 화면에서 그 사실을 알린다
            "exact": gap == offset,
        })

    def num(v):
        return None if v is None else float(v)

    # 평년가(PRICE_NORMAL)는 행마다 들어 있다. 날짜에 따라 달라지므로
    # 수평선 하나가 아니라 실제 가격과 나란히 놓을 수 있는 선이 된다.
    cutoff = today_date - timedelta(days=chart_days)
    chart = [{"date": r["survey_date"].date().isoformat(),
              "price": float(r["price_today"]),
              "normal": num(r["price_normal"])}
             for r in reversed(rows) if r["survey_date"].date() >= cutoff]

    return {
        "market": market,
        "item_code": item_code, "kind_code": kind_code, "rank_name": rank_name,
        "item_name": today["item_name"], "kind_name": today["kind_name"],
        "category": today["category_name"], "unit": today["unit"],
        "date": today_date.isoformat(),
        "price": float(today["price_today"]),
        "compares": compares,
        "year_ago": num(today["price_1y"]),
        "normal": num(today["price_normal"]),
        "chart": chart,
        "observations": len(rows),
    }


# ── 급등락 ──────────────────────────────────────────────────────────────
def _recent_by_product(depth=40, market=RETAIL):
    """한 시장 모든 품종의 최근 depth 개 관측을 한 번에 가져온다.

    품목당 여러 등급이 있어도 여기서는 전부 가져오고, 대표 등급 선별은 파이썬에서 한다.
    (약 170 품종 x 40 = 7천 행이라 부담이 없다.)
    """
    return _query("""
        SELECT * FROM (
            SELECT ITEM_CODE, ITEM_NAME, KIND_CODE, KIND_NAME, RANK_NAME, UNIT,
                   CATEGORY_NAME, SURVEY_DATE, PRICE_TODAY,
                   ROW_NUMBER() OVER (
                       PARTITION BY ITEM_CODE, KIND_CODE, RANK_NAME
                       ORDER BY SURVEY_DATE DESC
                   ) AS rn
            FROM   TBL_DAILY_PRICE
            WHERE  PRICE_TODAY IS NOT NULL AND MARKET_TYPE = :m
        ) WHERE rn <= :depth
    """, {"depth": depth, "m": market})


def _compare_all(offset=1, max_stale=3, market=RETAIL):
    """모든 품목의 '지금 가격 vs offset 일 전 가격'을 구한다. 품목당 대표 등급 하나.

    offset=1 이면 '직전 조사일 대비', 그 외에는 '해당 일수에 가장 가까운 조사일 대비'.
    같은 품목에서는 대표 등급 하나만 남긴다 (갈치 大/中/小 가 순위를 도배하지 않도록).

    max_stale: 최근 조사가 이보다 오래된 품종은 제외한다.
      철이 지나 조사가 끊긴 품종(8월 기준 53개)을 그냥 두면,
      몇 주 떨어진 마지막 두 관측의 변동률이 '오늘의 변동'처럼 상위에 올라온다.

    급등락(get_movers)과 포춘쿠키(get_fortune)가 같은 규칙을 쓰도록 여기 한 곳에 모아 둔다.
    두 곳에 따로 적어두면 나중에 한쪽만 고쳐져 두 화면이 다른 말을 하게 된다.
    """
    rows = _recent_by_product(market=market)
    if not rows:
        return []
    by_product = {}
    for r in rows:
        by_product.setdefault((r["item_code"], r["kind_code"], r["rank_name"]), []).append(r)

    global_latest = max(r["survey_date"] for r in rows).date()
    tol = TOLERANCE.get(offset, max(4, offset // 3))
    cands = []
    for key, series in by_product.items():
        series.sort(key=lambda r: r["survey_date"], reverse=True)
        today = series[0]
        past = series[1:]
        if not past:
            continue
        today_date = today["survey_date"].date()
        # 철 지나 조사가 끊긴 품종은 제외
        if (global_latest - today_date).days > max_stale:
            continue
        hit = past[0] if offset == 1 else _nearest(past, today_date - timedelta(days=offset), tol)
        if hit is None:
            continue
        # 비교 대상도 너무 멀면 '오늘의 변동'이라 부를 수 없다
        if offset == 1 and (today_date - hit["survey_date"].date()).days > TOLERANCE[1]:
            continue
        prev, cur = float(hit["price_today"]), float(today["price_today"])
        if prev <= 0:
            continue
        d = hit["survey_date"].date()
        cands.append({
            "item_code": key[0], "kind_code": key[1], "rank_name": key[2],
            "item_name": today["item_name"], "kind_name": today["kind_name"],
            "category": today["category_name"], "unit": today["unit"],
            "date": today_date.isoformat(), "price": cur,
            "prev_date": d.isoformat(), "prev_price": prev,
            "days_ago": (today_date - d).days,
            "change_pct": round((cur - prev) / prev * 100, 1),
        })

    # 품목당 대표 등급 하나만 남긴다
    best = {}
    for c in cands:
        k = c["item_code"]
        if k not in best or rank_key(c["rank_name"]) < rank_key(best[k]["rank_name"]):
            best[k] = c
    return list(best.values())


def _prev_range(picked):
    """비교 시점은 품목마다 다르다. 연휴 뒤에는 특히 벌어진다 —
    2026-08-17 은 축산물 말고는 당일가격이 없어서, 08-18 기준 '어제'가
    축산물만 08-17 이고 나머지는 08-14 가 된다.
    화면에 한 품목의 날짜만 적으면 나머지를 잘못 설명하게 되므로 범위를 넘긴다.
    """
    prevs = sorted(c["prev_date"] for c in picked)
    return (prevs[0], prevs[-1]) if prevs else (None, None)


def get_movers(offset=1, limit=5, max_stale=3, market=RETAIL):
    """가격이 많이 오른/내린 품목 상위 limit 개."""
    picked = _compare_all(offset, max_stale, market)
    down = sorted(picked, key=lambda c: c["change_pct"])[:limit]
    up = sorted(picked, key=lambda c: -c["change_pct"])[:limit]
    lo, hi = _prev_range(picked)
    return {
        "market": market,
        "offset": offset,
        "compared": len(picked),
        "prev_from": lo,
        "prev_to": hi,
        "down": down,
        "up": up,
    }


def get_fortune(offset=1, max_stale=3, market=RETAIL):
    """포춘쿠키 후보 — 비교 가능한 품목 전부. 오른 것도 내린 것도 그대로 넘긴다.

    화면에서 이 중 하나를 무작위로 뽑아 등락과 함께 보여준다.
    걸러내는 것은 조사가 끊긴 품종뿐이고(그건 오늘 시세가 아니므로),
    등락 방향으로는 거르지 않는다.
    """
    picked = _compare_all(offset, max_stale, market)
    lo, hi = _prev_range(picked)
    up = sum(1 for c in picked if c["change_pct"] > 0)
    down = sum(1 for c in picked if c["change_pct"] < 0)
    return {
        "market": market,
        "offset": offset,
        "count": len(picked),
        "up_count": up,
        "down_count": down,
        "flat_count": len(picked) - up - down,
        "prev_from": lo,
        "prev_to": hi,
        "items": sorted(picked, key=lambda c: c["change_pct"]),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(get_meta(), ensure_ascii=False, indent=2))
    ps = list_products()
    print(f"\n품목 {len(ps)}개 · 품종 {sum(len(p['kinds']) for p in ps)}개")
    print("예:", [p["item_name"] for p in ps[:8]])

    d = get_detail("211", "02")     # 배추 여름(고랭지)
    print(f"\n{d['item_name']} {d['kind_name']} {d['rank_name']} · {d['date']} · {d['price']:,.0f}원")
    for c in d["compares"]:
        if c["available"]:
            mark = "" if c["exact"] else "  (실제 {}일 전)".format(c["days_ago"])
            print(f"  {c['label']:<8} {c['date']} {c['price']:>9,.0f}원 "
                  f"{c['change_pct']:+.1f}%{mark}")
        else:
            print(f"  {c['label']:<8} 자료 없음")

    m = get_movers(1)
    print(f"\n직전 조사일 대비 · 비교 {m['compared']}품목")
    print("  하락:", [(x["item_name"], x["change_pct"]) for x in m["down"]])
    print("  상승:", [(x["item_name"], x["change_pct"]) for x in m["up"]])
