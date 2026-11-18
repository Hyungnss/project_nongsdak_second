"""collector/scheduler.py — 컨테이너용 매일 수집 스케줄러의 시각 판단.

서버 · 컨테이너는 UTC 인 경우가 많다. 수집 시각(17:30)과 '오늘' 은 한국 시각이어야 한다.
"""

from datetime import datetime, time

import pytest

import config
from collector import scheduler as s


@pytest.mark.parametrize(
    "now, ran, expected",
    [
        ("2026-11-18 09:00", False, "2026-11-18 17:30"),   # 수집 시각 전 -> 오늘 17:30
        ("2026-11-18 09:00", True,  "2026-11-18 17:30"),
        ("2026-11-18 18:00", False, "2026-11-18 18:00"),   # 지났는데 안 돌았음 -> 지금 바로 (따라잡기)
        ("2026-11-18 18:00", True,  "2026-11-19 17:30"),   # 이미 돌았음 -> 내일
        ("2026-12-31 23:59", True,  "2027-01-01 17:30"),   # 해가 바뀌어도
    ],
)
def test_next_run(now, ran, expected):
    assert s.next_run(datetime.fromisoformat(now), ran) == datetime.fromisoformat(expected)


def test_default_fetch_time_matches_check():
    """스케줄러가 도는 시각과 점검이 '오늘을 볼지' 정하는 시각이 같아야 헛경보가 안 난다."""
    from collector import check
    assert s.FETCH_AT == check.FETCH_TIME == time(17, 30)


def test_now_kst_ignores_machine_timezone(monkeypatch):
    """TZ 를 UTC 로 바꿔도 now_kst 는 한국 시각이다 (UTC + 9시간)."""
    utc = datetime.utcnow()
    diff = (config.now_kst() - utc).total_seconds() / 3600
    assert diff == pytest.approx(9, abs=0.05)


def test_ran_today_reads_fetch_log(pg_db):
    """오늘 수집 시각 이후의 요약 기록이 있어야 '오늘 돌았음' 이다 (실제 DB)."""
    now = datetime(2026, 11, 18, 18, 0)
    assert s.ran_today(now) is False
    pg_db.execute("""INSERT INTO TBL_FETCH_LOG (FETCHED_AT, SURVEY_DATE, MARKET_TYPE, STATUS)
                     VALUES ('2026-11-18 17:20+09', '2026-11-18', '소매', 'OK')""")
    assert s.ran_today(now) is False          # 17:30 전 기록은 오늘 정시 수집이 아니다
    pg_db.execute("""INSERT INTO TBL_FETCH_LOG (FETCHED_AT, SURVEY_DATE, MARKET_TYPE, STATUS)
                     VALUES ('2026-11-18 17:31+09', '2026-11-18', '소매', 'OK')""")
    assert s.ran_today(now) is True
