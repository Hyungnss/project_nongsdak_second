r"""가격 과거분 백필 — KAMIS 기간 API 로 지금 다루는 품종들의 과거 가격을 채운다.

  실행:  uv run python -m collector.backfill --start 2016-01-01 --end 2025-08-31
         uv run python -m collector.backfill --start 2016-01-01 --end 2025-08-31 --market retail --limit 20
         uv run python -m collector.backfill --status            (진행 상황만 보기)
  서버:  docker compose run --rm collector python -m collector.backfill --start ... --end ...

왜 기간 API 인가
  매일 수집에 쓰는 '일별 부류별'(dailyPriceByCategoryList)은 하루 × 부류 하나에 한 번이라
  10년이면 3만 번 가까이 불러야 한다. '신) 일별 품목별 소매/도매'(periodRetailProductList ·
  periodWholesaleProductList)는 품목 · 품종 · 등급 하나의 최대 1년을 한 번에 준다.
  지금 다루는 조합이 소매 240 · 도매 221 개라 1년에 약 460 번이다.

받은 값이 기존 값과 같은가 (2026-11-19 확인)
  응답에는 지역 · 시장별 행과 함께 countyname='평균'(전국 평균) · '평년' 행이 있다.
  소매 5 · 도매 5 조합의 2025-09-01 ~ 2026-08-31 을 받아 DB 와 날짜마다 비교했더니
  1,802 일 모두 같고 다른 값은 0 이었다. 그래서 '평균' 을 PRICE_TODAY, '평년' 을 PRICE_NORMAL 로 쓴다.

지키는 규칙
  · 이미 있는 행은 덮어쓰지 않는다 (ON CONFLICT DO NOTHING). 매일 수집한 행에는 1일전 · 1주전 같은
    비교 가격까지 있어 더 풍부하다. 백필 행은 DATA_SOURCE='kamis_period' 로 표시한다.
  · 구간은 달력 1년 이하로 나눈다 (1년을 넘기면 KAMIS 가 자료를 주지 않는다).
  · 끝난 구간(OK · NO_DATA)은 TBL_BACKFILL_JOB 에 남겨 다시 부르지 않는다. 언제 멈춰도 이어 받는다.
  · 호출 사이를 --sleep 초(기본 1초) 쉰다. 인증 오류(900)면 바로 멈춘다.
  · 대상 품종은 지금 DB 에 있는 (시장, 품목, 품종, 등급) 조합이다. 이름 · 단위는 그 조합의 최신 행 것을 쓴다.
    그래서 예전에만 있다가 사라진 품종은 받지 않는다.
"""

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
import config  # noqa: E402
from collector import kamis  # noqa: E402
from collector import loader  # noqa: E402

SOURCE = "kamis_period"
ACTIONS = {"소매": "periodRetailProductList", "도매": "periodWholesaleProductList"}
MARKET_ARGS = {"retail": ["소매"], "wholesale": ["도매"], "all": ["소매", "도매"]}
RETRIES = 3


# ── 대상 · 구간 ───────────────────────────────────────────────────────────
def combos(conn, markets):
    """백필 대상 — 지금 DB 에 있는 (시장, 부류, 품목, 품종, 등급) 과 그 최신 이름 · 단위."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (MARKET_TYPE, ITEM_CODE, KIND_CODE, RANK_CODE)
                   MARKET_TYPE, CATEGORY_CODE, CATEGORY_NAME, ITEM_CODE, ITEM_NAME,
                   KIND_CODE, KIND_NAME, RANK_NAME, RANK_CODE, UNIT
            FROM   TBL_DAILY_PRICE
            WHERE  MARKET_TYPE = ANY(%(m)s) AND RANK_CODE IS NOT NULL
            ORDER  BY MARKET_TYPE, ITEM_CODE, KIND_CODE, RANK_CODE, SURVEY_DATE DESC
        """, {"m": markets})
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def chunks(start, end):
    """[start, end] 를 달력 연도로 자른다 (KAMIS 기간 API 는 최대 1년)."""
    out, s = [], start
    while s <= end:
        e = min(date(s.year, 12, 31), end)
        out.append((s, e))
        s = e + timedelta(days=1)
    return out


def done_chunks(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT MARKET_TYPE, ITEM_CODE, KIND_CODE, RANK_CODE, CHUNK_START
                       FROM TBL_BACKFILL_JOB WHERE STATUS IN ('OK', 'NO_DATA')""")
        return set(cur.fetchall())


# ── KAMIS ─────────────────────────────────────────────────────────────────
def call_period(c, s, e):
    """조합 하나의 [s, e] 원본 응답. 네트워크 오류는 몇 번 다시 시도한다."""
    cert_key, cert_id = config.require_kamis()
    params = {
        "action": ACTIONS[c["market_type"]],
        "p_cert_key": cert_key, "p_cert_id": cert_id, "p_returntype": "json",
        "p_startday": s.isoformat(), "p_endday": e.isoformat(),
        "p_itemcategorycode": c["category_code"], "p_itemcode": c["item_code"],
        "p_kindcode": c["kind_code"], "p_productrankcode": c["rank_code"],
        "p_convert_kg_yn": "N",          # 조사 단위 그대로 (매일 수집과 같게)
        # p_countrycode 는 넣지 않는다 — 넣으면 그 지역만 오고 '평균' 행이 없다
    }
    last = None
    for attempt in range(RETRIES):
        try:
            r = requests.get(kamis.BASE_URL, params=params, timeout=60)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as ex:
            last = ex
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{RETRIES}번 시도했지만 실패: {type(last).__name__}: {last}")


def _price(v):
    s = str(v or "").replace(",", "").strip()
    if s in ("", "-", "0", "0.0"):
        return None
    try:
        p = float(s)
    except ValueError:
        return None
    return p if p > 0 else None


def parse_period(body):
    """응답 → {조사일: (평균 가격, 평년 가격)}. 평균 가격이 없는 날은 뺀다."""
    avg, normal = {}, {}
    for it in kamis.extract_items(body):
        county = str(it.get("countyname") or "").strip()
        if county not in ("평균", "평년"):
            continue
        try:
            m, d = str(it.get("regday")).split("/")
            day = date(int(it.get("yyyy")), int(m), int(d))
        except (TypeError, ValueError):
            continue
        p = _price(it.get("price"))
        if p is None:
            continue
        (avg if county == "평균" else normal)[day] = p
    return {d: (p, normal.get(d)) for d, p in avg.items()}


# ── DB ────────────────────────────────────────────────────────────────────
INSERT_SQL = """
    INSERT INTO TBL_DAILY_PRICE (SURVEY_DATE, MARKET_TYPE, CATEGORY_NAME, CATEGORY_CODE,
        ITEM_CODE, ITEM_NAME, KIND_CODE, KIND_NAME, RANK_NAME, RANK_CODE, UNIT,
        PRICE_TODAY, PRICE_NORMAL, DATA_SOURCE)
    VALUES (%(d)s, %(market_type)s, %(category_name)s, %(category_code)s,
        %(item_code)s, %(item_name)s, %(kind_code)s, %(kind_name)s, %(rank_name)s, %(rank_code)s, %(unit)s,
        %(price)s, %(normal)s, %(src)s)
    ON CONFLICT (MARKET_TYPE, SURVEY_DATE, ITEM_CODE, KIND_CODE, RANK_NAME) DO NOTHING
"""

JOB_SQL = """
    INSERT INTO TBL_BACKFILL_JOB (MARKET_TYPE, ITEM_CODE, KIND_CODE, RANK_CODE, CHUNK_START, CHUNK_END,
                                  STATUS, ROWS_FOUND, ROWS_INSERTED, MESSAGE)
    VALUES (%(m)s, %(i)s, %(k)s, %(r)s, %(s)s, %(e)s, %(st)s, %(f)s, %(n)s, %(msg)s)
    ON CONFLICT (MARKET_TYPE, ITEM_CODE, KIND_CODE, RANK_CODE, CHUNK_START) DO UPDATE
       SET CHUNK_END = EXCLUDED.CHUNK_END, STATUS = EXCLUDED.STATUS, ROWS_FOUND = EXCLUDED.ROWS_FOUND,
           ROWS_INSERTED = EXCLUDED.ROWS_INSERTED, MESSAGE = EXCLUDED.MESSAGE, DONE_AT = now()
"""


def save_chunk(conn, c, s, e, prices):
    """한 구간을 한 트랜잭션으로 넣고 진행 기록을 남긴다. 새로 넣은 행 수를 돌려준다."""
    inserted = 0
    with conn.transaction(), conn.cursor() as cur:
        for d, (price, normal) in sorted(prices.items()):
            cur.execute(INSERT_SQL, {**c, "d": d, "price": price, "normal": normal, "src": SOURCE})
            inserted += cur.rowcount
        cur.execute(JOB_SQL, {"m": c["market_type"], "i": c["item_code"], "k": c["kind_code"],
                              "r": c["rank_code"], "s": s, "e": e,
                              "st": "OK" if prices else "NO_DATA", "f": len(prices), "n": inserted,
                              "msg": None})
    return inserted


def save_error(conn, c, s, e, msg):
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(JOB_SQL, {"m": c["market_type"], "i": c["item_code"], "k": c["kind_code"],
                              "r": c["rank_code"], "s": s, "e": e, "st": "ERROR", "f": 0, "n": 0,
                              "msg": msg[:500]})


# ── 실행 ──────────────────────────────────────────────────────────────────
def parse_args(argv):
    p = argparse.ArgumentParser(prog="python -m collector.backfill", description="KAMIS 가격 과거분 백필")
    p.add_argument("--start", type=date.fromisoformat, help="시작일 YYYY-MM-DD")
    p.add_argument("--end", type=date.fromisoformat, help="종료일 YYYY-MM-DD")
    p.add_argument("--market", choices=MARKET_ARGS, default="all")
    p.add_argument("--limit", type=int, default=0, help="이번 실행에서 부를 최대 구간 수 (0 = 끝까지)")
    p.add_argument("--sleep", type=float, default=1.0, help="호출 사이 쉬는 초 (기본 1)")
    p.add_argument("--status", action="store_true", help="진행 상황만 보고 끝낸다")
    a = p.parse_args(argv)
    if not a.status:
        if not a.start or not a.end:
            p.error("--start 와 --end 가 필요합니다")
        if a.start > a.end:
            p.error("--start 가 --end 보다 늦습니다")
    return a


def print_status(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT MARKET_TYPE, STATUS, COUNT(*), SUM(ROWS_FOUND), SUM(ROWS_INSERTED),
                              MIN(CHUNK_START), MAX(CHUNK_END)
                       FROM TBL_BACKFILL_JOB GROUP BY 1, 2 ORDER BY 1 DESC, 2""")
        rows = cur.fetchall()
        cur.execute("""SELECT MARKET_TYPE, COUNT(*), MIN(SURVEY_DATE), MAX(SURVEY_DATE)
                       FROM TBL_DAILY_PRICE WHERE DATA_SOURCE = %s GROUP BY 1 ORDER BY 1 DESC""", (SOURCE,))
        filled = cur.fetchall()
    print("── 구간 ──")
    for m, st, n, f, ins, s, e in rows or []:
        print(f"  {m} {st:<8} {n:>5}개 · 받은 {f or 0:>9,} · 넣은 {ins or 0:>9,} · {s} ~ {e}")
    if not rows:
        print("  아직 없음")
    print("── 백필로 들어간 행 ──")
    for m, n, s, e in filled or []:
        print(f"  {m} {n:,}행 · {s} ~ {e}")


def main(argv=None):
    a = parse_args(sys.argv[1:] if argv is None else argv)
    conn = loader.connect()
    # 구간마다 conn.transaction() 으로 확정한다. autocommit 이 아니면 첫 SELECT 가 연 트랜잭션 안에
    # 전부 쌓여 끝까지 커밋되지 않는다 — 중간에 멈추면 받은 것이 다 사라지고 이어받기도 안 된다.
    conn.autocommit = True
    try:
        if a.status:
            print_status(conn)
            return
        config.require_kamis()
        targets = combos(conn, MARKET_ARGS[a.market])
        skip = done_chunks(conn)
        todo = [(c, s, e) for c in targets for s, e in chunks(a.start, a.end)
                if (c["market_type"], c["item_code"], c["kind_code"], c["rank_code"], s) not in skip]
        if a.limit:
            todo = todo[:a.limit]
        print(f"\n===== {config.now_kst():%Y-%m-%d %H:%M} 가격 백필 · {a.start} ~ {a.end} =====")
        print(f"대상 조합 {len(targets)}개 · 남은 구간 {len(todo)}개 (끝난 구간 {len(skip)}개는 건너뜀)"
              f" · 예상 {len(todo) * (a.sleep + 0.8) / 60:.0f}분")

        found = inserted = errors = 0
        started = time.time()
        for n, (c, s, e) in enumerate(todo, 1):
            tag = f"{c['market_type']} {c['item_code']}/{c['kind_code']}/{c['rank_name']} {s.year}"
            try:
                body = call_period(c, s, e)
                code = kamis.error_code_of(body)
                if code == "900":
                    raise SystemExit("KAMIS 인증 오류(900) — 인증키를 확인해 주세요. 여기서 멈춥니다.")
                if code not in (None, "000", "001"):
                    raise RuntimeError(f"KAMIS error_code {code}")
                prices = parse_period(body)
                got = save_chunk(conn, c, s, e, prices)
                found += len(prices)
                inserted += got
            except SystemExit:
                raise
            except Exception as ex:
                errors += 1
                save_error(conn, c, s, e, f"{type(ex).__name__}: {ex}")
                print(f"  [{n}/{len(todo)}] {tag}  오류 — {type(ex).__name__}: {ex}")
            if n % 25 == 0 or n == len(todo):
                rate = n / max(time.time() - started, 1e-6)
                print(f"  [{n}/{len(todo)}] {tag} · 받은 {found:,} · 넣은 {inserted:,} · 오류 {errors}"
                      f" · 남은 약 {(len(todo) - n) / rate / 60:.0f}분")
            time.sleep(a.sleep)

        print(f"끝: 받은 {found:,}행 · 새로 넣은 {inserted:,}행 · 오류 {errors}구간"
              + (" (다시 실행하면 오류 구간만 다시 받는다)" if errors else ""))
        print_status(conn)
        if errors:
            sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
