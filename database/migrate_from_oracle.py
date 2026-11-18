"""Oracle(v1) -> PostgreSQL(v2) 데이터 이전. 한 번 쓰고 마는 도구다.

  실행:  uv run python -m database.migrate_from_oracle            (Postgres 가 비어 있어야 한다)
         uv run python -m database.migrate_from_oracle --replace  (Postgres 를 비우고 다시 옮긴다)
         uv run python -m database.migrate_from_oracle --verify   (옮기지 않고 비교만 한다)

하는 일
  1. Oracle 6개 테이블을 전부 읽는다 (읽기만 한다 — Oracle 은 바꾸지 않는다)
  2. PostgreSQL 에 COPY 로 넣는다. 일련번호(PRICE_NO 등)는 원래 번호 그대로 넣는다
  3. IDENTITY 번호를 '지금 가장 큰 번호 다음' 부터 이어지게 맞춘다
  4. 양쪽의 모든 행을 기본키 순서로 한 줄씩 비교한다. 하나라도 다르면 실패로 끝난다

값 변환
  · Oracle DATE 는 날짜+시각이다. 조사일 같은 '날짜' 컬럼은 날짜만 떼어 DATE 로 넣는다
  · 시각 컬럼(CREATED_AT 등)은 시간대 정보가 없는 한국 시각이다. Asia/Seoul 로 읽어
    TIMESTAMPTZ 로 넣는다 (저장은 UTC, 보일 때는 다시 한국 시각)
  · 가격 NUMBER(12,2) 는 Decimal 로 읽어 소수점 오차 없이 NUMERIC 으로 넣는다
  · API 원문 CLOB 은 JSON 으로 넣는다(JSONB). BODY_HASH 는 원래 값을 그대로 둔다 —
    수집기는 새 응답의 해시를 이 값과 비교해 '바뀌었을 때만' 쌓는다

먼저 해 둘 것
  · docker compose up -d db   (database/schema.sql 로 빈 테이블이 만들어진다)
  · .env 에 Oracle(ORACLE_*) 과 PostgreSQL(DB_*) 접속 정보가 둘 다 있어야 한다
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import oracledb
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

KST = ZoneInfo("Asia/Seoul")

# Oracle 에서 꺼낼 때 숫자는 Decimal, CLOB 은 문자열로 바로 받는다 (LOB 객체를 하나씩 읽지 않게).
oracledb.defaults.fetch_decimals = True
oracledb.defaults.fetch_lobs = False

# FK 순서대로 (회원이 먼저 있어야 세션 · 장바구니를 넣을 수 있다).
# kind: date = 날짜만 / ts = 한국 시각 -> TIMESTAMPTZ / json = JSONB
TABLES = [
    ("TBL_USER", "USER_NO", [
        ("USER_NO", None), ("LOGIN_ID", None), ("PASSWORD_HASH", None), ("NICKNAME", None),
        ("CREATED_AT", "ts"), ("LAST_LOGIN_AT", "ts"),
    ]),
    ("TBL_USER_SESSION", "TOKEN_HASH", [
        ("TOKEN_HASH", None), ("USER_NO", None), ("CREATED_AT", "ts"), ("EXPIRES_AT", "ts"),
    ]),
    ("TBL_CART_ITEM", "CART_NO", [
        ("CART_NO", None), ("USER_NO", None), ("ITEM_CODE", None), ("KIND_CODE", None),
        ("RANK_NAME", None), ("QTY", None), ("ADDED_AT", "ts"),
    ]),
    ("TBL_DAILY_PRICE", "PRICE_NO", [
        ("PRICE_NO", None), ("SURVEY_DATE", "date"), ("MARKET_TYPE", None),
        ("CATEGORY_NAME", None), ("CATEGORY_CODE", None), ("ITEM_CODE", None), ("ITEM_NAME", None),
        ("KIND_CODE", None), ("KIND_NAME", None), ("RANK_NAME", None), ("RANK_CODE", None), ("UNIT", None),
        ("PRICE_TODAY", None), ("PRICE_1D", None), ("PRICE_1W", None), ("PRICE_2W", None),
        ("PRICE_1M", None), ("PRICE_1Y", None), ("PRICE_NORMAL", None),
        ("PRICE_1D_DATE", "date"), ("PRICE_1W_DATE", "date"), ("PRICE_2W_DATE", "date"),
        ("CREATED_AT", "ts"),
    ]),
    ("TBL_FETCH_LOG", "LOG_NO", [
        ("LOG_NO", None), ("FETCHED_AT", "ts"), ("SURVEY_DATE", "date"), ("MARKET_TYPE", None),
        ("CATEGORY_CODE", None), ("STATUS", None), ("ROWS_FETCHED", None), ("ROWS_UPSERTED", None),
        ("MESSAGE", None),
    ]),
    ("TBL_API_RAW", "RAW_NO", [
        ("RAW_NO", None), ("FETCHED_AT", "ts"), ("SURVEY_DATE", "date"), ("MARKET_TYPE", None),
        ("CATEGORY_CODE", None), ("ERROR_CODE", None), ("ITEM_COUNT", None), ("BODY_HASH", None),
        ("BODY", "json"),
    ]),
]

# IDENTITY 를 이어 줄 (테이블, 컬럼). TBL_USER_SESSION 은 토큰이 키라 번호가 없다.
IDENTITIES = [(t, pk) for t, pk, _ in TABLES if t != "TBL_USER_SESSION"]


# ── 접속 ─────────────────────────────────────────────────────────────────────
def connect_oracle():
    """thin 으로 먼저 붙어 보고, 11g 라 안 되면(DPY-3010) Instant Client 로 thick 전환."""
    args = dict(user=config.ORACLE_USER, password=config.ORACLE_PASSWORD, **config.ORACLE_DSN)
    try:
        return oracledb.connect(**args)
    except oracledb.Error as e:
        if "DPY-3010" not in str(e):
            raise
    oracledb.init_oracle_client(lib_dir=config.ORACLE_CLIENT_DIR)
    return oracledb.connect(**args)


def connect_pg():
    return psycopg.connect(**config.PG)


# ── 값 변환 ──────────────────────────────────────────────────────────────────
def to_pg(value, kind):
    """Oracle 에서 읽은 값 하나를 Postgres 에 넣을 값으로."""
    if value is None:
        return None
    if kind == "date":
        return value.date()
    if kind == "ts":
        return value.replace(tzinfo=KST)
    return value


def normalize(value, kind):
    """비교용. 양쪽 값을 같은 모양으로 맞춘다 (시각은 UTC, JSON 은 dict)."""
    if value is None:
        return None
    if kind == "date" and isinstance(value, datetime):
        return value.date()
    if kind == "ts":
        if value.tzinfo is None:
            value = value.replace(tzinfo=KST)
        return value.astimezone(ZoneInfo("UTC"))
    if kind == "json" and isinstance(value, str):
        return json.loads(value)
    return value


def oracle_rows(ocur, table, pk, cols):
    names = ", ".join(c for c, _ in cols)
    ocur.execute(f"SELECT {names} FROM {table} ORDER BY {pk}")
    return ocur.fetchall()


def pg_rows(pcur, table, pk, cols):
    names = ", ".join(c for c, _ in cols)
    pcur.execute(f"SELECT {names} FROM {table} ORDER BY {pk}")
    return pcur.fetchall()


# ── 옮기기 ───────────────────────────────────────────────────────────────────
def check_empty(pconn, replace):
    with pconn.cursor() as cur:
        counts = {}
        for t, _, _ in TABLES:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            counts[t] = cur.fetchone()[0]
    filled = {t: n for t, n in counts.items() if n}
    if not filled:
        return
    if not replace:
        raise SystemExit(
            f"Postgres 에 이미 데이터가 있습니다: {filled}\n"
            "  다시 옮기려면 --replace 를 붙이세요 (Postgres 쪽을 비우고 다시 넣습니다)."
        )
    names = ", ".join(t for t, _, _ in TABLES)
    with pconn.cursor() as cur:
        cur.execute(f"TRUNCATE {names} RESTART IDENTITY CASCADE")
    print(f"  Postgres 를 비웠습니다: {filled}")


def copy_table(ocur, pconn, table, pk, cols):
    t0 = time.time()
    rows = oracle_rows(ocur, table, pk, cols)
    names = ", ".join(c for c, _ in cols)
    with pconn.cursor() as cur, cur.copy(f"COPY {table} ({names}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row([to_pg(v, kind) for v, (_, kind) in zip(r, cols)])
    print(f"  {table:<18} {len(rows):>8,}행  ({time.time() - t0:.1f}초)")
    return len(rows)


def reset_identities(pconn):
    with pconn.cursor() as cur:
        for table, col in IDENTITIES:
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{table.lower()}', '{col.lower()}'), "
                f"COALESCE(MAX({col}), 0) + 1, false) FROM {table}"
            )
            print(f"  {table:<18} 다음 번호 {cur.fetchone()[0]:,}")


# ── 검증 ─────────────────────────────────────────────────────────────────────
def verify(oconn, pconn):
    """모든 테이블의 모든 행을 기본키 순서로 한 줄씩 비교한다."""
    ok = True
    with oconn.cursor() as ocur, pconn.cursor() as pcur:
        for table, pk, cols in TABLES:
            o = oracle_rows(ocur, table, pk, cols)
            p = pg_rows(pcur, table, pk, cols)
            diffs = []
            if len(o) != len(p):
                diffs.append(f"행 수 다름: Oracle {len(o):,} / Postgres {len(p):,}")
            for orow, prow in zip(o, p):
                for (name, kind), ov, pv in zip(cols, orow, prow):
                    if normalize(ov, kind) != normalize(pv, kind):
                        diffs.append(f"{pk}={orow[0]} {name}: Oracle {ov!r} / Postgres {pv!r}")
                        break
                if len(diffs) >= 5:
                    break
            mark = "일치" if not diffs else "불일치"
            print(f"  {table:<18} {len(o):>8,}행  {mark}")
            for d in diffs:
                print(f"      {d}")
            ok = ok and not diffs
    return ok


def main():
    args = set(sys.argv[1:])
    unknown = args - {"--replace", "--verify"}
    if unknown:
        raise SystemExit(f"모르는 옵션입니다: {', '.join(sorted(unknown))}")

    oconn = connect_oracle()
    pconn = connect_pg()
    print(f"Oracle {oconn.version} -> PostgreSQL {pconn.info.server_version // 10000}."
          f"{pconn.info.server_version % 10000}  ({config.PG['host']}:{config.PG['port']}/{config.PG['dbname']})")

    if "--verify" not in args:
        print("\n[1/3] 옮기기")
        with pconn.transaction():           # 중간에 실패하면 Postgres 쪽은 통째로 되돌린다
            check_empty(pconn, "--replace" in args)
            with oconn.cursor() as ocur:
                total = sum(copy_table(ocur, pconn, t, pk, cols) for t, pk, cols in TABLES)
            print(f"  합계 {total:,}행")
            print("\n[2/3] 일련번호 이어 주기")
            reset_identities(pconn)

    print("\n[3/3] 검증 — 모든 행 비교")
    ok = verify(oconn, pconn)
    oconn.close()
    pconn.close()
    if not ok:
        raise SystemExit("\n검증 실패: 위의 불일치를 확인하세요.")
    print("\n완료: 모든 테이블의 모든 행이 일치합니다.")


if __name__ == "__main__":
    main()
