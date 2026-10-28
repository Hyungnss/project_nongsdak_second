"""
15단계 — 가격 상승은 날씨 탓인가, 물가·사건 탓인가

실행:
    python 15_weather_vs_rise.py

입력  data/processed/year_rise.csv        14_year_rise.py 결과 (필수)
      data/raw/ta_*.csv                   년계절별 기온 (필수)
      data/raw/rn_*.csv                   년계절별 강수량 (필수)
      data/raw/cpi.csv                    소비자물가지수 (있으면 씁니다)

출력  data/processed/weather_vs_rise.csv  연도별 비교표
      화면에 표와 판단 근거를 전부 찍습니다. 웹페이지는 만들지 않습니다.


무엇을 확인하는가

    "2022년에 가격이 6.68% 올랐다" 는 사실이다.
    그런데 그게 날씨 때문인가?

    날씨 때문이라면, 가격이 많이 오른 해는 날씨도 유별났어야 한다.
    가격이 많이 오른 해의 날씨가 평범했다면, 원인은 다른 데 있다.
    물가상승 · 팬데믹 · 전쟁 · 유가 같은 것들이다.

    이 스크립트는 그 대조를 표로 만들어 준다.
    "날씨가 원인이다/아니다" 를 증명하지는 못한다.
    다만 '날씨로 설명되지 않는다' 는 것은 꽤 분명하게 보일 수 있다.


어떻게 견주는가

    가격 상승률은 '전년 대비' 값이다.
    그래서 날씨도 '전년 대비 변화' 로 맞춰서 견준다.

        가격 상승률 (%)        14_year_rise.py 가 낸 값
        기온 변화  (℃)         그 해 기온 − 전 해 기온
        강수 변화  (mm)        그 해 강수 − 전 해 강수

    '평년 대비 이상치' 도 함께 낸다. 그 해가 유별났는지 보는 값이다.

        기온 이상 = 그 해 기온 − 전체 기간 평균 기온


겨울은 해를 넘긴다

    겨울(12~2월)은 두 해에 걸쳐 있다.
    'YYYY 겨울' 이 그 해 12월부터인지, 그 해 2월까지인지는
    자료를 받은 곳마다 다르다. WINTER_IS_DECEMBER 로 맞출 수 있다.

    그래서 이 스크립트는 두 가지를 함께 낸다.

        4계절     봄·여름·가을·겨울 전부
        성장기    봄·여름·가을만 (겨울 제외)

    농산물은 성장기 날씨가 더 중요하고,
    겨울을 빼면 위의 애매함도 사라진다.
    두 값의 결론이 다르면 겨울 해석에 좌우된 것이니 조심해야 한다.


한계 — 반드시 읽을 것

    · 연도는 10개 안팎이다. 상관계수를 내도 우연일 가능성이 매우 크다.
      이 스크립트는 상관계수 옆에 '우연으로 볼 수 있는 선' 을 같이 찍는다.
      그 선을 넘지 못하면 "관계가 없다" 가 아니라 "이 자료로는 모른다" 이다.
    · 날씨가 전국 하나뿐이라 지역별 작황 차이는 볼 수 없다.
    · 상관은 인과가 아니다.
    · 팬데믹·전쟁 메모는 사람이 적어 넣은 주석이다. 데이터가 아니다.
"""

import math
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_DIR = PROJECT_ROOT / "data" / "processed"

RISE_FILE = DATA_DIR / "year_rise.csv"
CPI_FILE = RAW_DIR / "cpi.csv"

OUT_FILE = DATA_DIR / "weather_vs_rise.csv"

# 기온·강수 파일 찾는 규칙
#   기상자료개방포털에서 받으면 ta_20260819125338.csv 처럼 받은 시각이 붙습니다.
#   이름을 바꾸지 않아도 되도록 앞글자로 찾습니다. 여러 개면 가장 최근 것을 씁니다.
TEMP_GLOB = "ta_*.csv"
RAIN_GLOB = "rn_*.csv"

# 'YYYY 겨울' 이 그 해 12월부터인가?
#   True  = 2016 겨울 → 2016.12 ~ 2017.02   (기상청 계절값 기본)
#   False = 2016 겨울 → 2015.12 ~ 2016.02
#   확실하지 않으면 아래 '성장기' 결과를 보세요. 겨울을 빼므로 영향을 안 받습니다.
WINTER_IS_DECEMBER = True

SPRING, SUMMER, AUTUMN, WINTER = "봄", "여름", "가을", "겨울"
GROWING = [SPRING, SUMMER, AUTUMN]

# 어느 기준으로 판정할지
#   "4계절"  겨울 포함. 그 해 작물에 앞서는 겨울부터 1년 (12월~11월)
#   "성장기"  겨울 제외. 봄~가을만
#   둘 다 두면 같은 판정을 두 번 내고, 결론이 갈리는지도 알려 줍니다.
#   한쪽만 보고 싶으면 목록에서 지우세요.
SHOW_SCOPES = ["4계절", "성장기"]

# 사람이 적어 넣는 메모. 데이터가 아니라 해석을 돕는 주석입니다.
#   여러분이 아는 사건이 더 있으면 여기 적으세요. 계산에는 쓰이지 않습니다.
EVENTS = {
    2020: "코로나19 시작",
    2021: "물류대란 · 원자재 상승",
    2022: "러시아-우크라이나 전쟁 · 유가/비료값 급등",
}

# 순열검정 횟수
#   가격 순서를 무작위로 섞어 "아무 관계 없을 때 이만한 상관이 얼마나 자주 나오나" 를 셉니다.
#   연도가 10개 안팎이라 정규분포 가정이 위태로운데, 이 방법은 가정이 필요 없습니다.
N_SHUFFLE = 20000


# ---------------------------------------------------------
# 0. 표 맞추기 (한글은 터미널에서 두 칸)
# ---------------------------------------------------------

def width(text):
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1
               for ch in str(text))


def lpad(text, n):
    return str(text) + " " * max(0, n - width(text))


def rpad(text, n):
    return " " * max(0, n - width(text)) + str(text)


def fmt(value, digits=2, plus=True):
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "—"
    sign = "+" if (plus and value >= 0) else ""
    return f"{sign}{value:.{digits}f}"


# ---------------------------------------------------------
# 1. 읽기 도우미
#    기상자료개방포털 파일은 인코딩이 cp949 인 경우가 많고,
#    실제 표 위에 안내문이 몇 줄 붙어 오기도 합니다.
#    '년계절' 이 있는 줄을 찾아 거기부터 읽습니다.
# ---------------------------------------------------------

def read_kma(path, must_have="년계절"):

    encodings = ("utf-8-sig", "cp949", "euc-kr", "utf-8")

    text = None
    used = None

    for enc in encodings:
        try:
            text = path.read_text(encoding=enc)
            used = enc
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if text is None:
        raise UnicodeDecodeError(
            "kma", b"", 0, 1,
            f"{path.name} 의 인코딩을 못 읽었습니다. 시도한 것: {encodings}")

    lines = text.splitlines()

    def is_header(line):
        """머리글 줄인가.

        '# 자료구분: 년계절값' 같은 안내문에도 '년계절' 이 들어 있습니다.
        단순히 글자가 들어 있는지만 보면 안내문을 머리글로 착각합니다.
        쉼표로 나눈 '칸' 하나가 그 이름이어야 진짜 머리글입니다.
        """
        fields = [f.strip().strip('"') for f in line.split(",")]

        if len(fields) < 2:
            return False

        return any(f == must_have or (must_have and f.startswith(must_have))
                   or must_have == "" for f in fields)

    header = next((i for i, line in enumerate(lines) if is_header(line)), None)

    if header is None:
        raise KeyError(
            f"{path.name} 에서 '{must_have}' 칸이 있는 머리글 줄을 못 찾았습니다.\n"
            f"  첫 3줄: {lines[:3]}")

    frame = pd.read_csv(path, encoding=used, skiprows=header)
    frame.columns = [str(c).strip() for c in frame.columns]

    if header:
        print(f"  {path.name}: 안내문 {header}줄을 건너뛰었습니다 ({used})")

    return frame


def pick_column(frame, *hints):
    """'평균기온(℃)' 처럼 단위가 붙어도 찾아냅니다."""

    for hint in hints:
        for col in frame.columns:
            if hint in str(col):
                return col

    raise KeyError(
        f"'{hints[0]}' 에 해당하는 컬럼을 못 찾았습니다.\n"
        f"  실제 컬럼: {frame.columns.tolist()}")


def newest(pattern):
    found = sorted(RAW_DIR.glob(pattern))
    if not found:
        return None
    return max(found, key=lambda p: p.stat().st_mtime)


def split_year_season(series):
    """'2016 봄' → (2016, '봄')"""

    parts = series.astype(str).str.strip().str.split(r"\s+", n=1, expand=True)

    year = pd.to_numeric(parts[0], errors="coerce")
    season = parts[1].astype(str).str.strip() if parts.shape[1] > 1 else None

    return year, season


# ---------------------------------------------------------
# 2. 날씨 읽기
# ---------------------------------------------------------

print("=" * 78)
print("가격 상승은 날씨 탓인가 — 연도별 대조")
print("=" * 78)

temp_path = newest(TEMP_GLOB)
rain_path = newest(RAIN_GLOB)

if temp_path is None:
    raise FileNotFoundError(
        f"기온 파일이 없습니다: {RAW_DIR}/{TEMP_GLOB}\n"
        f"  기상자료개방포털에서 '년계절' 기온을 받아 두세요.")

if rain_path is None:
    raise FileNotFoundError(
        f"강수량 파일이 없습니다: {RAW_DIR}/{RAIN_GLOB}\n"
        f"  기상자료개방포털에서 '년계절' 강수량을 받아 두세요.")

print(f"\n기온:   {temp_path.name}")
temp = read_kma(temp_path)

print(f"강수량: {rain_path.name}")
rain = read_kma(rain_path)

# --- 지점 확인 ---
#   전국 한 줄이어야 합니다. 지점이 여럿이면 같은 해가 여러 번 나와 평균이 뒤틀립니다.
for name, frame in (("기온", temp), ("강수량", rain)):

    if "지점" not in frame.columns:
        continue

    spots = frame["지점"].dropna().unique()

    if len(spots) > 1:
        keep = "전국" if "전국" in spots else spots[0]
        print(f"\n  [주의] {name} 자료에 지점이 {len(spots)}개 있습니다: {list(spots)[:5]}")
        print(f"         '{keep}' 만 씁니다. 지역별로 보려면 이 스크립트를 고쳐야 합니다.")
        frame.drop(frame.index[frame["지점"] != keep], inplace=True)

t_year, t_season = split_year_season(temp[pick_column(temp, "년계절", "계절")])
r_year, r_season = split_year_season(rain[pick_column(rain, "년계절", "계절")])

temp = temp.assign(year=t_year, season=t_season)
rain = rain.assign(year=r_year, season=r_season)

TAVG = pick_column(temp, "평균기온")
TMIN = pick_column(temp, "평균최저기온", "최저기온")
TMAX = pick_column(temp, "평균최고기온", "최고기온")
RAIN = pick_column(rain, "강수량")

season = temp[["year", "season", TAVG, TMIN, TMAX]].merge(
    rain[["year", "season", RAIN]], on=["year", "season"], how="outer")

season = season.rename(columns={TAVG: "tavg", TMIN: "tmin",
                                TMAX: "tmax", RAIN: "rain"})

for col in ("tavg", "tmin", "tmax", "rain"):
    season[col] = pd.to_numeric(season[col], errors="coerce")

season = season.dropna(subset=["year", "season"])
season["year"] = season["year"].astype(int)

# 겨울을 어느 해로 볼지 — 12월부터라면 그 겨울의 영향은 '다음 해' 작물에 간다
if WINTER_IS_DECEMBER:
    season["crop_year"] = np.where(season["season"] == WINTER,
                                   season["year"] + 1, season["year"])
    winter_note = "'YYYY 겨울' = YYYY.12 ~ 다음해 2월 → 다음 해에 넣었습니다"
else:
    season["crop_year"] = season["year"]
    winter_note = "'YYYY 겨울' = 전해 12월 ~ YYYY.2 → 그 해에 넣었습니다"

found = sorted(season["season"].unique())
print(f"\n계절: {found}")
print(f"기간: {season['year'].min()} ~ {season['year'].max()}")
print(f"겨울 처리: {winter_note}")

missing = {SPRING, SUMMER, AUTUMN, WINTER} - set(found)

if missing:
    print(f"\n  [주의] 없는 계절이 있습니다: {sorted(missing)}")
    print(f"         계절 이름이 다르면 SPRING/SUMMER/AUTUMN/WINTER 를 고치세요.")


# ---------------------------------------------------------
# 3. 연도별 날씨
#    4계절 전부와 성장기(겨울 제외) 두 벌을 만듭니다.
# ---------------------------------------------------------

def yearly(frame, year_col, label):

    out = (frame.groupby(year_col)
                .agg(tavg=("tavg", "mean"), tmin=("tmin", "mean"),
                     tmax=("tmax", "mean"), rain=("rain", "sum"),
                     seasons=("season", "nunique"))
                .rename_axis("year").reset_index())

    out["scope"] = label
    return out

full = yearly(season, "crop_year", "4계절")
grow = yearly(season[season["season"].isin(GROWING)], "year", "성장기")

# 계절이 다 안 찬 해는 평균이 한쪽으로 쏠려 비교가 어긋납니다
for label, frame, need_n in (("4계절", full, 4), ("성장기", grow, 3)):
    thin = frame[frame["seasons"] < need_n]
    if len(thin):
        years = ", ".join(f"{int(r.year)}년({int(r.seasons)}계절)"
                          for r in thin.itertuples())
        print(f"\n  [주의] {label}: 계절이 덜 찬 해를 뺍니다 — {years}")

full = full[full["seasons"] >= 4]
grow = grow[grow["seasons"] >= 3]


# ---------------------------------------------------------
# 4. 가격 상승률
# ---------------------------------------------------------

if not RISE_FILE.exists():
    raise FileNotFoundError(
        f"가격 상승률이 없습니다: {RISE_FILE}\n"
        f"  먼저 python 14_year_rise.py 를 실행하세요.")

rise = pd.read_csv(RISE_FILE, encoding="utf-8-sig")
rise["year"] = rise["year"].astype(int)

print(f"\n가격 상승률: {RISE_FILE.name}  {len(rise)}개 연도 "
      f"({rise['year'].min()} ~ {rise['year'].max()})")


# ---------------------------------------------------------
# 5. 물가 (있으면)
# ---------------------------------------------------------

def load_cpi_year():
    """연도별 물가지수를 돌려줍니다. 없으면 (None, 사유)."""

    if not CPI_FILE.exists():
        return None, f"{CPI_FILE.name} 이 없어 물가 비교는 건너뜁니다."

    try:
        cpi = read_kma(CPI_FILE, must_have="")  # 안내문 없으면 0줄 건너뜀
    except Exception as err:
        return None, f"{CPI_FILE.name} 을 읽지 못했습니다: {err}"

    cpi.columns = [str(c).strip().strip('"') for c in cpi.columns]

    # 가로형: "시도별", 2016.01, 2016.02 ... 처럼 시점이 컬럼으로 눕는 형태
    ym_cols = [c for c in cpi.columns
               if any(ch.isdigit() for ch in c) and ("." in c or len(c) >= 6)]

    if len(ym_cols) >= 12:

        row = cpi.iloc[0]

        for _, candidate in cpi.iterrows():
            if any("전국" in str(v) for v in candidate.values):
                row = candidate
                break

        pairs = []

        for col in ym_cols:
            year = pd.to_numeric(str(col).split(".")[0], errors="coerce")
            value = pd.to_numeric(row[col], errors="coerce")
            if pd.notna(year) and pd.notna(value):
                pairs.append((int(year), float(value)))

        if not pairs:
            return None, "가로형 물가지수에서 값을 못 읽었습니다."

        wide = pd.DataFrame(pairs, columns=["year", "cpi"])
        return wide.groupby("year")["cpi"].mean().reset_index(), None

    return None, "물가지수 형식을 알아보지 못했습니다 (가로형만 지원)."


cpi_year, cpi_reason = load_cpi_year()

if cpi_year is None:
    print(f"\n물가: {cpi_reason}")
else:
    cpi_year = cpi_year.sort_values("year")
    cpi_year["cpi_rise_pct"] = cpi_year["cpi"].pct_change() * 100
    print(f"\n물가: {CPI_FILE.name}  {len(cpi_year)}개 연도")


# ---------------------------------------------------------
# 6. 비교표
#    가격 상승률은 '전년 대비' 값이므로 날씨도 '전년 대비 변화' 로 맞춥니다.
#    함께 '평년 대비 이상치' 도 냅니다 — 그 해가 유별났는지 보는 값입니다.
# ---------------------------------------------------------

def build(weather, label):

    w = weather.sort_values("year").copy()

    for col in ("tavg", "tmin", "tmax", "rain"):
        w[f"d_{col}"] = w[col].diff()                    # 전년 대비 변화
        w[f"a_{col}"] = w[col] - w[col].mean()           # 평년 대비 이상치

    merged = rise.merge(w, on="year", how="inner")

    if cpi_year is not None:
        merged = merged.merge(cpi_year[["year", "cpi_rise_pct"]],
                              on="year", how="left")
        merged["excess_pct"] = merged["rise_pct"] - merged["cpi_rise_pct"]

    merged["scope"] = label

    # 날씨가 얼마나 유별났나 — 세 지표의 이상치를 표준화해 크기만 더합니다.
    # 단위가 ℃ 와 mm 로 달라 그냥 더하면 강수량이 다 먹습니다.
    parts = []

    for col in ("a_tavg", "a_tmax", "a_rain"):
        std = merged[col].std()
        parts.append((merged[col] / std).abs() if std and np.isfinite(std)
                     else pd.Series(0.0, index=merged.index))

    merged["odd_score"] = sum(parts) / len(parts)

    return merged


tables = {"4계절": build(full, "4계절"), "성장기": build(grow, "성장기")}

# 설정에 없는 기준은 아예 만들지 않습니다 (표도 판정도 나오지 않게)
tables = {k: v for k, v in tables.items() if k in SHOW_SCOPES}


def show(table, label):

    print("\n" + "=" * 78)
    print(f"연도별 대조 — {label}"
          + ("  (봄·여름·가을만)" if label == "성장기" else ""))
    print("=" * 78)

    has_cpi = "cpi_rise_pct" in table.columns

    head = (lpad("연도", 6) + rpad("가격상승", 9)
            + (rpad("물가", 8) + rpad("초과분", 9) if has_cpi else "")
            + rpad("Δ평균", 8) + rpad("Δ최고", 8) + rpad("Δ최저", 8)
            + rpad("Δ강수", 10) + rpad("날씨유별", 10))

    print("\n" + head)
    print("-" * 78)

    for _, r in table.sort_values("year").iterrows():

        line = (lpad(int(r["year"]), 6)
                + rpad(fmt(r["rise_pct"], 2) + "%", 9))

        if has_cpi:
            line += (rpad(fmt(r.get("cpi_rise_pct"), 1) + "%", 8)
                     + rpad(fmt(r.get("excess_pct"), 1) + "%", 9))

        line += (rpad(fmt(r["d_tavg"], 1), 8)
                 + rpad(fmt(r["d_tmax"], 1), 8)
                 + rpad(fmt(r["d_tmin"], 1), 8)
                 + rpad(fmt(r["d_rain"], 0), 10)
                 + rpad(f"{r['odd_score']:.2f}", 10))

        note = EVENTS.get(int(r["year"]))
        print(line + ("   " + note if note else ""))

    print("\n  Δ = 전년 대비 변화 (기온 ℃ · 강수 mm)")
    print("  날씨유별 = 평년에서 얼마나 벗어났나 (기온·최고기온·강수 이상치의 크기 평균)")

    if has_cpi:
        print("  초과분 = 가격상승률 − 물가상승률. 물가로 설명되지 않는 몫입니다.")


for label, table in tables.items():
    show(table, label)


# ---------------------------------------------------------
# 7~10. 판정
#    4계절과 성장기 각각에 대해 같은 판정을 따로 냅니다.
#    한쪽만 내면 "겨울을 넣었나 뺐나" 를 알 수 없고,
#    두 판의 결론이 갈리는지도 볼 수 없습니다.
# ---------------------------------------------------------

def judge(table, label):
    """한 기준(4계절 또는 성장기)으로 7~10절을 전부 낸다. results 를 돌려준다."""

    scope_note = ("겨울 포함 · 그 해 작물에 앞서는 겨울부터 1년"
                  if label == "4계절" else "겨울 제외 · 봄~가을만")

    print("\n\n" + "#" * 78)
    print(f"#  {label} 기준 판정   ({scope_note})")
    print("#" * 78)

    # --- 7. 날씨가 유별났던 해 ---
    print("\n" + "=" * 78)
    print(f"날씨가 유별났던 해 ({label} 기준)")
    print("=" * 78)

    for col, name, unit in (("d_tavg", "평균기온이 가장 크게 변한 해", "℃"),
                            ("d_tmax", "최고기온이 가장 크게 변한 해", "℃"),
                            ("d_tmin", "최저기온이 가장 크게 변한 해", "℃"),
                            ("d_rain", "강수량이 가장 크게 변한 해", "mm")):

        sub = table.dropna(subset=[col])

        if sub.empty:
            continue

        row = sub.loc[sub[col].abs().idxmax()]
        print(f"\n  {name}: {int(row['year'])}년 "
              f"({fmt(row[col], 1)}{unit}, 전년 대비)")
        print(f"    그 해 가격 상승률 {fmt(row['rise_pct'], 2)}%")

    odd = table.loc[table["odd_score"].idxmax()]
    print(f"\n  종합적으로 날씨가 가장 유별났던 해: {int(odd['year'])}년 "
          f"(유별 점수 {odd['odd_score']:.2f})")
    print(f"    그 해 가격 상승률 {fmt(odd['rise_pct'], 2)}%")

    # --- 8. 겹치는가 ---
    print("\n" + "=" * 78)
    print(f"가격이 많이 오른 해와 날씨가 유별난 해가 겹치는가 ({label})")
    print("=" * 78)

    top_n = min(3, len(table))

    top_price = table.nlargest(top_n, "rise_pct")["year"].astype(int).tolist()
    top_odd = table.nlargest(top_n, "odd_score")["year"].astype(int).tolist()
    overlap = [y for y in top_price if y in top_odd]

    print(f"\n  가격이 많이 오른 해 {top_n}개:   {top_price}")
    print(f"  날씨가 유별났던 해 {top_n}개:   {top_odd}")
    print(f"  겹치는 해: {overlap if overlap else '없음'}")

    if not overlap:
        print("\n  → 가격이 많이 오른 해와 날씨가 유별난 해가 하나도 겹치지 않습니다.")
        print("    날씨만으로는 가격 상승을 설명하기 어렵다는 뜻입니다.")
    elif len(overlap) == top_n:
        print("\n  → 전부 겹칩니다. 날씨와 함께 움직였을 가능성이 있습니다.")
    else:
        print(f"\n  → {len(overlap)}개만 겹칩니다. 어느 쪽이라 말하기 어렵습니다.")

    # --- 9. 상관 (순열검정) ---
    #     지표를 여덟 개나 늘어놓고 그중 하나가 걸리면 "관계가 있다" 고 말하는 것은
    #     주사위를 여덟 번 던져 6이 한 번 나온 걸 두고 놀라는 것과 같습니다.
    #     그래서 두 확률을 함께 냅니다.
    #       p(단독)  이 지표 하나만 봤을 때 우연히 이만큼 나올 확률
    #       p(전체)  지표 전부 중 '가장 센 것' 이 우연히 이만큼 나올 확률
    #     판단은 p(전체) 로 합니다.
    print("\n" + "=" * 78)
    print(f"상관계수 — 가격 상승률 vs 각 지표 ({label})")
    print("=" * 78)

    targets = [("d_tavg", "평균기온 변화"), ("d_tmax", "최고기온 변화"),
               ("d_tmin", "최저기온 변화"), ("d_rain", "강수량 변화"),
               ("a_tavg", "평균기온 이상치"), ("a_rain", "강수량 이상치"),
               ("odd_score", "날씨 유별 점수")]

    if "cpi_rise_pct" in table.columns:
        targets.append(("cpi_rise_pct", "물가 상승률"))

    cols = [c for c, _ in targets if c in table.columns]
    names = {c: text for c, text in targets}

    pairs = table[["rise_pct"] + cols].dropna()

    # 값이 전부 같은 지표는 상관을 낼 수 없습니다
    cols = [c for c in cols if pairs[c].std() > 0]

    results = []

    if len(pairs) < 4 or not cols:
        print(f"\n  짝지어진 연도가 너무 적어 상관을 내지 않습니다 ({len(pairs)}개).")
        return results

    y = pairs["rise_pct"].to_numpy(float)
    X = pairs[cols].to_numpy(float)
    n_year = len(y)

    Xs = (X - X.mean(0)) / X.std(0)
    ys = (y - y.mean()) / y.std()

    r_obs = (ys @ Xs) / n_year

    # 가격 순서를 섞어 '아무 관계 없는 세상' 을 N_SHUFFLE 번 만들어 봅니다
    rng = np.random.default_rng(0)
    Y = np.array([rng.permutation(y) for _ in range(N_SHUFFLE)])
    Ys = (Y - Y.mean(1, keepdims=True)) / Y.std(1, keepdims=True)

    R = (Ys @ Xs) / n_year
    A = np.abs(R)

    p_single = (A >= np.abs(r_obs)).mean(0)
    p_family = (A.max(1)[:, None] >= np.abs(r_obs)).mean(0)

    print("\n" + lpad("지표", 20) + rpad("상관 r", 9) + rpad("p(단독)", 10)
          + rpad("p(전체)", 10) + "  판단")
    print("-" * 78)

    for j, col in enumerate(cols):

        if p_family[j] < 0.05:
            verdict = "우연으로 보기 어렵다"
        elif p_single[j] < 0.05:
            verdict = "혼자 보면 유의하나 여러 지표 중 하나라 확실치 않다"
        else:
            verdict = "우연일 수 있다"

        print(lpad(names[col], 20) + rpad(fmt(r_obs[j], 3), 9)
              + rpad(f"{p_single[j]:.3f}", 10)
              + rpad(f"{p_family[j]:.3f}", 10) + "  " + verdict)

        results.append((names[col], float(r_obs[j]), n_year,
                        float(p_family[j]), p_family[j] < 0.05))

    print(f"\n  연도 {n_year}개 · 지표 {len(cols)}개 · {N_SHUFFLE:,}번 섞어 본 결과입니다.")
    print("  p(전체) 는 '지표를 여러 개 늘어놓고 가장 센 것을 골랐다' 는 점까지 감안한 값입니다.")
    print("  넘지 못했다고 '관계가 없다' 가 아니라 '이 자료로는 판단할 수 없다' 는 뜻입니다.")

    # --- 10. 정리 ---
    print("\n" + "=" * 78)
    print(f"정리 ({label})")
    print("=" * 78)

    weather_hits = [name for name, r, nn, pf, ok in results
                    if ok and name != "물가 상승률"]

    cpi_hit = next((r for name, r, nn, pf, ok in results
                    if name == "물가 상승률" and ok), None)

    if weather_hits:
        print(f"\n  날씨 지표 중 우연으로 보기 어려운 것: {', '.join(weather_hits)}")
        print("    다만 연도가 적어 이것만으로 단정하면 안 됩니다.")
    else:
        print("\n  날씨 지표 중 우연으로 보기 어려운 것이 하나도 없습니다.")
        print("    이 자료에서는 '가격 상승이 날씨 때문' 이라는 근거를 찾지 못했습니다.")

    if cpi_hit is not None:
        print(f"\n  반면 물가 상승률은 r = {cpi_hit:+.3f} 로 우연으로 보기 어렵습니다.")
        print("    가격 상승의 상당 부분이 물가를 따라 움직였다는 뜻입니다.")

    if "excess_pct" in table.columns:

        ex = table.dropna(subset=["excess_pct"])

        if len(ex):
            print(f"\n  물가로 설명되지 않는 몫(초과분) 중앙값: "
                  f"{fmt(ex['excess_pct'].median(), 2)}%p")

            big = ex.loc[ex["excess_pct"].idxmax()]
            print(f"    가장 큰 해는 {int(big['year'])}년 "
                  f"({fmt(big['excess_pct'], 2)}%p)"
                  + (f" — {EVENTS[int(big['year'])]}"
                     if int(big["year"]) in EVENTS else ""))
            print("    이 몫은 날씨·사건·유통 등 물가 밖의 무언가입니다.")
            print("    무엇인지는 이 자료만으로 가릴 수 없습니다.")

    return results


scopes = [s for s in SHOW_SCOPES if len(tables.get(s, []))]

if not scopes:
    raise SystemExit("판정할 수 있는 기준이 없습니다. 계절 자료를 확인하세요.")

verdicts = {label: judge(tables[label], label) for label in scopes}


# ---------------------------------------------------------
# 두 기준의 결론이 같은가
#    갈리면 '겨울을 넣었나 뺐나' 에 결론이 좌우된 것입니다.
#    그때는 어느 한쪽을 근거로 삼으면 안 됩니다.
# ---------------------------------------------------------

if len(verdicts) > 1:

    print("\n\n" + "=" * 78)
    print("두 기준의 결론 대조")
    print("=" * 78)

    def hits(res):
        return {name for name, r, nn, pf, ok in res if ok}

    a_label, b_label = list(verdicts)[0], list(verdicts)[1]
    a_hits, b_hits = hits(verdicts[a_label]), hits(verdicts[b_label])

    print(f"\n  {a_label}: {', '.join(sorted(a_hits)) if a_hits else '걸린 지표 없음'}")
    print(f"  {b_label}: {', '.join(sorted(b_hits)) if b_hits else '걸린 지표 없음'}")

    only_a = a_hits - b_hits
    only_b = b_hits - a_hits

    if a_hits == b_hits:
        print("\n  → 두 기준의 결론이 같습니다. 겨울을 넣든 빼든 같은 답이니 믿을 만합니다.")
    else:
        print("\n  → 두 기준의 결론이 다릅니다.")
        if only_a:
            print(f"    {a_label} 에서만 걸림: {', '.join(sorted(only_a))}")
        if only_b:
            print(f"    {b_label} 에서만 걸림: {', '.join(sorted(only_b))}")
        print("    겨울을 넣었는지 뺐는지에 결론이 좌우된다는 뜻입니다.")
        print("    한쪽만 골라 근거로 삼지 말고, 보고서에 둘 다 적으세요.")

    both = (tables[a_label][["year", "odd_score"]].set_index("year")
            .join(tables[b_label][["year", "odd_score"]].set_index("year"),
                  lsuffix="_a", rsuffix="_b").dropna())

    if len(both) >= 3:
        agree = both["odd_score_a"].corr(both["odd_score_b"])
        print(f"\n  '날씨 유별' 판단의 일치도: r = {agree:.2f}")
        if agree < 0.7:
            print("    두 기준이 서로 다른 해를 유별나다고 봅니다.")
            print("    WINTER_IS_DECEMBER 설정이 맞는지 확인하세요.")


# ---------------------------------------------------------
# 11. 저장
# ---------------------------------------------------------

out = pd.concat(tables.values(), ignore_index=True)
out["event"] = out["year"].map(EVENTS)

keep = ["scope", "year", "rise_pct", "cpi_rise_pct", "excess_pct",
        "tavg", "tmin", "tmax", "rain",
        "d_tavg", "d_tmin", "d_tmax", "d_rain",
        "a_tavg", "a_tmin", "a_tmax", "a_rain",
        "odd_score", "products", "event"]

out = out[[c for c in keep if c in out.columns]].round(3)
out.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")

print("\n" + "=" * 78)
print("저장")
print("=" * 78)
print(f"  {OUT_FILE}")

print("\n보고서에 함께 적을 것")
print("  · 연도가 10개 안팎이라 상관계수는 근거가 약합니다.")
print("    '날씨로 설명되지 않는다' 까지가 이 자료로 할 수 있는 말입니다.")
print("  · 날씨가 전국 하나뿐이라 지역별 작황 차이는 보지 못했습니다.")
print("  · 팬데믹·전쟁 메모는 사람이 적어 넣은 주석입니다. 데이터가 아닙니다.")
