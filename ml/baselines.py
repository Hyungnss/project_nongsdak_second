"""기준선 — 학습 없이 정해진 규칙으로 예측한다. '이것도 못 이기면 모델이 필요 없다' 는 바닥선.

모든 함수는 (series_by_sid, samples) 를 받아 표본마다 예측값 배열을 돌려준다.
쓰는 값은 전부 기준일 위치 i 이하(그날까지 아는 값)다 — tests/test_ml.py 가 미래 값을 바꿔 확인한다.
값을 못 구하면(작년 자료 없음 등) NaN 이다. backtest 가 NaN 을 naive 로 메우고 그 비율을 함께 보고한다.
"""

import numpy as np

from ml.dataset import TOLERANCE, value_near

YEAR = np.timedelta64(364, "D")       # 52주 — 같은 요일끼리 맞춘다
MA_WINDOW = 20                        # 최근 20 조사일 ≈ 4주
PROFILE_SMOOTH = 7                    # 계절 프로파일은 연중 일자 ±7일로 부드럽게
PROFILE_MIN_YEARS = 2


def _by_series(series, samples, fn):
    out = np.full(len(samples), np.nan)
    for sid, g in samples.groupby("sid", sort=False):
        out[g.index.to_numpy()] = fn(series[sid], g)
    return out


def naive(series, samples):
    """기준일 가격 그대로."""
    return samples.p0.to_numpy(dtype=float)


def seasonal_naive(series, samples):
    """목표일 364일 전(같은 요일) 가격."""
    return _by_series(series, samples, lambda s, g: value_near(
        s, g.target_date.to_numpy() - YEAR, TOLERANCE, upto=g.i.to_numpy()))


def seasonal_adjusted(series, samples):
    """기준일 가격 × (작년 목표일 / 작년 기준일). 작년의 '변화 모양' 만 빌려 온다."""
    def f(s, g):
        i = g.i.to_numpy()
        a = value_near(s, g.target_date.to_numpy() - YEAR, TOLERANCE, upto=i)
        b = value_near(s, g.origin.to_numpy() - YEAR, TOLERANCE, upto=i)
        return g.p0.to_numpy() * a / b
    return _by_series(series, samples, f)


def moving_average(series, samples):
    """최근 20 조사일 평균 (기준일 포함)."""
    def f(s, g):
        c = np.concatenate([[0.0], np.cumsum(s.prices)])
        i = g.i.to_numpy()
        lo = np.maximum(i + 1 - MA_WINDOW, 0)
        return (c[i + 1] - c[lo]) / (i + 1 - lo)
    return _by_series(series, samples, f)


def _doy(dates):
    """연중 일자 0~364 (윤년 2/29 는 2/28 과 같게)."""
    dates = np.asarray(dates, dtype="datetime64[D]")
    y = dates.astype("datetime64[Y]")
    doy = (dates - y).astype(int)
    leap = ((y.astype(int) + 1970) % 4 == 0)
    doy = np.where(leap & (doy >= 59), doy - 1, doy)
    return np.minimum(doy, 364)


def season_profile(s, cutoff):
    """cutoff 이전 자료만으로 연중 일자별 '평소 대비 비율' 을 만든다. 해가 모자라면 None.

    해마다 그 해 평균으로 나눈 비율을 일자별로 모아 평균하고, ±7일로 부드럽게 한다(원형).
    """
    cutoff = np.datetime64(cutoff, "D")
    m = s.dates < cutoff
    d, p = s.dates[m], s.prices[m]
    if not len(d):
        return None
    years = d.astype("datetime64[Y]")
    acc, cnt, n_years = np.zeros(365), np.zeros(365), 0
    for y in np.unique(years):
        k = years == y
        if k.sum() < 100:             # 한 해에 100 조사일은 있어야 그 해 평균을 믿는다
            continue
        n_years += 1
        doy = _doy(d[k])
        np.add.at(acc, doy, p[k] / p[k].mean())
        np.add.at(cnt, doy, 1)
    if n_years < PROFILE_MIN_YEARS:
        return None
    w = PROFILE_SMOOTH
    kernel = np.ones(2 * w + 1)
    a = np.convolve(np.concatenate([acc[-w:], acc, acc[:w]]), kernel, "valid")
    c = np.convolve(np.concatenate([cnt[-w:], cnt, cnt[:w]]), kernel, "valid")
    with np.errstate(invalid="ignore", divide="ignore"):
        prof = a / c
    return prof


def seasonal_profile(series, samples, refit_dates):
    """기준일 가격 × 프로파일(목표일) / 프로파일(기준일). 프로파일은 4주마다 그 이전 자료로 다시 만든다.

    refit_dates: 오름차순. 기준일 t 에는 t 이하인 가장 늦은 refit 날짜의 프로파일을 쓴다.
    """
    refit = np.asarray(refit_dates, dtype="datetime64[D]")

    def f(s, g):
        out = np.full(len(g), np.nan)
        origin = g.origin.to_numpy()
        which = np.searchsorted(refit, origin, side="right") - 1
        for r in np.unique(which):
            if r < 0:
                continue
            prof = season_profile(s, refit[r])
            if prof is None:
                continue
            k = which == r
            out[k] = (g.p0.to_numpy()[k] * prof[_doy(g.target_date.to_numpy()[k])]
                      / prof[_doy(origin[k])])
        return out
    return _by_series(series, samples, f)


def blend(series, samples, refit_dates):
    """기준선 (2026-11-19 확정) — naive 와 계절 프로파일의 평균. '예년 계절 변화의 절반만큼 바뀐다'.

      예측 = 기준일 가격 × (1 + 예년 변화율) / 2
      예) 오늘 3,000원, 예년엔 4주 동안 20% 내림 → (3,000 + 2,400) / 2 = 2,700원 (10% 내림)

    도매 백테스트(2024-10 ~ 2026-10)에서 1 · 2 · 4주 모두 가장 좋거나 거의 같았다.
    계절이 뚜렷한 채소 · 과실은 계절 프로파일이, 저장 · 수입 품목(곡물 · 건어물 · 냉동 수산)은 naive 가
    나아서, 둘을 섞으면 어느 쪽에서도 크게 틀리지 않는다. 모델은 이 점수를 넘어야 한다.
    계절 프로파일을 못 구한 표본(과거 2년 미만)은 naive 그대로다.
    """
    p0 = naive(series, samples)
    prof = seasonal_profile(series, samples, refit_dates)
    return np.where(np.isfinite(prof), (p0 + prof) / 2, np.nan)


BASELINES = {
    "naive": naive,
    "seasonal_naive": seasonal_naive,
    "seasonal_adjusted": seasonal_adjusted,
    "moving_average": moving_average,
    "seasonal_profile": seasonal_profile,      # refit_dates 가 필요하다
    "blend": blend,                            # 확정 기준선 · refit_dates 가 필요하다
}
NEEDS_REFITS = {"seasonal_profile", "blend"}
REFERENCE = "blend"                            # 모델이 넘어야 할 기준선
