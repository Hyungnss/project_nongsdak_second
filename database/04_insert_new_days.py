"""새로 받은 KAMIS CSV 를 TBL_DAILY_PRICE 에 이어붙인다.

기존 행은 지우지도 고치지도 않는다. TRUNCATE 후 전체 재적재하는
02_insert_daily_price.py 와 달리, 아직 DB 에 없는 조사 건만 골라 넣는다.

  실행:  .venv\\Scripts\\python.exe database\\04_insert_new_days.py [CSV경로]
  기본값: raws/kamis_price_data_20260815_20260818.csv

변환 규칙(등급 '-' -> '없음', 가격 '-' -> NULL, 날짜 TO_DATE)은
02_insert_daily_price.py 의 함수를 그대로 불러 쓴다. 두 곳에 같은 규칙을
따로 적어두면 나중에 한쪽만 고쳐져 데이터가 어긋나기 때문이다.
"""

import importlib.util
import sys
from pathlib import Path

import oracledb
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CSV = BASE_DIR / "raws" / "kamis_price_data_20260815_20260818.csv"

# 파일명이 숫자로 시작해 일반 import 가 안 된다. 경로로 직접 읽어들인다.
_LOADER_PATH = Path(__file__).resolve().parent / "02_insert_daily_price.py"
_spec = importlib.util.spec_from_file_location("kamis_loader", _LOADER_PATH)
loader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(loader)

# 자연키가 행 튜플의 몇 번째인지 (build_rows 의 order 기준)
#   0 조사일자 · 4 품목코드 · 6 품종코드 · 8 등급
KEY_IDX = (0, 4, 6, 8)


def key_of(row):
    return tuple(row[i] for i in KEY_IDX)


def existing_keys(cursor, dates):
    """해당 날짜들에 대해 DB 에 이미 있는 자연키를 가져온다."""
    found = set()
    # IN 절에 1000개 넘게 못 넣으므로 날짜를 나눠 묻는다 (여기선 며칠뿐이라 한 번에 끝난다)
    for i in range(0, len(dates), 500):
        chunk = dates[i:i + 500]
        binds = {f"d{j}": d for j, d in enumerate(chunk)}
        placeholders = ", ".join(f"TO_DATE(:{n}, 'YYYY-MM-DD')" for n in binds)
        cursor.execute(
            f"""SELECT TO_CHAR(SURVEY_DATE, 'YYYY-MM-DD'), ITEM_CODE, KIND_CODE, RANK_NAME
                FROM   TBL_DAILY_PRICE
                WHERE  SURVEY_DATE IN ({placeholders})
                  AND  MARKET_TYPE = '소매'""",
            binds,
        )
        found.update(cursor.fetchall())
    return found


def main():
    csv_file = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    if not csv_file.exists():
        raise SystemExit(f"CSV 를 찾을 수 없습니다: {csv_file}")

    df = pd.read_csv(csv_file, encoding="utf-8-sig", dtype=str)
    print(f"CSV 읽음: {csv_file.name} · {len(df):,}행")
    print(f"  기간 {df['조사일자'].min()} ~ {df['조사일자'].max()}")

    rows = loader.build_rows(df)
    dates = sorted(df["조사일자"].unique())

    conn = cursor = None
    try:
        conn = loader.connect()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM TBL_DAILY_PRICE")
        before = cursor.fetchone()[0]
        print(f"\n적재 전 테이블: {before:,}행")

        have = existing_keys(cursor, dates)
        todo = [r for r in rows if key_of(r) not in have]
        skipped = len(rows) - len(todo)
        print(f"  이 날짜들에 이미 있는 행: {len(have):,}건")
        print(f"  넣을 행 {len(todo):,} · 건너뛸 행 {skipped:,}")

        if not todo:
            print("\n새로 넣을 행이 없습니다. 아무것도 바꾸지 않았습니다.")
            return

        inserted = 0
        for i in range(0, len(todo), loader.BATCH_SIZE):
            chunk = todo[i:i + loader.BATCH_SIZE]
            cursor.executemany(loader.SQL, chunk)
            inserted += len(chunk)
            print(f"    {inserted:,}/{len(todo):,}행")

        conn.commit()
        print(f"\n적재 완료: {inserted:,}행")

        cursor.execute("SELECT COUNT(*) FROM TBL_DAILY_PRICE")
        after = cursor.fetchone()[0]
        print(f"테이블 행 수: {before:,} -> {after:,} (+{after - before:,})")

        cursor.execute("""
            SELECT MIN(SURVEY_DATE), MAX(SURVEY_DATE),
                   COUNT(DISTINCT ITEM_CODE), COUNT(DISTINCT SURVEY_DATE)
            FROM   TBL_DAILY_PRICE
        """)
        lo, hi, items, days = cursor.fetchone()
        print(f"기간 {lo:%Y-%m-%d} ~ {hi:%Y-%m-%d} · 품목 {items}개 · 조사일 {days}일")

    except oracledb.IntegrityError as e:
        if conn:
            conn.rollback()
        print(f"\n무결성 오류 (롤백함) — 같은 조사 건이 이미 있습니다: {e}")
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"\n적재 오류 (롤백함): {e}")
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
