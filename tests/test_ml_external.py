"""ml/external.py — 외부 특성(날씨 · 물가)이 미래를 보지 않는지.

  · 날씨: 기준일 t 의 특성은 t-1 까지의 날씨로만. t 이후 날씨를 바꿔도 그대로여야 한다.
  · 평년: 그 해 이전 해들로만. 뒤 해의 날씨를 바꿔도 앞 해의 평년 차이는 그대로여야 한다.
  · 물가: 기준일 17:30 KST 이전에 발표된(AVAILABLE_AT) 달까지만.
  · oracle: 실험용 — 기준일 다음 날 ~ 목표일의 실제 날씨를 정확히 쓰는지.
DB 없이 가짜 조회 함수로 돈다.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from ml import external

KST = timezone(timedelta(hours=9))


def _weather_rows(start="2015-01-01", days=365 * 4, shock_from=None):
    d0 = pd.Timestamp(start)
    rows = []
    for i in range(days):
        d = d0 + pd.Timedelta(days=i)
        ta = 10 + 10 * np.sin(2 * np.pi * d.dayofyear / 365)
        if shock_from is not None and d >= pd.Timestamp(shock_from):
            ta += 30                                     # 미래를 크게 바꾼다
        rows.append({"d": d.date(), "ta": ta, "tmin": ta - 5, "tmax": ta + 5, "rn": 1.0, "ss": 5.0,
                     "frost": 0.0, "heat": 0.0})
    return rows


def _cpi_rows():
    rows = []
    for y in (2017, 2018):
        for m in range(1, 13):
            nxt = datetime(y + (m == 12), m % 12 + 1, 10, tzinfo=KST)          # 다음 달 10일 발표
            for code in ("00", "211", "21112"):
                rows.append({"period": f"{y}{m:02d}", "item_code": code, "v": 100 + m + (y - 2017) * 12,
                             "available_at": nxt})
    return rows


def _ext(shock_from=None):
    def query(sql):
        return _cpi_rows() if "TBL_CPI_MONTHLY" in sql else _weather_rows(shock_from=shock_from)
    return external.External(query)


def _samples(origins, target_days=14, cat="200"):
    o = pd.to_datetime(origins)
    return pd.DataFrame({"origin": o, "target_date": o + pd.Timedelta(days=target_days),
                         "category_code": cat})


def test_weather_uses_only_days_before_origin():
    smp = _samples(["2018-06-15"])
    base = _ext().build(smp, ["weather"])
    shocked = _ext(shock_from="2018-06-15").build(smp, ["weather"])      # 기준일 당일부터 바뀜
    pd.testing.assert_frame_equal(base, shocked)
    assert base.notna().all(axis=None)


def test_climatology_uses_only_earlier_years():
    """2018년 날씨를 바꿔도 2017년의 평년 차이는 그대로 (평년에 뒤 해가 섞이지 않는다)."""
    a = external.anomalies(external.load_weather(lambda _: _weather_rows()))
    b = external.anomalies(external.load_weather(lambda _: _weather_rows(shock_from="2018-01-01")))
    pd.testing.assert_series_equal(a.ta[:"2017-12-31"], b.ta[:"2017-12-31"])
    assert a.ta[:"2015-12-31"].isna().all()                              # 첫 해는 비교할 앞선 해가 없다


def test_cpi_only_published_months():
    """2018-03-09 에는 1월분까지(2월분은 3월 10일 발표), 3월 10일 18시에는 2월분까지."""
    ext = _ext()
    f = ext.build(_samples(["2018-03-09", "2018-03-10"]), ["cpi"])
    jan, feb = 100 + 1 + 12, 100 + 2 + 12                                 # 2018-01, 2018-02 값
    assert np.isclose(f.cpi_cat_mom.iloc[0], jan / (100 + 12) - 1)         # 2018-01 / 2017-12 (=112)
    assert np.isclose(f.cpi_cat_yoy.iloc[0], jan / (100 + 1) - 1)
    assert np.isclose(f.cpi_cat_yoy.iloc[1], feb / (100 + 2) - 1)
    assert np.isclose(f.cpi_all_yoy.iloc[1], feb / (100 + 2) - 1)


def test_cpi_category_without_series_is_nan():
    f = _ext().build(_samples(["2018-06-01"], cat="600"), ["cpi"])     # 수산 계열(2113)이 없는 가짜 자료
    assert np.isnan(f.cpi_cat_yoy.iloc[0]) and np.isfinite(f.cpi_all_yoy.iloc[0])


def test_oracle_is_mean_future_anomaly():
    """oracle 은 기준일 다음 날 ~ 목표일의 실제 평년 차이 평균 — 미래를 바꾸면 바뀌어야 한다 (실험용)."""
    smp = _samples(["2018-06-15"], target_days=7)
    a = _ext().build(smp, ["oracle"])
    b = _ext(shock_from="2018-06-16").build(smp, ["oracle"])
    assert np.isclose(b.oracle_ta_anom.iloc[0] - a.oracle_ta_anom.iloc[0], 30.0)


def test_feature_sets():
    assert external.FEATURE_SETS["lgbm"] == []
    assert "oracle" not in external.FEATURE_SETS["lgbm_ext"]                # 서비스용 조합에 미래 정보 없음
    assert "oracle" in external.FEATURE_SETS["lgbm_oracle"]


def _ext_sido(shock_from=None):
    def query(sql):
        if "TBL_CPI_MONTHLY" in sql:
            return _cpi_rows()
        rows = _weather_rows(shock_from=shock_from)
        if "SIDO" in sql:                                    # 시도별 — 강원 · 제주 두 곳
            return [{**r, "sido": s} for s in ("강원", "제주") for r in rows]
        return rows
    return external.External(query)


def test_region_weather_uses_only_days_before_origin():
    smp = _samples(["2018-06-15"]).assign(sid=["211/02/상품"])        # 고랭지 배추 → 강원
    base = _ext_sido().build(smp, ["region"])
    shocked = _ext_sido(shock_from="2018-06-15").build(smp, ["region"])
    pd.testing.assert_frame_equal(base, shocked)
    assert base.notna().all(axis=None) and "rg_ta_anom_180" in base


def test_region_unknown_item_is_empty_and_mapping_prefers_kind():
    smp = _samples(["2018-06-15"]).assign(sid=["418/02/상품"])        # 바나나(수입) — 산지 없음
    assert _ext_sido().build(smp, ["region"]).empty or _ext_sido().build(smp, ["region"]).isna().all(axis=None)
    assert external.regions_of("211", "02") == ["강원"] and external.regions_of("211", "06") == ["전남"]
    assert external.regions_of("415", "01") == ["제주"] and external.regions_of("418", "02") is None
    assert "region_oracle" not in external.FEATURE_SETS["lgbm_region"]
