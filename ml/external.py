"""외부 특성 — 날씨(전국 평균) · 물가(ECOS). base 모델(가격만)에 더해 효과를 본다 (③-1).

모든 값은 '기준일에 알 수 있었던 것' 만 쓴다.
  · 날씨: 일자료는 다음 날 오전에 나온다 → 기준일 t 에는 t-1 까지의 날씨.
  · 평년(날씨의 '보통'): 그 해 이전 해들로만 만든다. 2018년을 볼 때 2020년 날씨가 평년에 섞이지 않게.
  · 물가: AVAILABLE_AT(발표된 뒤 처음 알 수 있던 시각) <= 기준일 17:30 인 달까지만.

'완벽한 예보' (oracle) 는 실험용이다 — 기준일 다음 날부터 목표일까지의 **실제** 날씨라 미래 정보다.
서비스에는 절대 쓰지 않는다. '예보가 완벽하다면 최대 얼마나 좋아지나' 라는 상한선을 재는 데만 쓴다.

날씨는 기온 자체가 아니라 '평년과의 차이' 를 쓴다. 모델은 이미 계절(11월엔 춥다)을 알고 있어서
기온을 그대로 주면 같은 정보를 두 번 주는 셈이다. 가격을 흔드는 건 '올해 11월이 유난히 춥다' 쪽이다.
"""

import numpy as np
import pandas as pd

WEATHER_VARS = ["ta", "tmin", "tmax", "rn", "ss"]
CLIMO_SMOOTH = 7                 # 평년은 연중 일자 ±7일로 부드럽게
FETCH_HOUR = (17, 30)            # 기준일의 예측 시각 (가격 수집 뒤)

# 품목 부류 → 물가 계열 (ECOS 901Y010)
CPI_BY_CATEGORY = {"100": "21111", "200": "21112", "300": "2111", "400": "21113", "500": "2112", "600": "2113"}
CPI_COMMON = {"00": "cpi_all", "211": "cpi_agri"}

FEATURE_SETS = {
    "lgbm": [],                                    # A — 가격만
    "lgbm_ext": ["weather", "cpi"],                 # B — + 지난 날씨 · 물가 (서비스에 쓸 수 있다)
    "lgbm_oracle": ["weather", "cpi", "oracle"],    # C — + 미래 실제 날씨 (실험용 상한선)
    "lgbm_region": ["region"],                      # D — + 산지(시도) 날씨, 긴 시차 (물가 없이 날씨 효과만)
    "lgbm_region_oracle": ["region", "region_oracle"],   # E — + 산지의 미래 실제 날씨 (실험용)
}

# 품목(·품종) → 주산지 시도. 2026-11-20 일반적으로 알려진 주산지로 정한 **가정**이다
# (통계청 시도별 생산량 등으로 확인할 것). 수입 과일 · 버섯(실내 재배)은 날씨와 무관해 넣지 않는다.
# 키는 품목코드 또는 (품목코드, 품종코드). 품종 키가 먼저다 (배추 · 무는 철마다 산지가 다르다).
REGIONS = {
    ("211", "01"): ["전남", "충북"], ("211", "02"): ["강원"], ("211", "03"): ["충북", "강원"],
    ("211", "06"): ["전남"],
    ("231", "01"): ["전남", "충남"], ("231", "02"): ["강원"], ("231", "03"): ["강원", "충남"],
    ("231", "06"): ["제주"],
    "212": ["제주", "강원"], "213": ["전남", "경남"], "214": ["경기"], "215": ["경기"],
    "221": ["충북", "경남", "전북"], "222": ["경북"], "223": ["충남", "경남"], "224": ["경남", "강원"],
    "225": ["충남", "경남"], "226": ["충남", "경남"], "232": ["제주"], "233": ["경기"],
    "241": ["경북", "충북"], "242": ["경남", "강원"], "243": ["경북", "충북"], "244": ["경북", "전남", "경남"],
    "245": ["전남", "경남"], "246": ["전남"], "251": ["경기"], "252": ["경북"], "253": ["충남"],
    "254": ["경기"], "255": ["강원", "경남"], "256": ["경남", "전남"], "257": ["충북", "전남"],
    "258": ["경북", "전남", "경남"], "279": ["강원"], "280": ["강원", "제주"], "422": ["충남", "경남"],
    "111": ["전남", "충남", "전북"], "112": ["전남", "전북"], "115": ["전남"], "121": ["전북", "전남"],
    "141": ["경북", "강원"], "142": ["강원", "경북"], "151": ["전남", "경기"], "152": ["강원"],
    "411": ["경북"], "412": ["전남", "충남"], "413": ["경북", "충북"], "414": ["경북", "충북"],
    "415": ["제주"], "416": ["경남"], "419": ["전남", "경남"], "437": ["전남", "경남"],
}


# ── 날씨 ──────────────────────────────────────────────────────────────────
def load_weather(query):
    """관측소 평균 → 날짜별 전국 날씨 (빈 날 없이 이어진 일별 표).

    평균기온이 최저~최고 밖인 행(원자료 오류 — 품질 점검의 '범위 밖 값')은 그 평균기온을 빼고 계산한다.
    """
    rows = query("""
        SELECT OBS_DATE AS d,
               AVG(CASE WHEN AVG_TA BETWEEN MIN_TA - 0.5 AND MAX_TA + 0.5 THEN AVG_TA END)::float8 AS ta,
               AVG(MIN_TA)::float8 AS tmin, AVG(MAX_TA)::float8 AS tmax,
               AVG(SUM_RN)::float8 AS rn, AVG(SUM_SS_HR)::float8 AS ss,
               AVG(CASE WHEN MIN_TA < 0 THEN 1.0 ELSE 0.0 END)::float8 AS frost,
               AVG(CASE WHEN MAX_TA >= 33 THEN 1.0 ELSE 0.0 END)::float8 AS heat
        FROM   TBL_WEATHER_DAILY
        GROUP  BY OBS_DATE ORDER BY OBS_DATE
    """)
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df["d"])
    full = pd.date_range(df.d.min(), df.d.max(), freq="D")
    return df.set_index("d").reindex(full)


def _doy(idx):
    doy = idx.dayofyear.to_numpy() - 1
    leap = idx.is_leap_year
    doy = np.where(leap & (doy >= 59), doy - 1, doy)
    return np.minimum(doy, 364)


def anomalies(w, cols=WEATHER_VARS):
    """평년(그 해 이전 해들의 같은 연중 일자 ±7일 평균)과의 차이. 앞선 해가 없으면 NaN."""
    years = w.index.year.to_numpy()
    doy = _doy(w.index)
    ys = np.unique(years)
    out = pd.DataFrame(index=w.index)
    k = np.ones(2 * CLIMO_SMOOTH + 1)
    for c in cols:
        v = w[c].to_numpy()
        acc = np.zeros((len(ys), 365))
        cnt = np.zeros((len(ys), 365))
        for n, y in enumerate(ys):
            m = (years == y) & np.isfinite(v)
            np.add.at(acc[n], doy[m], v[m])
            np.add.at(cnt[n], doy[m], 1)
        # 해마다 앞선 해들의 누적 → 연중 일자 ±7 일로 부드럽게 (원형)
        cacc, ccnt = np.cumsum(acc, 0), np.cumsum(cnt, 0)
        climo = np.full((len(ys), 365), np.nan)
        for n in range(1, len(ys)):
            a = np.convolve(np.r_[cacc[n - 1, -CLIMO_SMOOTH:], cacc[n - 1], cacc[n - 1, :CLIMO_SMOOTH]], k, "valid")
            b = np.convolve(np.r_[ccnt[n - 1, -CLIMO_SMOOTH:], ccnt[n - 1], ccnt[n - 1, :CLIMO_SMOOTH]], k, "valid")
            with np.errstate(invalid="ignore", divide="ignore"):
                climo[n] = a / b
        row = np.searchsorted(ys, years)
        out[c] = v - climo[row, doy]
    return out


def weather_table(w):
    """기준일마다 붙일 날씨 특성 — 전날까지의 최근 7 · 30 · 90일 평년 차이, 서리 · 폭염 비율.

    돌려주는 표의 행 = 기준일 (그날 값은 그 전날까지로 계산했다).
    """
    an = anomalies(w)
    f = pd.DataFrame(index=w.index)
    for d in (7, 30, 90):
        f[f"wx_ta_anom_{d}"] = an.ta.rolling(d, min_periods=d // 2).mean()
    f["wx_tmin_anom_30"] = an.tmin.rolling(30, min_periods=15).mean()
    f["wx_tmax_anom_30"] = an.tmax.rolling(30, min_periods=15).mean()
    for d in (7, 30):
        f[f"wx_rn_anom_{d}"] = an.rn.rolling(d, min_periods=d // 2).sum()
    f["wx_ss_anom_30"] = an.ss.rolling(30, min_periods=15).mean()
    f["wx_frost_30"] = w.frost.rolling(30, min_periods=15).mean()
    f["wx_heat_30"] = w.heat.rolling(30, min_periods=15).mean()
    return f.shift(1)            # t 행 = t-1 까지 (일자료는 다음 날 나온다)


def oracle_table(w):
    """실험용 — 누적합. (기준일 다음 날 ~ 목표일) 의 실제 평균기온 차이 · 강수 차이를 구할 때 쓴다."""
    an = anomalies(w, ["ta", "rn"]).fillna(0.0)
    return an.cumsum()


def load_weather_by_sido(query):
    """관측소를 시도로 묶은 일별 날씨 {시도: 표}. 평균기온 원자료 오류는 뺀다 (load_weather 와 같다)."""
    rows = query("""
        SELECT s.SIDO AS sido, w.OBS_DATE AS d,
               AVG(CASE WHEN w.AVG_TA BETWEEN w.MIN_TA - 0.5 AND w.MAX_TA + 0.5 THEN w.AVG_TA END)::float8 AS ta,
               AVG(w.MIN_TA)::float8 AS tmin, AVG(w.MAX_TA)::float8 AS tmax,
               AVG(w.SUM_RN)::float8 AS rn, AVG(w.SUM_SS_HR)::float8 AS ss,
               AVG(CASE WHEN w.MIN_TA < 0 THEN 1.0 ELSE 0.0 END)::float8 AS frost,
               AVG(CASE WHEN w.MAX_TA >= 33 THEN 1.0 ELSE 0.0 END)::float8 AS heat
        FROM   TBL_WEATHER_DAILY w JOIN TBL_WEATHER_STATION s USING (STN_ID)
        GROUP  BY 1, 2 ORDER BY 1, 2
    """)
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df["d"])
    full = pd.date_range(df.d.min(), df.d.max(), freq="D")
    return {sido: g.drop(columns="sido").set_index("d").reindex(full) for sido, g in df.groupby("sido")}


def region_table(w):
    """산지 날씨 특성 — 긴 시차까지 (날씨는 몇 달 뒤 수확량에 영향을 준다). t 행 = t-1 까지."""
    an = anomalies(w)
    f = pd.DataFrame(index=w.index)
    for d in (30, 90, 180):
        f[f"rg_ta_anom_{d}"] = an.ta.rolling(d, min_periods=d // 2).mean()
        f[f"rg_rn_anom_{d}"] = an.rn.rolling(d, min_periods=d // 2).sum()
    f["rg_tmin_anom_60"] = an.tmin.rolling(60, min_periods=30).mean()
    f["rg_tmax_anom_60"] = an.tmax.rolling(60, min_periods=30).mean()
    f["rg_ss_anom_60"] = an.ss.rolling(60, min_periods=30).mean()
    f["rg_frost_60"] = w.frost.rolling(60, min_periods=30).mean()
    f["rg_heat_60"] = w.heat.rolling(60, min_periods=30).mean()
    return f.shift(1)


def regions_of(item_code, kind_code):
    return REGIONS.get((item_code, kind_code)) or REGIONS.get(item_code)


# ── 물가 ──────────────────────────────────────────────────────────────────
def load_cpi(query):
    rows = query("""SELECT PERIOD, ITEM_CODE, VALUE::float8 AS v, AVAILABLE_AT
                    FROM TBL_CPI_MONTHLY WHERE STAT_CODE = '901Y010' ORDER BY ITEM_CODE, PERIOD""")
    df = pd.DataFrame(rows)
    out = {}
    for code, g in df.groupby("item_code"):
        g = g.sort_values("period").reset_index(drop=True)
        g["yoy"] = g.v / g.v.shift(12) - 1
        g["mom"] = g.v / g.v.shift(1) - 1
        g["avail"] = pd.to_datetime(g.available_at, utc=True)
        out[code] = g[["period", "yoy", "mom", "avail"]]
    return out


def _asof(cpi_series, when_ns):
    """기준 시각(UTC, 나노초 정수)마다 그때 발표된 가장 최근 달의 (yoy, mom). 없으면 NaN."""
    g = cpi_series.sort_values("avail")
    idx = np.searchsorted(g.avail.astype("int64").to_numpy(), when_ns, side="right") - 1
    yoy = np.where(idx >= 0, g.yoy.to_numpy()[np.maximum(idx, 0)], np.nan)
    mom = np.where(idx >= 0, g.mom.to_numpy()[np.maximum(idx, 0)], np.nan)
    return yoy, mom


# ── 붙이기 ────────────────────────────────────────────────────────────────
class External:
    """DB 에서 한 번 읽어 두고, 표본마다 외부 특성을 붙인다."""

    def __init__(self, query):
        self.w = load_weather(query)
        self.wx = weather_table(self.w)
        self.orc = oracle_table(self.w)
        self.cpi = load_cpi(query)
        self._query = query
        self._sido = None
        self._region_cache = {}

    def _region(self, regions):
        """시도 목록 → (특성 표, 실험용 누적합 표). 여러 시도면 시도별 특성의 평균."""
        key = tuple(regions)
        if key not in self._region_cache:
            if self._sido is None:
                self._sido = load_weather_by_sido(self._query)
            have = [r for r in regions if r in self._sido]
            feats = [region_table(self._sido[r]) for r in have]
            orcs = [oracle_table(self._sido[r]) for r in have]
            self._region_cache[key] = (sum(feats) / len(feats), sum(orcs) / len(orcs)) if have else (None, None)
        return self._region_cache[key]

    def build(self, samples, parts):
        out = pd.DataFrame(index=samples.index)
        if not parts:
            return out
        origin = pd.to_datetime(samples.origin).dt.normalize()
        if "weather" in parts:
            got = self.wx.reindex(origin.to_numpy())
            for c in got.columns:
                out[c] = got[c].to_numpy()
        if "cpi" in parts:
            # 기준일 17:30 KST 를 UTC 로 — AVAILABLE_AT 과 비교
            when = (origin + pd.Timedelta(hours=FETCH_HOUR[0], minutes=FETCH_HOUR[1])
                    - pd.Timedelta(hours=9)).dt.tz_localize("UTC").astype("int64").to_numpy()
            for code, name in CPI_COMMON.items():
                if code in self.cpi:
                    out[f"{name}_yoy"], out[f"{name}_mom"] = _asof(self.cpi[code], when)
            yoy = np.full(len(samples), np.nan)
            mom = np.full(len(samples), np.nan)
            cat = samples.category_code.astype(str).to_numpy()
            for c, code in CPI_BY_CATEGORY.items():
                k = cat == c
                if k.any() and code in self.cpi:
                    yoy[k], mom[k] = _asof(self.cpi[code], when[k])
            out["cpi_cat_yoy"], out["cpi_cat_mom"] = yoy, mom
        if "region" in parts or "region_oracle" in parts:
            sid = samples.sid.astype(str).str.split("/")
            item, kind = sid.str[0].to_numpy(), sid.str[1].to_numpy()
            target = pd.to_datetime(samples.target_date).dt.normalize()
            groups = {}
            for n_, (i_, k_) in enumerate(zip(item, kind)):
                rg = regions_of(i_, k_)
                if rg:
                    groups.setdefault(tuple(rg), []).append(n_)
            cols = {}
            for rg, pos in groups.items():
                feat, orc = self._region(list(rg))
                if feat is None:
                    continue
                pos = np.asarray(pos)
                o_ = origin.to_numpy()[pos]
                if "region" in parts:
                    got = feat.reindex(o_)
                    for c in got.columns:
                        cols.setdefault(c, np.full(len(samples), np.nan))[pos] = got[c].to_numpy()
                if "region_oracle" in parts:
                    a, b = orc.reindex(o_), orc.reindex(target.to_numpy()[pos])
                    days = (target.to_numpy()[pos] - o_).astype("timedelta64[D]").astype(float)
                    cols.setdefault("rg_oracle_ta_anom", np.full(len(samples), np.nan))[pos] =                         (b.ta.to_numpy() - a.ta.to_numpy()) / days
                    cols.setdefault("rg_oracle_rn_anom", np.full(len(samples), np.nan))[pos] =                         b.rn.to_numpy() - a.rn.to_numpy()
            for c, v in cols.items():
                out[c] = v
        if "oracle" in parts:
            target = pd.to_datetime(samples.target_date).dt.normalize()
            a = self.orc.reindex(origin.to_numpy())
            b = self.orc.reindex(target.to_numpy())
            days = (target - origin).dt.days.to_numpy().astype(float)
            out["oracle_ta_anom"] = (b.ta.to_numpy() - a.ta.to_numpy()) / days
            out["oracle_rn_anom"] = b.rn.to_numpy() - a.rn.to_numpy()
        return out


def db_query():
    """ml 이 쓰는 DB 조회 함수 (backend/db.py 의 _query)."""
    import sys  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "backend"))
    import db  # noqa: PLC0415
    return lambda sql: db._query(sql)

