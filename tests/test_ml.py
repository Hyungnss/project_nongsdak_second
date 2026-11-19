"""ml/ — 목표일 규칙 · 기준선 · 특성 · 지표. 핵심은 '미래 값이 예측에 새지 않는가' 다.

미래 가격을 일부러 크게 바꿔도 기준일의 기준선 예측 · 특성이 그대로인지 본다 (누수 방지).
DB 없이 가짜 시계열로 돈다. lightgbm 은 쓰지 않는다 (CI 에는 ml 그룹이 없다).
"""

import numpy as np
import pandas as pd
import pytest

from ml import backtest, baselines, features
from ml.dataset import Series, make_samples, value_near


def _series(sid="211/03/상품", start="2022-01-03", years=3, seed=0, item="211"):
    """평일만 조사하는 가짜 시계열. 계절 모양 + 잡음."""
    days = np.arange(np.datetime64(start), np.datetime64(start) + 365 * years, dtype="datetime64[D]")
    days = days[((days.astype(int) + 3) % 7) < 5]                 # 월~금
    doy = (days - days.astype("datetime64[Y]")).astype(int)
    rng = np.random.default_rng(seed)
    p = 2000 * (1 + 0.3 * np.sin(2 * np.pi * doy / 365)) * np.exp(rng.normal(0, 0.02, len(days)))
    return Series(sid=sid, item_code=item, kind_code="03", rank_name="상품", category_code="200",
                  name="배추", dates=days, prices=p.round(), normals=np.full(len(days), 2000.0))


def _copy(s, prices):
    return Series(**{**s.__dict__, "prices": prices})


# ── 목표일 ────────────────────────────────────────────────────────────────
def test_target_is_first_survey_day_within_tolerance():
    d = np.array(["2026-11-02", "2026-11-03", "2026-11-09", "2026-11-20"], dtype="datetime64[D]")
    s = Series("x", "1", "1", "상품", "200", "x", d, np.array([1.0, 2, 3, 4]), np.full(4, np.nan))
    smp = make_samples([s], horizons=(7,), tol=3)
    # 11-02 +7 = 11-09 (있음) · 11-03 +7 = 11-10 → 11-13 까지 없음 → 뺀다 · 11-09 +7 = 11-16 → 11-19 까지 없음
    assert smp[["origin", "target_date", "y"]].values.tolist() == [
        [np.datetime64("2026-11-02"), np.datetime64("2026-11-09"), 3.0]]
    smp = make_samples([s], horizons=(7,), tol=4)
    assert len(smp) == 2 and smp.target_date.iloc[1] == np.datetime64("2026-11-20")


def test_value_near_never_reads_after_upto():
    d = np.array(["2026-01-01", "2026-01-02", "2026-01-05"], dtype="datetime64[D]")
    s = Series("x", "1", "1", "상품", "200", "x", d, np.array([10.0, 20, 50]), np.full(3, np.nan))
    when = np.array(["2026-01-04"], dtype="datetime64[D]")
    assert value_near(s, when, tol=3)[0] == 50                   # 가장 가까운 날 (01-05)
    assert value_near(s, when, tol=3, upto=np.array([1]))[0] == 20   # 위치 1 까지만 보면 01-02


# ── 누수 방지 ─────────────────────────────────────────────────────────────
@pytest.fixture
def setup():
    s = _series()
    smp = make_samples([s], start="2024-06-01", end="2024-09-30")
    return s, smp


def _future_shocked(s, smp, row):
    """row 의 기준일 다음부터 가격을 10배로 바꾼 시계열과, 그 표본 하나."""
    p = s.prices.copy()
    p[int(smp.loc[row, "i"]) + 1:] *= 10
    one = smp.loc[[row]].reset_index(drop=True)
    return _copy(s, p), one


@pytest.mark.parametrize("name", ["naive", "seasonal_naive", "seasonal_adjusted", "moving_average"])
def test_baselines_do_not_peek(setup, name):
    s, smp = setup
    row = len(smp) // 2
    fn = baselines.BASELINES[name]
    before = fn({s.sid: s}, smp.loc[[row]].reset_index(drop=True))
    shocked, one = _future_shocked(s, smp, row)
    after = fn({s.sid: shocked}, one)
    np.testing.assert_allclose(before, after)


def test_seasonal_profile_uses_only_data_before_refit(setup):
    s, smp = setup
    refits = backtest.refit_dates("2024-06-01", "2024-09-30")
    row = len(smp) - 1
    before = baselines.seasonal_profile({s.sid: s}, smp.loc[[row]].reset_index(drop=True), refits)
    shocked, one = _future_shocked(s, smp, row)
    after = baselines.seasonal_profile({s.sid: shocked}, one, refits)
    assert np.isfinite(before[0])
    np.testing.assert_allclose(before, after)


def test_features_do_not_peek(setup):
    s, smp = setup
    row = len(smp) // 3
    before = features.build({s.sid: s}, smp.loc[[row]].reset_index(drop=True))
    shocked, one = _future_shocked(s, smp, row)
    after = features.build({s.sid: shocked}, one)
    pd.testing.assert_frame_equal(before, after)
    assert before.notna().sum(axis=1).iloc[0] >= 15           # 3년치라 거의 다 채워진다


def test_features_and_target_shapes(setup):
    s, smp = setup
    f = features.build({s.sid: s}, smp)
    assert len(f) == len(smp) and set(features.CATEGORICAL) <= set(f.columns)
    y = features.target(smp)
    np.testing.assert_allclose(np.exp(y) * smp.p0, smp.y)


# ── 기준선 · 지표 ─────────────────────────────────────────────────────────
def test_seasonal_naive_matches_last_year(setup):
    s, smp = setup
    pred = baselines.seasonal_naive({s.sid: s}, smp)
    k = np.flatnonzero(np.isfinite(pred))[0]
    want = value_near(s, np.array([smp.target_date.iloc[k] - np.timedelta64(364, "D")]))[0]
    assert pred[k] == want


def test_backtest_and_metrics_without_lgbm():
    series = [_series(seed=1), _series(sid="111/01/상품", item="111", seed=2)]
    smp = backtest.run(series, "2024-06-01", "2024-10-31",
                       ["naive", "seasonal_naive", "moving_average", "seasonal_profile"], log=lambda *_: None)
    scale = backtest.scales(series, "2024-06-01")
    table = backtest.metrics(smp, scale, ["naive", "seasonal_profile"])
    assert set(table.h) == {7, 14, 28} and (table.series == 2).all()
    naive_rows = table[table.model == "naive"]
    assert naive_rows.DIR.isna().all() and (naive_rows.MASE_mean > 0).all()
    # 사인파 계절성이 뚜렷한 가짜 자료라 계절 프로파일이 4주 뒤에서는 naive 를 이겨야 한다
    m = table.set_index(["model", "h"]).MASE_mean
    assert m["seasonal_profile", 28] < m["naive", 28]


def test_perfect_prediction_has_zero_mase():
    series = [_series(seed=3)]
    smp = backtest.run(series, "2024-06-01", "2024-07-31", ["naive"], log=lambda *_: None)
    smp["pred_naive"] = smp.y
    t = backtest.metrics(smp, backtest.scales(series, "2024-06-01"), ["naive"])
    assert (t.MASE_mean == 0).all() and (t.MAPE == 0).all()


def test_blend_is_half_of_seasonal_change(setup):
    """기준선 blend = naive 와 계절 프로파일의 평균 — 예년 변화의 절반만큼."""
    s, smp = setup
    refits = backtest.refit_dates("2024-06-01", "2024-09-30")
    by = {s.sid: s}
    prof = baselines.seasonal_profile(by, smp, refits)
    got = baselines.blend(by, smp, refits)
    ok = np.isfinite(prof)
    assert ok.any()
    np.testing.assert_allclose(got[ok], (smp.p0.to_numpy()[ok] + prof[ok]) / 2)
    assert baselines.REFERENCE == "blend" and "blend" in baselines.NEEDS_REFITS


def test_blend_does_not_peek(setup):
    s, smp = setup
    refits = backtest.refit_dates("2024-06-01", "2024-09-30")
    row = len(smp) - 1
    before = baselines.blend({s.sid: s}, smp.loc[[row]].reset_index(drop=True), refits)
    shocked, one = _future_shocked(s, smp, row)
    np.testing.assert_allclose(before, baselines.blend({s.sid: shocked}, one, refits))
