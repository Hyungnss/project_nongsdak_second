r"""데이터 품질 점검 — 모델에 넣기 전에 가격 · 날씨 · 물가에 이상한 값이 섞였는지 본다.

  uv run python -m collector.quality                     (전부)
  uv run python -m collector.quality --only price --market 도매
  uv run python -m collector.quality --csv               (의심 목록을 logs/quality/*.csv 로도)

무엇을 보나
  가격
    · 수준 이동 : 앞 1년(250 조사일)과 뒤 1년의 중앙값이 2.5배 넘게 다르다 → 단위 변경 · 코드 재사용 의심
                  (예: 같은 품종 코드인데 20kg → 10kg 으로 조사 단위가 바뀐 경우)
                  창을 1년으로 잡는 이유: 한 달 창(20 조사일)으로 보면 시금치 · 상추처럼 해마다 몇 배씩
                  오르내리는 계절 변동이 다 걸린다 (도매 첫 점검에서 121건이 거의 다 그랬다). 1년이면
                  계절이 평균에 묻히고, 한 번 바뀌면 계속 그 수준인 단위 변경만 남는다.
    · 튐        : 하루만 앞뒤 값보다 5배 넘게 높거나 낮다 → 입력 오류 의심
    · 연도별 행 수 : 어느 해가 통째로 비었는지
  날씨
    · 관측소마다 시작일 ~ 마지막 날 사이에 빠진 날
    · 범위 밖 값 (기온 -40~45℃ 밖, 최저 > 최고, 강수 < 0)
  물가
    · 계열마다 빠진 달, 한 달 새 20% 넘게 바뀐 값

찾은 것은 '의심' 이다. 진짜 폭등일 수도 있다 (예: 2024 사과). 사람이 보고 판단해서, 문제인 구간은
모델 학습에서 뺀다. DB 의 데이터는 고치거나 지우지 않는다.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config  # noqa: E402, F401  (출력 UTF-8 설정)
from collector import loader  # noqa: E402

SHIFT_WINDOW = 250     # 수준 이동을 볼 앞뒤 조사일 수 (약 1년)
SHIFT_RATIO = 2.5
SPIKE_RATIO = 5.0
ABRUPT_JUMP = 2.0     # 하루 사이 이만큼 바뀌면 '갑작스러운' 수준 이동 (단위 변경 의심)
CPI_JUMP = 0.20
TA_RANGE = (-40, 45)
OUT = ROOT / "logs" / "quality"


# ── 가격 ──────────────────────────────────────────────────────────────────
def level_shifts(dates, prices, window=SHIFT_WINDOW, ratio=SHIFT_RATIO):
    """앞뒤 window 개 중앙값 비율이 ratio 를 넘는 지점. 이어진 지점은 가장 큰 곳 하나로 묶는다.

    돌려주는 것: [(날짜, 앞 중앙값, 뒤 중앙값, 비율, 하루 최대 변화)] — 비율은 뒤/앞 (1/3 이면 0.33).
    하루 최대 변화: 그 지점 앞뒤 window 개 안에서 하루 사이 가장 크게 바뀐 배수 (1 보다 크게 맞춘다).
      단위 변경은 하루아침에 바뀌어 이 값이 크다 (2배 이상). 시장 변화는 몇 달에 걸쳐 바뀌어 작다.
    """
    p = np.asarray(prices, float)
    n = len(p)
    if n < 2 * window:
        return []
    s = pd.Series(p)
    before = s.rolling(window).median().shift(1).to_numpy()        # i 직전 window 개
    after = s[::-1].rolling(window).median()[::-1].to_numpy()       # i 부터 window 개
    r = after / before
    hit = np.flatnonzero((r >= ratio) | (r <= 1 / ratio))
    out = []
    for grp in np.split(hit, np.flatnonzero(np.diff(hit) > 1) + 1) if len(hit) else []:
        # 비율이 가장 큰 지점이 여러 날 이어질 수 있다 (단위가 바뀐 날 앞뒤로 같은 비율).
        # 그중 하루 변화가 가장 큰 날을 고른다 — 단위 변경이면 그날이 실제로 바뀐 날이다.
        mag = np.abs(np.log(r[grp]))
        top = grp[mag >= mag.max() - 1e-9]
        day_jump = np.abs(np.log(p[top] / p[np.maximum(top - 1, 0)]))
        k = top[np.argmax(day_jump)] if day_jump.max() > 0 else top[len(top) // 2]
        lo, hi = max(k - window, 1), min(k + window, n - 1)
        jumps = np.abs(np.diff(np.log(p[lo - 1: hi + 1])))
        out.append((dates[k], before[k], after[k], r[k], float(np.exp(jumps.max())) if len(jumps) else 1.0))
    return out


def spikes(dates, prices, ratio=SPIKE_RATIO):
    """하루만 앞 · 뒤 값보다 ratio 배 넘게 다른 날. [(날짜, 앞, 그날, 뒤)]."""
    p = np.asarray(prices, float)
    if len(p) < 3:
        return []
    prev, cur, nxt = p[:-2], p[1:-1], p[2:]
    up = (cur / prev >= ratio) & (cur / nxt >= ratio)
    down = (prev / cur >= ratio) & (nxt / cur >= ratio)
    k = np.flatnonzero(up | down) + 1
    return [(dates[i], p[i - 1], p[i], p[i + 1]) for i in k]


def check_prices(conn, markets):
    df = pd.read_sql("""
        SELECT MARKET_TYPE AS market, ITEM_CODE, KIND_CODE, RANK_NAME, ITEM_NAME, KIND_NAME,
               SURVEY_DATE AS d, PRICE_TODAY::float8 AS p, DATA_SOURCE AS src
        FROM   TBL_DAILY_PRICE
        WHERE  PRICE_TODAY > 0 AND MARKET_TYPE = ANY(%(m)s)
        ORDER  BY MARKET_TYPE, ITEM_CODE, KIND_CODE, RANK_NAME, SURVEY_DATE
    """, conn, params={"m": markets})
    df.columns = [c.lower() for c in df.columns]
    shifts, spk = [], []
    for (m, i, k, r), g in df.groupby(["market", "item_code", "kind_code", "rank_name"], sort=False):
        name = f"{g.item_name.iloc[-1]} {g.kind_name.iloc[-1]} {r}"
        d, p = g.d.to_numpy(), g.p.to_numpy()
        for day, b, a, ratio, jump in level_shifts(d, p):
            shifts.append({"market": m, "series": f"{i}/{k}/{r}", "name": name, "date": day,
                           "before": round(b), "after": round(a), "ratio": round(ratio, 2),
                           "max_day_jump": round(jump, 2),
                           "kind": "단위 변경 의심" if jump >= ABRUPT_JUMP else "시장 변화(점진)"})
        for day, b, x, a in spikes(d, p):
            spk.append({"market": m, "series": f"{i}/{k}/{r}", "name": name, "date": day,
                        "prev": b, "value": x, "next": a})
    years = (df.assign(y=pd.to_datetime(df.d).dt.year)
             .pivot_table(index="y", columns="market", values="p", aggfunc="size", fill_value=0))
    return pd.DataFrame(shifts), pd.DataFrame(spk), years, df.groupby(["market", "item_code", "kind_code",
                                                                        "rank_name"]).ngroups


# ── 날씨 ──────────────────────────────────────────────────────────────────
def check_weather(conn):
    gaps = pd.read_sql("""
        SELECT s.STN_ID AS stn, s.STN_NAME AS name, MIN(w.OBS_DATE) AS first, MAX(w.OBS_DATE) AS last,
               (MAX(w.OBS_DATE) - MIN(w.OBS_DATE) + 1) - COUNT(*) AS missing
        FROM   TBL_WEATHER_STATION s JOIN TBL_WEATHER_DAILY w USING (STN_ID)
        GROUP  BY 1, 2 ORDER BY missing DESC
    """, conn)
    bad = pd.read_sql(f"""
        SELECT w.OBS_DATE AS d, s.STN_NAME AS name, w.MIN_TA AS min_ta, w.AVG_TA AS avg_ta,
               w.MAX_TA AS max_ta, w.SUM_RN AS sum_rn
        FROM   TBL_WEATHER_DAILY w JOIN TBL_WEATHER_STATION s USING (STN_ID)
        WHERE  w.MIN_TA < {TA_RANGE[0]} OR w.MAX_TA > {TA_RANGE[1]} OR w.MIN_TA > w.MAX_TA
           OR  w.AVG_TA < w.MIN_TA - 0.5 OR w.AVG_TA > w.MAX_TA + 0.5 OR w.SUM_RN < 0
        ORDER  BY 1
    """, conn)
    return gaps, bad


# ── 물가 ──────────────────────────────────────────────────────────────────
def check_cpi(conn):
    df = pd.read_sql("""SELECT ITEM_CODE AS item, ITEM_NAME AS name, PERIOD AS period, VALUE::float8 AS v
                        FROM TBL_CPI_MONTHLY ORDER BY 1, 3""", conn)
    missing, jumps = [], []
    for (item, name), g in df.groupby(["item", "name"]):
        months = pd.PeriodIndex(g.period, freq="M")
        full = pd.period_range(months.min(), months.max(), freq="M")
        lack = sorted(set(full) - set(months))
        if lack:
            missing.append({"item": item, "name": name, "missing": len(lack), "first": str(lack[0])})
        ch = g.v.pct_change().abs().to_numpy()
        for idx in np.flatnonzero(ch > CPI_JUMP):
            jumps.append({"item": item, "name": name, "period": g.period.iloc[idx],
                          "change": round(float(g.v.iloc[idx] / g.v.iloc[idx - 1] - 1), 3)})
    return pd.DataFrame(missing), pd.DataFrame(jumps), df.item.nunique()


# ── 실행 ──────────────────────────────────────────────────────────────────
def _show(title, df, top=20):
    print(f"\n── {title}: {len(df)}건 ──")
    if len(df):
        print(df.head(top).to_string(index=False))
        if len(df) > top:
            print(f"  … 외 {len(df) - top}건 (--csv 로 전체를 파일에)")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m collector.quality", description="데이터 품질 점검")
    p.add_argument("--only", choices=["price", "weather", "cpi"])
    p.add_argument("--market", choices=["소매", "도매"], help="가격 점검 시장 (기본 둘 다)")
    p.add_argument("--csv", action="store_true", help="의심 목록을 logs/quality/*.csv 로도 남긴다")
    a = p.parse_args(sys.argv[1:] if argv is None else argv)
    conn = loader.connect()
    saved = {}
    try:
        if a.only in (None, "price"):
            markets = [a.market] if a.market else ["소매", "도매"]
            shifts, spk, years, n = check_prices(conn, markets)
            print(f"\n===== 가격 · {'·'.join(markets)} · 품종 {n}개 =====")
            print("\n── 연도별 행 수 ──")
            print(years.to_string())
            if len(shifts):
                shifts = shifts.assign(_abs=np.abs(np.log(shifts.ratio))).sort_values("_abs", ascending=False)
                shifts = shifts.drop(columns="_abs")
            if len(shifts):
                _show(f"단위 변경 의심 (1년 수준이 {SHIFT_RATIO:g}배 넘게 바뀌었고, 하루 사이 {ABRUPT_JUMP:g}배 넘게 튐)",
                      shifts[shifts.kind == "단위 변경 의심"])
                _show("시장 변화 (1년 수준이 크게 바뀌었지만 점진적 — 참고용)", shifts[shifts.kind != "단위 변경 의심"], top=10)
            else:
                _show("수준 이동", shifts)
            _show(f"하루 튐 의심 (앞뒤보다 {SPIKE_RATIO:g}배 넘게)", spk)
            saved.update(price_shifts=shifts, price_spikes=spk)
        if a.only in (None, "weather"):
            gaps, bad = check_weather(conn)
            print(f"\n===== 날씨 · 관측소 {len(gaps)}곳 =====")
            _show("빠진 날이 있는 관측소", gaps[gaps.missing > 0])
            _show("범위 밖 값", bad)
            saved.update(weather_gaps=gaps, weather_bad=bad)
        if a.only in (None, "cpi"):
            miss, jumps, n = check_cpi(conn)
            print(f"\n===== 물가 · 계열 {n}개 =====")
            _show("빠진 달이 있는 계열", miss)
            _show(f"한 달 새 {CPI_JUMP:.0%} 넘게 바뀐 값", jumps)
            saved.update(cpi_missing=miss, cpi_jumps=jumps)
    finally:
        conn.close()
    if a.csv:
        OUT.mkdir(parents=True, exist_ok=True)
        for name, df in saved.items():
            df.to_csv(OUT / f"{name}.csv", index=False, encoding="utf-8-sig")
        print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
