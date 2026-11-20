"""가격 백필 (collector/backfill.py) — 응답 해석 · 구간 나누기 · 덮어쓰지 않기 · 이어받기."""

from datetime import date

import pytest

from collector import backfill
from tests.conftest import add_price


def _body(rows, code="000"):
    return {"condition": [], "data": {"error_code": code, "item": rows}}


def _row(county, regday, price, yyyy="2024"):
    return {"itemname": None, "kindname": None, "countyname": county, "marketname": None,
            "yyyy": yyyy, "regday": regday, "price": price}


def test_chunks_split_by_calendar_year():
    assert backfill.chunks(date(2023, 11, 5), date(2025, 2, 1)) == [
        (date(2023, 11, 5), date(2023, 12, 31)),
        (date(2024, 1, 1), date(2024, 12, 31)),
        (date(2025, 1, 1), date(2025, 2, 1)),
    ]
    assert backfill.chunks(date(2024, 3, 1), date(2024, 3, 1)) == [(date(2024, 3, 1), date(2024, 3, 1))]


def test_parse_uses_national_average_and_normal_only():
    body = _body([
        _row("평균", "01/02", "2,712"), _row("평년", "01/02", "3,100"),
        _row("서울", "01/02", "2,500"),                      # 지역 행은 쓰지 않는다
        _row("평균", "01/03", "-"), _row("평년", "01/03", "3,000"),   # 평균 없는 날은 뺀다
        _row("평균", "01/04", "1,000"),                       # 평년 없는 날
        _row("평균", "bad", "10"),
    ])
    assert backfill.parse_period(body) == {
        date(2024, 1, 2): (2712.0, 3100.0),
        date(2024, 1, 4): (1000.0, None),
    }
    assert backfill.parse_period({"data": []}) == {}          # 무자료는 data 가 리스트
    assert backfill.parse_period(_body(_row("평균", "12/31", "5"))) == {date(2024, 12, 31): (5.0, None)}


@pytest.fixture
def conn(pg_db):
    pg_db.execute("TRUNCATE TBL_BACKFILL_JOB")
    return pg_db


def _combo(conn):
    add_price(conn, "2026-11-18", price=2390.0)
    conn.execute("UPDATE TBL_DAILY_PRICE SET RANK_CODE = '04'")
    [c] = backfill.combos(conn, ["소매"])
    return c


def test_backfill_never_overwrites_and_marks_source(conn):
    c = _combo(conn)
    assert c["item_code"] == "211" and c["rank_code"] == "04" and c["unit"] == "1포기"
    prices = {date(2026, 11, 17): (2434.0, 3300.0), date(2026, 11, 18): (9999.0, None)}
    assert backfill.save_chunk(conn, c, date(2026, 1, 1), date(2026, 12, 31), prices) == 1

    rows = conn.execute("""SELECT SURVEY_DATE, PRICE_TODAY, PRICE_NORMAL, DATA_SOURCE, KIND_NAME
                           FROM TBL_DAILY_PRICE ORDER BY 1""").fetchall()
    assert rows == [
        (date(2026, 11, 17), 2434.0, 3300.0, "kamis_period", "가을(1포기)"),
        (date(2026, 11, 18), 2390.0, None, None, "가을(1포기)"),      # 기존 행 그대로
    ]


def test_resume_skips_finished_chunks_and_retries_errors(conn, monkeypatch):
    _combo(conn)
    calls = []

    def fake_call(combo, s, e):
        calls.append(s.year)
        if s.year == 2024 and calls.count(2024) == 1:
            raise RuntimeError("일시 오류")
        return _body([_row("평균", "06/01", "1,500", yyyy=str(s.year))])

    monkeypatch.setattr(backfill, "call_period", fake_call)
    monkeypatch.setattr(backfill.loader, "connect", lambda: _NoClose(conn))
    monkeypatch.setattr(backfill.config, "require_kamis", lambda: ("k", "i"))

    with pytest.raises(SystemExit):              # 오류 구간이 있으면 종료 코드 1
        backfill.main(["--start", "2023-01-01", "--end", "2024-12-31", "--market", "retail", "--sleep", "0"])
    assert calls == [2023, 2024]
    status = dict(conn.execute("SELECT EXTRACT(YEAR FROM CHUNK_START)::int, STATUS FROM TBL_BACKFILL_JOB").fetchall())
    assert status == {2023: "OK", 2024: "ERROR"}

    backfill.main(["--start", "2023-01-01", "--end", "2024-12-31", "--market", "retail", "--sleep", "0"])
    assert calls == [2023, 2024, 2024]          # 끝난 2023 은 다시 부르지 않는다
    assert conn.execute("SELECT COUNT(*) FROM TBL_DAILY_PRICE WHERE DATA_SOURCE = 'kamis_period'").fetchone()[0] == 2


class _NoClose:
    """시험 커넥션을 main() 이 닫지 않게 감싼다."""

    def __init__(self, conn):
        self._c = conn

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._c, name)

    def __setattr__(self, name, value):
        if name == "_c":
            object.__setattr__(self, name, value)
        else:
            setattr(self._c, name, value)
