"""KAMIS OpenAPI 로 하루치를 받아 TBL_DAILY_PRICE 에 MERGE 로 반영한다 (5·6단계).

  실행:  .venv\\Scripts\\python.exe database\\06_upsert_daily_price.py [YYYY-MM-DD]
  기본값: 오늘
  옵션:  --dry-run   받아서 요약만 보여주고 DB 는 건드리지 않는다
         --days N    그날부터 거슬러 N일치를 함께 요청한다 (기본 1)

왜 --days 가 필요한가
  하루 한 번 실행은 그날 날짜만 요청한다. 실행을 한 번 놓치면 그날은 영영 빈칸이다.
  다음날 실행은 어제가 아니라 오늘을 요청하기 때문이다. 노트북이 꺼져 있던 날,
  스케줄러가 걸러 먹은 날이 그대로 구멍으로 남는다.

  덤으로 KAMIS 의 사후 개정도 따라간다 — 2026-08-18 을 나중에 다시 받아 보니
  물오징어 원양(냉동)/中 이 5,271 -> 5,258 로, 꽃게의 1년전·평년이 '-' -> 19,511 로
  바뀌어 있었다. MERGE 라 다시 받아도 중복되지 않고 값만 최신이 된다.

  주말을 메우는 용도가 아님에 주의. 토·일은 며칠 뒤에 다시 받아도 축산물 29행뿐이다.
  (KAMIS 가 조사를 안 한 날이라 애초에 자료가 없다.)

왜 04 가 아니라 이걸 쓰는가
  04_insert_new_days.py 는 DB 에 이미 있는 자연키를 건너뛴다. 사람이 하루 한 번
  돌릴 때는 맞지만 자동 수집에서는 틀린다.

    오전 10시 호출 -> 당일가격이 아직 '-' -> NULL 인 채로 행이 들어간다
    오후 4시 재호출 -> 값이 채워져 있지만 자연키가 이미 있어 건너뛴다
    결과: 오늘 시세가 영원히 빈칸으로 남는다

  그래서 MERGE 로 덮어쓴다. 하루에 여러 번 돌려도 중복되지 않고 값만 최신이 된다.
  실제로 KAMIS 는 공표 뒤에도 값을 보정한다 — 2026-08-18 을 나중에 다시 받아 보니
  물오징어 원양(냉동)/中 이 5,271 -> 5,258 로 바뀌어 있었고, 꽃게의 1년전·평년은
  비어 있다가 채워져 있었다 (09_verify_against_csv.py 로 확인).

NULL 로 덮어쓰지 않는다
  이미 값이 있는 행에 늦게 도착한 '-'(NULL)를 그대로 UPDATE 하면 있던 값이 지워진다.
  UPDATE 절을 NVL(:price, t.PRICE) 로 감싼다.

이 DB(11.2.0.2)에서 확인해 둔 것
  · MERGE 의 INSERT 절에 SEQ_DAILY_PRICE.NEXTVAL -> 된다 (ORA-02287 안 남)
  · executemany + 이름 바인드로 MERGE -> 된다
  · UPDATE 절에 ON 조건 컬럼을 넣으면 ORA-38104 -> 자연키 4개는 UPDATE 에서 뺐다

먼저 07_create_fetch_log.sql 을 실행해 TBL_FETCH_LOG 를 만들어 둘 것.
"""

import importlib.util
import sys
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

import oracledb

BASE_DIR = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))


def _load(name, filename):
    """파일명이 숫자로 시작해 일반 import 가 안 된다. 경로로 직접 읽어들인다."""
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 변환 규칙(등급 '-' -> '없음', 가격 '-' -> NULL)과 접속은 02 의 것을 그대로 쓴다.
# 같은 규칙을 두 곳에 적어두면 나중에 한쪽만 고쳐져 데이터가 어긋난다.
loader = _load("kamis_loader", "02_insert_daily_price.py")
fetcher = _load("kamis_fetcher", "05_fetch_kamis.py")

# build_rows 가 돌려주는 튜플의 순서 -> MERGE 의 바인드 이름
BIND_NAMES = [
    "survey_date", "market_type", "category_name", "category_code",
    "item_code", "item_name", "kind_code", "kind_name", "rank_name", "unit",
    "price_today", "price_1d", "price_1w", "price_2w",
    "price_1m", "price_1y", "price_normal",
]
PRICE_BINDS = BIND_NAMES[10:]

MERGE_SQL = """
MERGE INTO TBL_DAILY_PRICE t
USING (
    SELECT TO_DATE(:survey_date, 'YYYY-MM-DD') AS SURVEY_DATE,
           :item_code AS ITEM_CODE,
           :kind_code AS KIND_CODE,
           :rank_name AS RANK_NAME
    FROM DUAL
) s
ON (    t.SURVEY_DATE = s.SURVEY_DATE
    AND t.ITEM_CODE   = s.ITEM_CODE
    AND t.KIND_CODE   = s.KIND_CODE
    AND t.RANK_NAME   = s.RANK_NAME)
WHEN MATCHED THEN UPDATE SET
    t.PRICE_TODAY  = NVL(:price_today,  t.PRICE_TODAY),
    t.PRICE_1D     = NVL(:price_1d,     t.PRICE_1D),
    t.PRICE_1W     = NVL(:price_1w,     t.PRICE_1W),
    t.PRICE_2W     = NVL(:price_2w,     t.PRICE_2W),
    t.PRICE_1M     = NVL(:price_1m,     t.PRICE_1M),
    t.PRICE_1Y     = NVL(:price_1y,     t.PRICE_1Y),
    t.PRICE_NORMAL = NVL(:price_normal, t.PRICE_NORMAL)
WHEN NOT MATCHED THEN INSERT
    (PRICE_NO, SURVEY_DATE, MARKET_TYPE, CATEGORY_NAME, CATEGORY_CODE,
     ITEM_CODE, ITEM_NAME, KIND_CODE, KIND_NAME, RANK_NAME, UNIT,
     PRICE_TODAY, PRICE_1D, PRICE_1W, PRICE_2W, PRICE_1M, PRICE_1Y, PRICE_NORMAL)
VALUES
    (SEQ_DAILY_PRICE.NEXTVAL, s.SURVEY_DATE, :market_type, :category_name, :category_code,
     s.ITEM_CODE, :item_name, s.KIND_CODE, :kind_name, s.RANK_NAME, :unit,
     :price_today, :price_1d, :price_1w, :price_2w, :price_1m, :price_1y, :price_normal)
"""

LOG_SQL = """
INSERT INTO TBL_FETCH_LOG
    (LOG_NO, SURVEY_DATE, CATEGORY_CODE, STATUS, ROWS_FETCHED, ROWS_UPSERTED, MESSAGE)
VALUES
    (SEQ_FETCH_LOG.NEXTVAL, TO_DATE(:survey_date, 'YYYY-MM-DD'),
     :category_code, :status, :rows_fetched, :rows_upserted, :message)
"""

# 바인드 크기. 한 배치가 전부 NULL 인 가격 컬럼이 있으면 oracledb 가 타입을
# 못 정해 터지므로 미리 알려 준다. 문자열 길이는 01_create_kamis_table.sql 기준.
INPUT_SIZES = dict(
    survey_date=20, market_type=10, category_name=20, category_code=5,
    item_code=10, item_name=40, kind_code=10, kind_name=60,
    rank_name=30, unit=20,
    **{n: oracledb.NUMBER for n in PRICE_BINDS},
)


def to_binds(rows):
    """build_rows 의 튜플을 이름 바인드 dict 로 바꾼다."""
    return [dict(zip(BIND_NAMES, r)) for r in rows]


def write_log(conn, survey_date, cat_code, status, fetched=0, upserted=0, message=None):
    """수집 이력 한 줄. 로그 실패가 수집을 막지는 않게 한다."""
    try:
        with conn.cursor() as cur:
            cur.execute(LOG_SQL, dict(
                survey_date=survey_date, category_code=cat_code, status=status,
                rows_fetched=fetched, rows_upserted=upserted,
                message=(message or "")[:500] or None))
        conn.commit()
    except oracledb.Error as e:
        if "ORA-00942" in str(e):     # table or view does not exist
            print("  (TBL_FETCH_LOG 가 없습니다 — 07_create_fetch_log.sql 을 실행하세요)")
        else:
            print(f"  (수집 로그 기록 실패: {e})")


def upsert(conn, rows_dicts):
    """MERGE 로 반영하고 반영된 행 수를 돌려준다."""
    import pandas as pd

    df = pd.DataFrame(rows_dicts)
    binds = to_binds(loader.build_rows(df))
    with conn.cursor() as cur:
        cur.setinputsizes(**INPUT_SIZES)
        cur.executemany(MERGE_SQL, binds)
        return cur.rowcount


def parse_args(argv):
    """(조사일, 일수, dry) 를 돌려준다.

    `--days 3` 의 '3' 이 날짜 인자로 새지 않도록 앞에서부터 직접 훑는다.
    (`a.startswith("--")` 로 옵션만 걸러내면 '3' 이 날짜로 잡힌다.)
    """
    day, days, dry = None, 1, False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--dry-run":
            dry = True
        elif a == "--days" or a.startswith("--days="):
            if a == "--days":
                i += 1
                if i >= len(argv):
                    raise SystemExit("--days 뒤에 일수를 적어 주세요. 예) --days 3")
                raw = argv[i]
            else:
                raw = a.split("=", 1)[1]
            if not raw.isdigit() or int(raw) < 1:
                raise SystemExit(f"--days 는 1 이상의 정수여야 합니다: {raw!r}")
            days = int(raw)
        elif a.startswith("--"):
            raise SystemExit(f"모르는 옵션입니다: {a}")
        elif day is None:
            day = a
        else:
            raise SystemExit(f"날짜는 하나만 적어 주세요 ({day}, {a})")
        i += 1

    day = day or date.today().isoformat()
    try:
        date.fromisoformat(day)
    except ValueError:
        raise SystemExit(f"날짜 형식이 잘못됐습니다: {day!r} (YYYY-MM-DD)")
    return day, days, dry


def target_days(day, days):
    """받아 올 조사일 목록. 최신부터 거슬러 간다 — [오늘, 어제, 그저께]."""
    end = date.fromisoformat(day)
    return [(end - timedelta(days=k)).isoformat() for k in range(days)]


def run_day(conn, day, dry):
    """하루치를 6개 부류 순회하며 반영한다. (받은 행, 반영 행, 실패한 부류) 를 돌려준다."""
    fetched = upserted = 0
    failed = []

    for i, (cat_code, cat_name) in enumerate(fetcher.CATEGORIES.items()):
        if i:
            time.sleep(0.5)      # 연속 호출 간격
        try:
            rows, err = fetcher.fetch_category_status(cat_code, day)
        except Exception as e:
            # 한 부류가 실패해도 나머지는 계속 받는다.
            msg = f"{type(e).__name__}: {e}"
            print(f"  {cat_code} {cat_name:<6} 실패 — {msg}")
            failed.append(cat_code)
            if conn:
                write_log(conn, day, cat_code, "ERROR", message=msg)
            continue

        fetched += len(rows)
        if not rows:
            # 주말·공휴일이면 정상이다. ERROR 로 적으면 매주 경고가 울려
            # 아무도 안 보게 된다.
            print(f"  {cat_code} {cat_name:<6}    0행  (자료 없음)")
            if conn:
                write_log(conn, day, cat_code, "NO_DATA", message=f"error_code={err}")
            continue

        if dry:
            priced = sum(r["당일가격"] != "-" for r in rows)
            print(f"  {cat_code} {cat_name:<6} {len(rows):>4}행  당일가격 {priced}건")
            continue

        try:
            n = upsert(conn, rows)
            conn.commit()
            upserted += n
            priced = sum(r["당일가격"] != "-" for r in rows)
            print(f"  {cat_code} {cat_name:<6} {len(rows):>4}행 반영  당일가격 {priced}건")
            write_log(conn, day, cat_code, "OK", len(rows), n)
        except Exception as e:
            conn.rollback()
            msg = f"{type(e).__name__}: {e}"
            print(f"  {cat_code} {cat_name:<6} 적재 실패 — {msg}")
            traceback.print_exc()
            failed.append(cat_code)
            write_log(conn, day, cat_code, "ERROR", len(rows), 0, msg)

    if dry:
        return fetched, upserted, failed

    # 그날의 요약 한 줄 (CATEGORY_CODE = NULL)
    if failed:
        status, msg = "ERROR", f"실패한 부류: {','.join(failed)}"
    elif fetched == 0:
        status, msg = "NO_DATA", "전 부류 자료 없음 (주말·공휴일이면 정상)"
    else:
        status, msg = "OK", None
    write_log(conn, day, None, status, fetched, upserted, msg)

    with conn.cursor() as cur:
        cur.execute("""SELECT COUNT(*), COUNT(PRICE_TODAY)
                       FROM   TBL_DAILY_PRICE
                       WHERE  SURVEY_DATE = TO_DATE(:d, 'YYYY-MM-DD')""", d=day)
        n, priced = cur.fetchone()
        print(f"  DB 의 {day}: {n}행 · 당일가격 있는 행 {priced}")

    return fetched, upserted, failed


def main():
    day, days, dry = parse_args(sys.argv[1:])
    targets = target_days(day, days)

    span = targets[0] if days == 1 else f"{targets[-1]} ~ {targets[0]} ({days}일치)"
    # logs\fetch.log 에 계속 덧붙으므로 실행 구분선을 남긴다.
    print(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====")
    print(f"수집 시작 · 조사일 {span}" + ("  [dry-run · DB 안 건드림]" if dry else ""))

    conn = None if dry else loader.connect()
    total_fetched = total_upserted = 0
    failed_days = []

    try:
        for i, target in enumerate(targets):
            if i:
                time.sleep(0.5)
            if days > 1:
                print(f"\n[{target}]")
            fetched, upserted, failed = run_day(conn, target, dry)
            total_fetched += fetched
            total_upserted += upserted
            if failed:
                failed_days.append(f"{target}({','.join(failed)})")

        print(f"\n받은 행 {total_fetched:,} · 반영 {total_upserted:,}")

        if dry:
            print("dry-run 이라 DB 는 그대로입니다.")
            return

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), MAX(SURVEY_DATE) FROM TBL_DAILY_PRICE")
            total, last = cur.fetchone()
            print(f"테이블 전체: {total:,}행 · 최신 조사일 {last:%Y-%m-%d}")

        if failed_days:
            print(f"실패: {' · '.join(failed_days)}")
            sys.exit(1)

    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
