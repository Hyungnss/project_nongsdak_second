"""collector/upsert.py — 명령줄 옵션 해석.

작업 스케줄러가 `--days 7` 로 부르므로, 옵션 해석이 틀리면 매일 수집이 엉뚱한 날짜를 받는다.
"""

from datetime import date

import pytest

from collector import kamis, upsert


def test_defaults_today_one_day_all_markets():
    day, days, dry, markets = upsert.parse_args([])
    assert day == date.today().isoformat()
    assert (days, dry, markets) == (1, False, [kamis.RETAIL, kamis.WHOLESALE])


def test_days_value_is_not_taken_as_date():
    """`--days 3` 의 '3' 이 날짜 인자로 새면 안 된다 (예전에 실제로 있던 버그)."""
    day, days, _, _ = upsert.parse_args(["2026-11-17", "--days", "3"])
    assert (day, days) == ("2026-11-17", 3)


@pytest.mark.parametrize("argv", [["--days=7"], ["--days", "7"]])
def test_days_both_forms(argv):
    assert upsert.parse_args(argv)[1] == 7


def test_market_and_dry_run():
    _, _, dry, markets = upsert.parse_args(["--market", "wholesale", "--dry-run"])
    assert dry is True and markets == [kamis.WHOLESALE]


@pytest.mark.parametrize(
    "argv",
    [
        ["--days", "0"],               # 1 이상이어야 한다
        ["--days", "abc"],
        ["--days"],                    # 값이 빠짐
        ["--market", "foo"],           # 없는 시장
        ["--nope"],                    # 모르는 옵션
        ["2026-11-17", "2026-11-18"],  # 날짜 두 개
        ["2026/11/17"],                # 날짜 형식
    ],
)
def test_bad_arguments_stop_with_message(argv):
    with pytest.raises(SystemExit):
        upsert.parse_args(argv)


def test_target_days_newest_first():
    assert upsert.target_days("2026-11-17", 3) == ["2026-11-17", "2026-11-16", "2026-11-15"]
