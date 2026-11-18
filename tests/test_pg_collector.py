"""수집기 SQL 을 실제 PostgreSQL 에 돌려 본다 (collector/upsert.py · check.py).

가짜 DB 로는 못 잡는 것 — SQL 문법, ON CONFLICT 동작, 제약(CHECK), JSONB 저장 — 을 본다.
KAMIS 는 부르지 않는다. 응답 모양의 dict 를 직접 만들어 넣는다.
"""

import psycopg
import pytest

from collector import check, kamis, loader, upsert

DAY = "2026-11-17"


def _item(**over):
    it = {"item_name": "배추", "item_code": "211", "kind_name": "가을", "kind_code": "01",
          "rank": "상품", "rank_code": "04", "unit": "1포기",
          "day2": "1일전 (11/14)", "dpr1": "3,980", "dpr2": "4,010", "dpr3": "-", "dpr4": "4,200",
          "dpr5": "4,300", "dpr6": "3,500", "dpr7": "4,100"}
    it.update(over)
    return it


def _rows(*items, cls=kamis.RETAIL):
    body = {"data": {"error_code": "000", "item": list(items)}}
    return kamis.rows_from(body, "200", DAY, cls)


def _price_row(conn):
    return conn.execute("""SELECT PRICE_TODAY, PRICE_1D, PRICE_1W, PRICE_1Y, PRICE_1D_DATE, ITEM_NAME
                           FROM TBL_DAILY_PRICE""").fetchall()


@pytest.fixture
def conn(pg_db):
    """수집기와 같은 방식(loader.connect, autocommit 아님)으로 붙는다."""
    c = loader.connect()
    yield c
    c.close()


# ── 시세 반영 (INSERT ... ON CONFLICT) ───────────────────────────────────
def test_upsert_inserts_new_rows(conn, pg_db):
    n = upsert.upsert(conn, _rows(_item(), _item(rank="중품", rank_code="05", dpr1="3,500")))
    conn.commit()
    assert n == 2
    (row, _) = sorted(_price_row(pg_db))
    assert float(row[0]) == 3500.0


def test_upsert_twice_does_not_duplicate(conn, pg_db):
    """매일 7일치를 다시 받는다. 같은 자연키는 한 행으로 남아야 한다."""
    for _ in range(2):
        upsert.upsert(conn, _rows(_item()))
        conn.commit()
    assert pg_db.execute("SELECT COUNT(*) FROM TBL_DAILY_PRICE").fetchone()[0] == 1


def test_upsert_updates_value_but_null_does_not_erase(conn, pg_db):
    """KAMIS 의 사후 보정은 반영하고, 늦게 온 '-'(NULL)는 있던 값을 지우지 않는다."""
    upsert.upsert(conn, _rows(_item()))
    conn.commit()
    upsert.upsert(conn, _rows(_item(dpr1="3,900", dpr2="-", item_name="바뀐이름")))
    conn.commit()
    today, d1, _, _, _, name = _price_row(pg_db)[0]
    assert float(today) == 3900.0          # 보정된 값으로 갱신
    assert float(d1) == 4010.0             # '-' 가 와도 기존 값 유지
    assert name == "배추"                   # 이름 칸은 처음 값 그대로 (Oracle MERGE 때와 같다)


def test_upsert_zero_price_is_stored_as_null(conn, pg_db):
    upsert.upsert(conn, _rows(_item(dpr1="0", dpr6="0")))
    conn.commit()
    today, _, _, year_ago, _, _ = _price_row(pg_db)[0]
    assert today is None and year_ago is None


def test_upsert_keeps_actual_comparison_dates(conn, pg_db):
    upsert.upsert(conn, _rows(_item()))
    conn.commit()
    assert str(_price_row(pg_db)[0][4]) == "2026-11-14"     # '1일전 (11/14)'


def test_retail_and_wholesale_are_separate_rows(conn, pg_db):
    """같은 품종 · 등급 · 날짜라도 시장이 다르면 다른 행이다 (자연키에 MARKET_TYPE)."""
    upsert.upsert(conn, _rows(_item()))
    upsert.upsert(conn, _rows(_item(dpr1="39,000"), cls=kamis.WHOLESALE))
    conn.commit()
    got = dict(pg_db.execute("SELECT MARKET_TYPE, PRICE_TODAY FROM TBL_DAILY_PRICE").fetchall())
    assert {k: float(v) for k, v in got.items()} == {"소매": 3980.0, "도매": 39000.0}


def test_db_rejects_zero_price_from_other_paths(pg_db):
    """수집기를 거치지 않고 0원을 넣으려 하면 DB 가 막는다 (CK_DAILY_PRICE_POSITIVE)."""
    from tests.conftest import add_price
    with pytest.raises(psycopg.errors.CheckViolation):
        add_price(pg_db, DAY, price=0)


# ── 응답 원문 (JSONB) ────────────────────────────────────────────────────
def test_store_raw_skips_identical_and_masks_key(conn, pg_db):
    body = {"condition": [{"p_cert_key": "SECRET"}], "data": {"error_code": "000", "item": [_item()]}}
    assert upsert.store_raw(conn, DAY, "소매", "200", body) is True
    assert upsert.store_raw(conn, DAY, "소매", "200", body) is False         # 같으면 안 쌓음
    changed = {**body, "data": {"error_code": "000", "item": [_item(dpr1="1")]}}
    assert upsert.store_raw(conn, DAY, "소매", "200", changed) is True       # 바뀌면 쌓음
    conn.commit()
    rows = pg_db.execute("SELECT BODY, ITEM_COUNT FROM TBL_API_RAW ORDER BY RAW_NO").fetchall()
    assert len(rows) == 2
    assert rows[0][0]["condition"][0]["p_cert_key"] == "***"                 # JSONB 로 저장, 키는 가림
    assert rows[0][1] == 1


# ── 수집 이력 · 점검 ─────────────────────────────────────────────────────
def test_write_log_and_check_summary(conn):
    upsert.write_log(conn, DAY, "소매", None, "OK", 183, 183)
    upsert.write_log(conn, DAY, "도매", None, "NO_DATA", message="주말")
    upsert.write_log(conn, DAY, "소매", "200", "OK", 50, 50)                # 부류행은 점검 대상 아님
    found = check.fetch_summaries(conn, [DAY])
    assert found == {(DAY, "소매"): ("OK", 183, 183, None),
                     (DAY, "도매"): ("NO_DATA", 0, 0, "주말")}


def test_write_log_failure_does_not_break_connection(conn, pg_db):
    """이력 기록이 실패해도 수집은 계속돼야 한다 — 실패 뒤에도 같은 커넥션을 쓸 수 있어야 한다."""
    upsert.write_log(conn, DAY, "소매", None, "WRONG_STATUS")              # CHECK 에 걸린다
    upsert.write_log(conn, DAY, "소매", None, "OK")
    assert pg_db.execute("SELECT STATUS FROM TBL_FETCH_LOG").fetchall() == [("OK",)]
