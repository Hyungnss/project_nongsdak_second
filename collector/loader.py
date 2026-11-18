"""KAMIS 수집 CSV를 TBL_DAILY_PRICE 에 적재한다.

원본: data/raws/kamis_price_data_20250901_20260818.csv (43,480행 · 17컬럼)

적재하면서 바꾸는 것 세 가지
  1. 조사일자 '2025-09-01'  -> DATE (::date 로 변환)
  2. 등급 '-'               -> '없음'  (NULL 로 넣으면 UNIQUE 인덱스가 중복을 못 막는다)
  3. 가격 '-'               -> NULL    (숫자 컬럼이라 문자열을 넣을 수 없다)
     가격 0 이하            -> NULL    (KAMIS 가 '조사 없음' 을 0 으로 줄 때가 있다 — to_price 참고)

PRICE_NO 는 IDENTITY 가 채운다.

이 파일은 두 가지로 쓰인다.
  · 모듈: upsert · check 가 connect() 와 변환 규칙(to_price · build_rows)을 가져다 쓴다
  · 단독 실행: 빈 DB 에 원본 CSV 1년치를 넣는다
      uv run python -m collector.loader
    먼저 database/schema.sql 로 테이블을 만들어 둘 것 (docker compose 는 자동).

재적재할 때
  TRUNCATE TABLE TBL_DAILY_PRICE;  를 먼저 실행한다.
  자연키(UX_DAILY_PRICE_NATURAL)가 걸려 있어 그냥 다시 돌리면 중복 오류가 난다.
"""

import sys
from pathlib import Path

import pandas as pd
import psycopg

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
import config  # noqa: E402

# 08-17·18 을 합친 최신 파일. 예전 파일(..._20260814.csv)을 가리키면 이틀이 빠진다.
CSV_FILE = BASE_DIR / "data" / "raws" / "kamis_price_data_20250901_20260818.csv"

BATCH_SIZE = 5000

# CSV 컬럼 -> 바인드 순서
TEXT_COLS = ["구분", "부류명", "부류코드", "품목코드", "품목명", "품종코드", "품종명", "등급", "단위"]
PRICE_COLS = ["당일가격", "1일전가격", "1주일전가격", "2주일전가격",
              "1개월전가격", "1년전가격", "평년가격"]

SQL = """
INSERT INTO TBL_DAILY_PRICE
(
    SURVEY_DATE, MARKET_TYPE, CATEGORY_NAME, CATEGORY_CODE,
    ITEM_CODE, ITEM_NAME, KIND_CODE, KIND_NAME, RANK_NAME, UNIT,
    PRICE_TODAY, PRICE_1D, PRICE_1W, PRICE_2W, PRICE_1M, PRICE_1Y, PRICE_NORMAL
)
VALUES
(
    %s::date, %s, %s, %s,
    %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s
)
"""


def connect():
    """PostgreSQL 에 붙는다. 접속 정보는 config.PG (.env 의 DB_*).

    트랜잭션은 부르는 쪽이 commit / rollback 으로 직접 끝낸다 (autocommit 아님).
    """
    conn = psycopg.connect(**config.PG, connect_timeout=10)
    print(f"PostgreSQL 연결 성공 ({config.PG['host']}:{config.PG['port']}/{config.PG['dbname']})")
    return conn


def to_price(v):
    """가격 문자열을 숫자로. '-' 나 빈 값, 0 이하는 NULL(None).

    0 을 그대로 넣으면 화면이 '0원' 을 진짜 가격으로 보여준다. KAMIS 는 조사가 없는 칸을
    '-' 대신 0 으로 줄 때가 있다 — 소매 닭/절단육은 2025-10-25 부터 당일가격이 매일 0 이었고,
    소/갈비 · 수입 소고기/갈비살의 1년전 가격에도 0 이 섞여 있었다. 가격이 0원일 수는 없으니
    '조사 없음' 과 같게 NULL 로 넣는다.
    """
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-"):
        return None
    try:
        price = float(s)
    except ValueError:
        return None
    return price if price > 0 else None


def clean_text(v):
    return "" if v is None else str(v).strip()


def build_rows(df):
    """CSV 한 행을 바인드 튜플로 바꾼다.

    itertuples 는 쓰지 않는다. '1일전가격'처럼 숫자로 시작하는 컬럼명은
    파이썬 식별자가 될 수 없어 pandas 가 '_11' 같은 이름으로 바꿔버리기 때문이다.
    컬럼을 이름으로 직접 꺼내 zip 으로 묶는 방식이 안전하다.
    """
    order = ["조사일자", "구분", "부류명", "부류코드", "품목코드", "품목명",
             "품종코드", "품종명", "등급", "단위"] + PRICE_COLS
    missing = [c for c in order if c not in df.columns]
    if missing:
        raise KeyError(f"CSV에 없는 컬럼: {missing}")

    cols = [df[c].tolist() for c in order]
    rows = []
    for vals in zip(*cols):
        text = [clean_text(v) for v in vals[:10]]
        # 등급이 '-' 면 '없음'. NOT NULL 컬럼이라 빈 값을 넣을 수 없다.
        text[8] = "없음" if text[8] in ("", "-", "nan") else text[8]
        rows.append(tuple(text) + tuple(to_price(v) for v in vals[10:]))
    return rows


def main():
    df = pd.read_csv(CSV_FILE, encoding="utf-8-sig", dtype=str)
    print(f"CSV 읽음: {CSV_FILE.name} · {len(df):,}행")

    # 적재 전에 무엇이 바뀌는지 먼저 보여준다.
    n_rank = (df["등급"].str.strip() == "-").sum()
    print(f"  등급 '-' -> '없음' 변환: {n_rank:,}행")
    for c in PRICE_COLS:
        n = (df[c].str.strip() == "-").sum()
        if n:
            print(f"  {c} '-' -> NULL: {n:,}행")

    rows = build_rows(df)
    print(f"  변환 완료: {len(rows):,}행")

    conn = cursor = None
    inserted = 0
    try:
        conn = connect()
        cursor = conn.cursor()

        for i in range(0, len(rows), BATCH_SIZE):
            chunk = rows[i:i + BATCH_SIZE]
            cursor.executemany(SQL, chunk)
            inserted += len(chunk)
            print(f"    {inserted:,}/{len(rows):,}행")

        conn.commit()
        print(f"\n적재 완료: {inserted:,}행")

        cursor.execute("SELECT COUNT(*) FROM TBL_DAILY_PRICE")
        print(f"테이블 총 행 수: {cursor.fetchone()[0]:,}")

        cursor.execute("""
            SELECT MIN(SURVEY_DATE), MAX(SURVEY_DATE),
                   COUNT(DISTINCT ITEM_CODE), COUNT(PRICE_TODAY)
            FROM   TBL_DAILY_PRICE
        """)
        lo, hi, items, priced = cursor.fetchone()
        print(f"기간 {lo:%Y-%m-%d} ~ {hi:%Y-%m-%d} · 품목 {items}개 · "
              f"당일가격 있는 행 {priced:,}")

    except psycopg.IntegrityError as e:
        if conn:
            conn.rollback()
        print("\n무결성 오류 — 이미 적재된 데이터가 있을 수 있습니다.")
        print("  TRUNCATE TABLE TBL_DAILY_PRICE; 를 실행한 뒤 다시 시도하세요.")
        print(f"  상세: {e}")
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
