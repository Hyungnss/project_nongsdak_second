"""collector/quality.py — 단위 변경(갑작스러운 수준 이동)과 시장 변화(점진) · 계절 변동 · 튐을 가르는지."""

import numpy as np

from collector import quality


def _dates(n):
    return np.arange(np.datetime64("2018-01-01"), np.datetime64("2018-01-01") + n, dtype="datetime64[D]")


def test_unit_change_is_abrupt():
    """20kg → 10kg 처럼 하루아침에 반으로 — 1년 창 수준 이동 + 하루 변화 2배 → 단위 변경 의심."""
    p = np.r_[np.full(400, 50000.0), np.full(400, 15000.0)]
    [(day, before, after, ratio, jump)] = quality.level_shifts(_dates(len(p)), p)
    assert day == _dates(800)[400] and before == 50000 and after == 15000
    assert ratio < 1 / quality.SHIFT_RATIO and jump >= quality.ABRUPT_JUMP


def test_gradual_market_move_is_not_unit_change():
    """2년에 걸쳐 4배 오른 생강 같은 흐름 — 수준 이동은 잡히지만 하루 변화가 작다."""
    p = np.r_[np.full(300, 18000.0), np.geomspace(18000, 80000, 300), np.full(300, 80000.0)]
    shifts = quality.level_shifts(_dates(len(p)), p)
    assert shifts and all(jump < quality.ABRUPT_JUMP for *_, jump in shifts)


def test_seasonal_swings_are_ignored():
    """해마다 몇 배씩 오르내리는 시금치 같은 계절 변동은 1년 창에서 잡히지 않는다.

    KAMIS 는 평일에만 조사해서 1년이 약 250 조사일이다 — 주기를 250 관측으로 맞춘다.
    """
    t = np.arange(250 * 4)
    p = 20000 * np.exp(1.2 * np.sin(2 * np.pi * t / 250))          # 연중 약 11배 차이
    assert quality.level_shifts(_dates(len(p)), p) == []


def test_single_day_spike():
    p = np.array([1000.0, 1010, 9000, 1005, 995, 100, 1000])
    got = quality.spikes(_dates(len(p)), p)
    assert [(str(d), x) for d, _, x, _ in got] == [("2018-01-03", 9000.0), ("2018-01-06", 100.0)]


def test_short_series_is_skipped():
    assert quality.level_shifts(_dates(10), np.ones(10)) == []
    assert quality.spikes(_dates(2), np.ones(2)) == []
