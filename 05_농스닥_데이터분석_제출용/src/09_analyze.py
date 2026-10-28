"""
9단계 — 네 가지 질문을 한 번에 분석  (Q1 ~ Q4)

실행:
    python 09_analyze.py            주별 (기본)
    python 09_analyze.py month      월별
    python 09_analyze.py day        일별
    python 09_analyze.py all        셋 다 차례로

입력 (주기마다 다름)
    week   data/processed/price_weather_weekly.parquet    05_merge.py 결과
    month  data/processed/price_weather_monthly.parquet   11_merge_monthly.py 결과
    day    data/processed/price_day.csv                   팀원 제작 (이미 merge 됨)

    data/raw/cpi.csv    Q3 에만 필요. 없으면 Q3 만 건너뛴다.

출력
    data/processed/dashboard_data_<주기>.json   ← 10_dashboard.py 가 읽는다
    data/processed/q1_season_<주기>.csv
    data/processed/q2_weather_<주기>.csv
    data/processed/q3_inflation_<주기>.csv
    data/processed/q4_position_<주기>.csv


무엇에 답하는가

    Q1  품목별 가격에 계절 패턴이 있는가.
        1년 중 언제 싸고 언제 비싼가.

    Q2  기온과 강수량은 가격 변동과 어떤 관계인가.
        (계절을 걷어내지 않은 실제 가격 움직임으로 본다)

    Q3  10년간의 가격 상승은 소비자물가 상승으로 얼마나 설명되는가.

    Q4  과거 가격 분포를 기준으로 지금 가격 수준을 판단할 수 있는가.


모든 질문의 바탕 — 가격지수 (물가도 계절도 걷어내지 않는다)

    Q1 · Q2 · Q4 는 실제 가격 움직임 그대로를 본다.
    다만 상품마다 단위가 달라(배추 1포기 4천원 · 쌀 20kg 5만원) 원 단위로는
    서로 견줄 수 없어서, 그 상품의 전체 기간 중앙값으로 한 번 나눈다.

        가격지수 = 그 시점 가격 ÷ 그 상품의 전체 기간 중앙값
        평년값   = 그 자리(주차 · 월)의 가격지수 중앙값        ← 계절 모양

    ★ '한 번' 나눈다는 것이 핵심이다.
      해마다 다른 값으로 나누면 물가상승이 지워지지만, 기간 전체를 같은 수
      하나로 나누므로 물가상승이 그대로 남는다.
      옛 해는 1.00 아래, 최근 해는 1.00 위에 몰리는 게 정상이다.
      상관계수(Q2)와 백분위(Q4)는 상수로 나눠도 값이 변하지 않으므로,
      원 가격으로 계산한 것과 결과가 같다.

    Q1 은 '평년값' 자체가 답이고,
    Q2 는 가격지수와 기상을 바로 견주며,
    Q4 는 지금 값이 과거 같은 자리 분포의 어디인지를 본다.

    Q3 만 예외다. '물가로 얼마나 설명되는가' 가 질문 자체라서
    원 단위 가격과 소비자물가지수(CPI)를 쓴다.

    걷어내지 않은 대가 — 해석할 때 반드시 함께 적을 것

        Q1  계절 진폭에 10년치 물가상승이 섞여 실제 계절 진폭보다 커진다.
        Q2  계절이 기온과 가격을 함께 움직인 몫이 상관에 들어 있다.
            상관이 부풀므로 판정선을 높게 잡았다
            (Q2_WEAK_LINE 0.35 / Q2_STRONG_LINE 0.50).
        Q4  물가가 오른 만큼 최근 값이 위쪽에 몰려, 뭐든 '비싸다' 쪽으로 기운다.


주기마다 다른 것

    주기   계절 칸  시간 축   시차 범위   최소 관측
    ----   -------  -------   ---------   ---------
    주별   52 주    주        0~8 주      52 회
    월별   12 달    달        0~3 달      24 회
    일별   52 주    일        0~28 일     200 회

    일별의 계절 평년값은 '날짜' 가 아니라 '주차' 로 낸다.
    하루 단위로 10년치 평년값을 내면 한 칸에 10개뿐이라 들쭉날쭉하다.
    대신 시간 축과 시차는 하루 단위 그대로라 반응 시점을 더 잘게 본다.


한계 (보고서에 적을 것)
    · 날씨가 전국 하나뿐이라 지역별 비교는 못 한다.
    · 상관은 인과가 아니다.
    · 여기서 찾는 것은 '가격이 가장 싼 시기' 뿐이다.
      왜 그때 싼지(출하 시기 · 저장 · 수입 · 양식)는 이 자료 안에 없다.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_DIR = PROJECT_ROOT / "data" / "processed"

DATA_DIR.mkdir(parents=True, exist_ok=True)

CPI_FILE = RAW_DIR / "cpi.csv"


# ---------------------------------------------------------
# 주기별 설정
#   cycle      1년이 몇 칸인가 (계절 평년값의 칸 수)
#   unit_days  시간 축 한 칸이 며칠인가 (시차 계산용)
#   max_lag    시차를 몇 칸까지 볼지
#   min_obs    상품당 최소 관측 수
#   span       싼 시기·비싼 시기를 몇 칸 묶음으로 볼지
# ---------------------------------------------------------

FREQ = {
    "week": {
        "label": "주별",
        "unit": "주",
        "files": ["price_weather_weekly.parquet", "price_weather_weekly.csv"],
        "cycle": 52, "max_lag": 8, "min_obs": 52, "span": 4,
        "min_years_per_slot": 3,
    },
    "month": {
        "label": "월별",
        "unit": "달",
        "files": ["price_weather_monthly.parquet", "price_weather_monthly.csv"],
        "cycle": 12, "max_lag": 3, "min_obs": 24, "span": 1,
        "min_years_per_slot": 3,
    },
    "day": {
        "label": "일별",
        "unit": "일",
        "files": ["price_day.parquet", "price_day.csv"],
        # span 은 '계절 칸' 단위다. 일별의 계절 칸은 날짜가 아니라 주차이므로
        # 4 는 4주를 뜻한다. 28 로 두면 28주(반년)를 뭉개 싼 시기가 어긋난다.
        "cycle": 52, "max_lag": 28, "min_obs": 200, "span": 4,
        "min_years_per_slot": 3,
    },
}


# 상품을 가르는 기준
PRODUCT_KEYS = ["item_name", "variety_name", "grade_name",
                "retail_unit_size", "retail_unit_name"]

# 없어도 되는 상품 키 — 파일에 없으면 "-" 로 채운다
OPTIONAL_KEYS = {"grade_name", "retail_unit_size", "retail_unit_name", "variety_name"}

TEMP_COL = "avg_tmp"
RAIN_COL = "precip"

MIN_PAIRS = 30
EXTREME_Q = 0.95
EVENT_WINDOW_RATIO = 4      # 시차 단위로 몇 칸을 사건 창으로 볼지 (주=4주, 월=4달, 일=28일)

MAX_PRODUCTS = 120

# --- Q2 전용 판정선 ---
#
#   Q2 는 계절을 걷어내지 않고 상대가격 그대로 기상과 비교한다.
#   계절이 살아 있으면 상관의 절대값이 부풀어 오르므로
#   이탈도에 쓰던 0.2 / 0.3 을 그대로 쓰면 거의 모든 상품이 '뚜렷' 이 된다.
#   그래서 한 단계 높여 잡는다. 목록이 너무 길거나 너무 짧으면 여기를 고친다.
Q2_WEAK_LINE = 0.35
Q2_STRONG_LINE = 0.50

#   화면(json)에 실을 Q2 상품 수 상한. 잘린 상품도 q2_weather_<주기>.csv 에는 전부 있다.
MAX_Q2_PRODUCTS = 300

# --- Q1 '뚜렷한 계절 패턴' 으로 볼 계절 진폭 ---
#
#   진폭 0.50 = 1년 사이 전체 기간 중앙값 대비 50%p 넘게 오르내림.
#
#   0.50 으로 정한 근거 (16_amplitude_dist.py 로 실제 분포를 뽑아 정했다)
#     · 세 주기 모두 상위 22~29% 가 걸린다 (일 29% · 주 26% · 월 22%)
#       — 주기를 갈아 끼워도 '뚜렷' 의 뜻이 흔들리지 않는다.
#     · 상위 25% 분위수(일 0.574 · 주 0.547 · 월 0.434)와 거의 같은 자리다.
#     · 예전 값 0.20 은 일별 67% · 주별 60% 가 걸려 아무것도 가르지 못했고,
#       그 경계에 쇠고기 · 계란 · 건오징어 같은 비계절 품목이 놓였다.
#
#   물가상승을 걷어내지 않으므로 10년치 물가 추세가 진폭에 섞여 들어간다.
Q1_STRONG_AMPLITUDE = 0.50


# ---------------------------------------------------------
# 컬럼 이름 자동 인식
#   팀원이 만든 파일은 컬럼 이름이 다를 수 있다.
#   한글·영문 어느 쪽이든 받아서 표준 이름으로 바꾼다.
#
#   주의: '년월' 은 '년' 과 '월' 두 별칭에 모두 걸린다.
#         그래서 정확히 일치하는 이름을 먼저 찾고,
#         한 컬럼이 두 자리를 차지하지 못하게 막는다.
# ---------------------------------------------------------

ALIASES = {
    "date":             ["date", "날짜", "일자", "가격등록일자", "조사일자"],
    "year":             ["year", "연도", "년도", "년"],
    "month":            ["month", "월"],
    "day":              ["day", "일"],
    "week":             ["week", "주", "주차"],
    "period":           ["period", "시점", "년월", "연월", "기간"],
    "sido_name":        ["sido_name", "시도명", "시도", "지역", "지역명"],
    "item_name":        ["item_name", "품목명", "품목"],
    "variety_name":     ["variety_name", "품종명", "품종"],
    "grade_name":       ["grade_name", "산물등급명", "등급명", "등급"],
    "market_type_code": ["market_type_code", "도소매조사구분코드", "도소매구분"],
    "price":            ["price", "품목가격", "평균가격", "소매가격", "가격"],
    "retail_unit_size": ["retail_unit_size", "소매출하단위크기", "단위크기"],
    "retail_unit_name": ["retail_unit_name", "소매출하단위명", "단위명", "단위"],
    "avg_tmp":          ["avg_tmp", "avg_temp", "평균기온"],
    "min_avgtmp":       ["min_avgtmp", "min_temp", "평균최저기온"],
    "max_avgtmp":       ["max_avgtmp", "max_temp", "평균최고기온"],
    "precip":           ["precip", "precipitation", "rain", "강수량"],
    "location":         ["location", "지점", "지점명", "관측소"],
}


def resolve_columns(columns, want=None, quiet=False):
    """실제 컬럼명 -> 표준 이름 매핑을 만든다.

    1) 정확히 일치하는 것을 먼저 잡는다  ('월' == '월')
    2) 남은 것만 부분 일치로 잡는다      ('평균기온(℃)' 안에 '평균기온')
    3) 한 컬럼이 두 자리를 차지하지 못하게 한다
    """

    cols = [str(c).strip() for c in columns]
    lowered = {c: c.lower() for c in cols}

    mapping = {}      # 실제컬럼 -> 표준이름
    taken = set()     # 이미 자리를 잡은 표준이름

    targets = want or list(ALIASES)

    # 1단계 — 정확히 일치
    for std in targets:
        for alias in ALIASES[std]:
            hit = next((c for c in cols
                        if c not in mapping and lowered[c] == alias.lower()), None)
            if hit:
                mapping[hit] = std
                taken.add(std)
                break

    # 2단계 — 부분 일치 (긴 별칭부터: '평균최저기온' 이 '평균기온' 보다 먼저)
    for std in targets:
        if std in taken:
            continue
        for alias in sorted(ALIASES[std], key=len, reverse=True):
            hit = next((c for c in cols
                        if c not in mapping and alias.lower() in lowered[c]), None)
            if hit:
                mapping[hit] = std
                taken.add(std)
                break

    if not quiet:
        renamed = {k: v for k, v in mapping.items() if k != v}
        if renamed:
            print("  컬럼 인식:", ", ".join(f"{k} -> {v}" for k, v in renamed.items()))

    return mapping


# ---------------------------------------------------------
# 도우미
# ---------------------------------------------------------

def read_any(paths, what):
    """parquet 을 먼저, 없거나 못 읽으면 csv 를 읽는다."""

    for path in paths:

        if not path.exists():
            continue

        try:
            if path.suffix == ".parquet":
                return pd.read_parquet(path), path

            return pd.read_csv(path, encoding="utf-8-sig", low_memory=False), path

        except UnicodeDecodeError:
            for enc in ("cp949", "euc-kr"):
                try:
                    return pd.read_csv(path, encoding=enc, low_memory=False), path
                except UnicodeDecodeError:
                    continue

        except Exception as err:
            print(f"  ({path.name} 읽기 실패: {err})")

    raise FileNotFoundError(
        f"{what} 을(를) 못 찾았습니다.\n  찾은 곳: "
        + "\n            ".join(str(p) for p in paths))


def read_csv_any(path, **kwargs):

    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs)
        except UnicodeDecodeError:
            continue

    raise RuntimeError(f"인코딩 판별 실패: {path.name}")


def corr_of(x, y):
    """짝이 충분하고 둘 다 변할 때만 상관을 낸다."""

    pair = pd.DataFrame({"x": np.asarray(x, dtype=float),
                         "y": np.asarray(y, dtype=float)}).dropna()

    if len(pair) < MIN_PAIRS or pair["x"].nunique() < 2 or pair["y"].nunique() < 2:
        return np.nan

    return pair["x"].corr(pair["y"])


def r2(value, digits=3):
    """JSON 에 NaN 을 넣으면 브라우저가 못 읽는다."""

    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    return round(float(value), digits)


MONTH_NAME = ["1월", "2월", "3월", "4월", "5월", "6월",
              "7월", "8월", "9월", "10월", "11월", "12월"]


def circular_rolling(values, span):
    """계절 칸을 원형으로 보고 이동평균을 낸다.

    1년은 고리다. 12월 다음은 1월이다.
    그냥 rolling 하면 연초·연말이 잘려 나가,
    싼 시기가 겨울에 걸친 품목(배추 등)의 최저점을 놓친다.

    앞뒤로 한 바퀴씩 이어 붙여 굴린 뒤 가운데만 되돌린다.
    """

    if span <= 1 or len(values) < span:
        return values

    arr = values.to_numpy(dtype=float)
    triple = np.concatenate([arr, arr, arr])

    rolled = pd.Series(triple).rolling(span, min_periods=span).mean().to_numpy()

    middle = rolled[len(arr):2 * len(arr)]

    return pd.Series(middle, index=values.index)


def wa_gwa(word):
    """받침이 있으면 '과', 없으면 '와'. ('12월과' / '52주차와')"""

    if not word:
        return "와"

    last = word[-1]

    if "가" <= last <= "힣":
        return "과" if (ord(last) - 0xAC00) % 28 else "와"

    return "와"


def slot_to_month(slot, cycle):
    """계절 칸 번호를 대략의 월로 — 달력 표시에만 쓴다."""

    if cycle == 12:
        return int(min(12, max(1, slot)))

    return int(min(12, max(1, (slot - 1) // 4.345 + 1)))


# ---------------------------------------------------------
# 물가지수 읽기 — 세로형·가로형 모두 받는다
# ---------------------------------------------------------

def load_cpi():
    """연도별 평균 물가지수를 돌려준다. 못 읽으면 (None, 사유)."""

    if not CPI_FILE.exists():
        return None, (f"{CPI_FILE.name} 이 없습니다. "
                      f"KOSIS 소비자물가지수를 {CPI_FILE} 로 두세요.")

    cpi = read_csv_any(CPI_FILE)
    cpi.columns = [str(c).strip().strip('"') for c in cpi.columns]

    # --- 가로형인가? ---
    #   "시도별", 2016.01, 2016.02, ... 처럼 시점이 컬럼으로 눕는 형태.
    #   KOSIS 에서 받으면 보통 이 모양이다.
    ym_cols = [c for c in cpi.columns
               if pd.Series([c]).str.match(r"^\D*\d{4}[.\-/]?\d{0,2}\D*$").iloc[0]
               and len(''.join(ch for ch in c if ch.isdigit())) >= 4]

    if len(ym_cols) >= 12:

        print(f"  가로형으로 읽습니다 (시점 컬럼 {len(ym_cols)}개)")

        # 지역 컬럼이 있으면 '전국' 행을 고른다
        label_cols = [c for c in cpi.columns if c not in ym_cols]
        row = cpi

        if label_cols:
            first = label_cols[0]
            national = cpi[cpi[first].astype(str).str.contains("전국", na=False)]

            if len(national):
                row = national
                print(f"  '{first}' 에서 전국 행을 골랐습니다")
            else:
                row = cpi.head(1)
                print(f"  '전국' 행이 없어 첫 행({cpi[first].iloc[0]})을 씁니다")

        long = row[ym_cols].iloc[0]

        frame = pd.DataFrame({"_period": ym_cols, "_value": long.to_numpy()})

    else:
        # --- 세로형 ---
        mapping = resolve_columns(
            cpi.columns, want=["period", "year", "month"], quiet=True)

        inv = {v: k for k, v in mapping.items()}

        value_col = None
        for hint in ("총지수", "소비자물가지수", "물가지수", "지수", "cpi", "value", "index"):
            hit = next((c for c in cpi.columns
                        if c not in mapping and hint in str(c).lower()), None)
            if hit:
                value_col = hit
                break

        if value_col is None:
            # 남은 숫자 컬럼 하나를 값으로 본다
            spare = [c for c in cpi.columns if c not in mapping]
            value_col = spare[0] if spare else None

        if value_col is None:
            return None, f"물가지수 값 컬럼을 못 찾았습니다: {cpi.columns.tolist()}"

        print(f"  세로형으로 읽습니다 (값 컬럼: {value_col})")

        y, m, p = inv.get("year"), inv.get("month"), inv.get("period")

        if y and m and y != m:
            print(f"  시점: {y} + {m} (연·월 분리)")
            frame = pd.DataFrame({"_year": pd.to_numeric(cpi[y], errors="coerce"),
                                  "_value": cpi[value_col]})
            frame["_period"] = None

        else:
            ym = p or y or m

            if ym is None:
                return None, f"시점 컬럼을 못 찾았습니다: {cpi.columns.tolist()}"

            print(f"  시점: {ym}")
            frame = pd.DataFrame({"_period": cpi[ym].astype(str),
                                  "_value": cpi[value_col]})

    # --- 연도 뽑기 ---
    if "_year" not in frame.columns or frame["_year"].isna().all():
        digits = frame["_period"].astype(str).str.replace(r"\D", "", regex=True)
        frame["_year"] = pd.to_numeric(digits.str[:4], errors="coerce")

    frame["_value"] = pd.to_numeric(
        frame["_value"].astype(str).str.replace(",", "").str.strip(), errors="coerce")

    frame = frame.dropna(subset=["_year", "_value"])

    if frame.empty:
        return None, "물가지수를 읽었지만 쓸 수 있는 행이 없습니다."

    frame["_year"] = frame["_year"].astype(int)

    counts = frame.groupby("_year").size()
    yearly = frame.groupby("_year")["_value"].mean()

    print(f"  물가지수 {len(frame):,}행 → 연평균 {len(yearly)}개 연도 "
          f"({yearly.index.min()}~{yearly.index.max()})")

    # 달이 덜 찬 해는 연평균이 계절에 치우친다.
    partial = counts[(counts > 1) & (counts < 12)]

    if len(partial):
        for y, n in partial.items():
            print(f"  [주의] {y}년은 {n}개월치뿐입니다. 연평균이 계절에 치우칩니다.")

    return (yearly, counts), None


# ---------------------------------------------------------
# 본체 — 주기 하나를 분석한다
# ---------------------------------------------------------

def run(freq, cpi_pack):

    cfg = FREQ[freq]
    cycle = cfg["cycle"]
    unit = cfg["unit"]
    max_lag = cfg["max_lag"]
    min_obs = cfg["min_obs"]
    span = cfg["span"]
    min_years = cfg["min_years_per_slot"]
    event_window = cfg["max_lag"] if freq != "week" else EVENT_WINDOW_RATIO

    out_json = DATA_DIR / f"dashboard_data_{freq}.json"
    q_files = {q: DATA_DIR / f"q{q}_{name}_{freq}.csv"
               for q, name in ((1, "season"), (2, "weather"),
                               (3, "inflation"), (4, "position"))}

    print("\n" + "=" * 70)
    print(f"[{cfg['label']}] 데이터 읽기")
    print("=" * 70)

    data, source = read_any([DATA_DIR / f for f in cfg["files"]],
                            f"{cfg['label']} 결합 데이터")

    print(f"입력: {source.name}  {len(data):,}행 × {len(data.columns)}컬럼")

    # --- 컬럼 이름 맞추기 ---
    mapping = resolve_columns(data.columns)
    data = data.rename(columns=mapping)

    # 같은 표준 이름으로 두 컬럼이 들어오면 앞의 것만 남긴다
    data = data.loc[:, ~data.columns.duplicated()]

    missing = [k for k in PRODUCT_KEYS + ["price"]
               if k not in data.columns and k not in OPTIONAL_KEYS]

    if missing:
        raise KeyError(
            f"{cfg['label']} 파일에 꼭 필요한 컬럼이 없습니다: {missing}\n"
            f"  실제 컬럼: {list(data.columns)}\n"
            f"  ALIASES 에 이 파일의 컬럼명을 추가하세요.")

    for key in PRODUCT_KEYS:
        if key not in data.columns:
            print(f"  [주의] {key} 가 없어 '-' 로 채웁니다. 상품 구분이 거칠어집니다.")
            data[key] = "-"

    has_weather = TEMP_COL in data.columns and RAIN_COL in data.columns

    if not has_weather:
        print(f"  [주의] 기상 컬럼이 없어 Q2 를 건너뜁니다.")

    # 쓰지 않는 컬럼은 여기서 버린다.
    #   일별 파일은 수백만 행이라 컬럼 하나가 수십 MB 다.
    #   sido_name 은 전국 중앙값으로 줄이면서 사라지므로 들고 갈 필요가 없다.
    keep = set(PRODUCT_KEYS) | {"year", "month", "day", "week", "date", "period",
                                "price", TEMP_COL, RAIN_COL}

    drop = [c for c in data.columns if c not in keep]

    if drop:
        print(f"  분석에 안 쓰는 컬럼 {len(drop)}개 제외: {drop}")
        data = data.drop(columns=drop)

    data = data.copy()

    for col in PRODUCT_KEYS:
        data[col] = data[col].astype(object).where(data[col].notna(), "-").astype(str)

    # --- 시점 만들기 ---
    #   date 가 있으면 그것으로, 없으면 year·month(·week) 로 만든다.
    if "date" in data.columns:
        data["date"] = pd.to_datetime(data["date"], errors="coerce")

    elif {"year", "month", "day"} <= set(data.columns):
        # year·month·day 가 따로 있는 파일 (팀원이 만든 price_day.csv 가 이 모양)
        print("  날짜: year + month + day 로 조립")
        data["date"] = pd.to_datetime(
            dict(year=pd.to_numeric(data["year"], errors="coerce"),
                 month=pd.to_numeric(data["month"], errors="coerce"),
                 day=pd.to_numeric(data["day"], errors="coerce")),
            errors="coerce")

    elif "period" in data.columns:
        data["date"] = pd.to_datetime(
            data["period"].astype(str).str.replace(r"\D", "", regex=True).str[:6],
            format="%Y%m", errors="coerce")

    else:
        data["date"] = pd.NaT

    for col in ("year", "month", "week"):
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")

    if "year" not in data.columns or data["year"].isna().all():
        data["year"] = data["date"].dt.year

    if "month" not in data.columns or data["month"].isna().all():
        data["month"] = data["date"].dt.month

    data["price"] = pd.to_numeric(data["price"], errors="coerce")
    data = data.dropna(subset=["year", "price"])
    data["year"] = data["year"].astype(int)

    # --- 계절 칸(slot) 과 시간 축(t) ---
    day_base = None

    if freq == "month":
        data = data.dropna(subset=["month"])
        data["slot"] = data["month"].clip(1, 12).astype(int)
        base = int(data["year"].min())
        data["t"] = (data["year"] - base) * 12 + data["slot"]

    elif freq == "week":
        if "week" not in data.columns or data["week"].isna().all():
            if data["date"].isna().all():
                raise KeyError("주차를 만들 수 없습니다. week 또는 date 컬럼이 필요합니다.")
            data["week"] = data["date"].dt.isocalendar().week.astype(int)

        data = data.dropna(subset=["week"])
        data["slot"] = data["week"].clip(upper=52).astype(int)
        base = int(data["year"].min())
        data["t"] = (data["year"] - base) * 52 + data["slot"]

    else:  # day
        if data["date"].isna().all():
            raise KeyError(
                "일별 분석에는 날짜가 필요합니다. "
                "date(날짜·일자·가격등록일자) 컬럼 하나가 있거나, "
                "year + month + day 세 컬럼이 함께 있어야 합니다.")

        data = data.dropna(subset=["date"])
        data["slot"] = data["date"].dt.isocalendar().week.clip(upper=52).astype(int)
        base_date = data["date"].min()
        data["t"] = (data["date"] - base_date).dt.days
        day_base = base_date          # Q4 에서 실제 날짜를 되살릴 때 쓴다

        if "month" not in data.columns or data["month"].isna().all():
            data["month"] = data["date"].dt.month

    # --- 전국 대표값으로 줄이기 ---
    agg = {"price": ("price", "median")}

    if has_weather:
        agg["temp"] = (TEMP_COL, "mean")
        agg["rain"] = (RAIN_COL, "mean")

    series = (data.groupby(PRODUCT_KEYS + ["year", "slot", "t"], observed=True)
              .agg(**agg).reset_index())

    print(f"전국 {cfg['label']}로 줄임: {len(data):,}행 → {len(series):,}행")

    # --- 가격지수 만들기 (물가상승은 걷어내지 않는다) ---
    #
    #   상품마다 단위가 달라(배추 1포기 4천원 · 쌀 20kg 5만원) 원 단위 그대로는
    #   서로 견줄 수 없다. 그래서 그 상품의 '전체 기간 중앙값' 으로 한 번 나눠
    #   1.00 기준의 지수로 만든다.
    #
    #   ★ 해마다 다른 값으로 나누면(연도별 중앙값) 물가상승이 지워진다.
    #     여기서는 기간 전체에 걸쳐 '같은 수' 하나로 나누므로 물가상승이 그대로 남는다.
    #     2016년 값은 1.00 아래, 2025년 값은 1.00 위에 몰리는 게 정상이다.
    #     Q1 · Q2 · Q4 가 이 값을 쓴다. (Q3 만 원 단위 price 와 물가지수를 쓴다.)
    all_median = (series.groupby(PRODUCT_KEYS, observed=True)["price"]
                  .transform("median"))

    series["price_idx"] = series["price"] / all_median.replace(0, np.nan)
    series = series.dropna(subset=["price_idx"])

    sizes = series.groupby(PRODUCT_KEYS, observed=True)["price"].transform("size")
    thin_products = (sizes < min_obs).sum()
    series = series[sizes >= min_obs]

    if series.empty:
        print(f"[중단] 관측 {min_obs}{unit} 이상인 상품이 없습니다. "
              f"FREQ['{freq}']['min_obs'] 를 낮추세요.")
        return None

    if thin_products:
        print(f"관측 {min_obs}{unit} 미만이라 제외: {thin_products:,}행")

    series["pkey"] = series[PRODUCT_KEYS].astype(str).agg(" | ".join, axis=1)

    n_products = series["pkey"].nunique()

    print(f"분석 대상: 상품 {n_products:,}개 / 품목 {series['item_name'].nunique():,}개")
    print(f"기간: {series['year'].min()}년 ~ {series['year'].max()}년")

    # --- 계절 평년값 ---
    print(f"\n[{cfg['label']}] 계절 평년값 ({cycle}칸)")

    season = (series.groupby(["pkey", "slot"], observed=True)
              .agg(p10=("price_idx", lambda s: s.quantile(0.10)),
                   p50=("price_idx", "median"),
                   p90=("price_idx", lambda s: s.quantile(0.90)),
                   years=("year", "nunique"))
              .reset_index())

    thin = season["years"] < min_years
    print(f"  평년값 {len(season):,}칸 / 관측 {min_years}년 미만 제외 {thin.sum():,}칸")

    season = season[~thin]

    # 평년값을 낼 수 있는 칸(관측 min_years 년 이상)만 남긴다.
    # inner join 이 그 몫을 한다. 이탈도(anomaly)는 이제 쓰지 않으므로 만들지 않는다.
    series = series.merge(season[["pkey", "slot", "p50"]], on=["pkey", "slot"], how="inner")

    if series.empty:
        print("[중단] 평년값과 결합한 뒤 남은 행이 없습니다.")
        return None

    info = (series.groupby("pkey", observed=True)
            .agg(**{k: (k, "first") for k in PRODUCT_KEYS},
                 n=("price", "size"), years=("year", "nunique"),
                 price_med=("price", "median"))
            .reset_index())

    result = {"freq": freq, "cfg": cfg, "series": series, "season": season,
              "day_base": day_base,
              "info": info, "cycle": cycle, "unit": unit,
              "max_lag": max_lag, "span": span, "min_obs": min_obs,
              "event_window": event_window, "has_weather": has_weather,
              "n_products": n_products, "out_json": out_json, "q_files": q_files,
              "min_years": min_years}

    return result


# ---------------------------------------------------------
# Q1 — 계절 패턴
# ---------------------------------------------------------

def analyze_q1(R):

    cfg, cycle, span = R["cfg"], R["cycle"], R["span"]
    season, info = R["season"], R["info"]

    print(f"\n[{cfg['label']}] Q1  계절 패턴")

    rows, products = [], []
    need = max(6, cycle // 4)

    for pkey, prof in season.groupby("pkey", observed=True):

        prof = prof.sort_values("slot")

        if len(prof) < need:
            continue

        p50 = prof.set_index("slot")["p50"]
        amplitude = float(p50.max() - p50.min())

        roll = circular_rolling(p50, span)

        if roll.notna().sum() == 0:
            continue

        cheap_slot, dear_slot = int(roll.idxmin()), int(roll.idxmax())
        cheap_val, dear_val = float(roll.min()), float(roll.max())

        saving = (dear_val - cheap_val) / dear_val * 100 if dear_val else np.nan

        row = info[info["pkey"] == pkey]

        if row.empty:
            continue

        row = row.iloc[0]

        cheap_month = slot_to_month(cheap_slot, cycle)
        dear_month = slot_to_month(dear_slot, cycle)

        rows.append({"pkey": pkey, **{k: row[k] for k in PRODUCT_KEYS},
                     "n": int(row["n"]), "years": int(row["years"]),
                     "amplitude": round(amplitude, 3),
                     "cheap_month": cheap_month, "dear_month": dear_month,
                     "saving_pct": round(saving, 1) if pd.notna(saving) else None})

        products.append({
            "pkey": pkey, "item": str(row["item_name"]),
            "variety": str(row["variety_name"]), "grade": str(row["grade_name"]),
            "unit": f"{row['retail_unit_size']} {row['retail_unit_name']}",
            "n": int(row["n"]), "priceMed": r2(row["price_med"], 0),
            "amplitude": round(amplitude, 3),
            "cheapMonth": cheap_month, "dearMonth": dear_month,
            "savingPct": round(saving, 1) if pd.notna(saving) else None,
            "slots": [int(s) for s in prof["slot"]],
            "p10": [r2(v) for v in prof["p10"]],
            "p50": [r2(v) for v in prof["p50"]],
            "p90": [r2(v) for v in prof["p90"]]})

    q1 = pd.DataFrame(rows)

    if q1.empty:
        print("  계절 프로파일을 만들 수 있는 상품이 없습니다.")
        return None, [], [], None

    q1 = q1.sort_values("amplitude", ascending=False)
    q1.to_csv(R["q_files"][1], index=False, encoding="utf-8-sig")

    strong = q1[q1["amplitude"] >= Q1_STRONG_AMPLITUDE]

    print(f"  상품 {len(q1):,}개 · 진폭 {Q1_STRONG_AMPLITUDE} 이상 {len(strong):,}개 "
          f"({len(strong) / len(q1) * 100:.0f}%) · 중앙값 {q1['amplitude'].median():.3f}")

    for _, r in q1.head(5).iterrows():
        print(f"    {f'{r.item_name}/{r.variety_name}'[:20]:<20} 진폭 {r['amplitude']:>5.2f} "
              f"싼 달 {MONTH_NAME[r['cheap_month'] - 1]:<4} "
              f"비싼 달 {MONTH_NAME[r['dear_month'] - 1]:<4} {r['saving_pct']:>5.1f}%")

    # 품목 달력 — 품목마다 관측이 가장 많은 상품
    rep = info.sort_values("n", ascending=False).groupby("item_name", observed=True).head(1)

    calendar = []

    for _, r in rep.iterrows():

        prof = season[season["pkey"] == r["pkey"]]

        if len(prof) < need:
            continue

        prof = prof.assign(month=[slot_to_month(s, cycle) for s in prof["slot"]])
        by_month = prof.groupby("month")["p50"].mean()

        values = [r2(by_month.get(m)) for m in range(1, 13)]

        if sum(v is not None for v in values) < 8:
            continue

        calendar.append({"item": str(r["item_name"]),
                         "variety": str(r["variety_name"]),
                         "grade": str(r["grade_name"]),
                         "unit": f"{r['retail_unit_size']} {r['retail_unit_name']}",
                         "months": values})

    calendar.sort(key=lambda d: -max((v for v in d["months"] if v is not None), default=0))

    print(f"  계절 달력 품목 {len(calendar)}개")

    return q1, products, calendar, strong


# ---------------------------------------------------------
# Q2 — 기온·강수량
#
#   ★ 계절을 걷어내지 않고 비교합니다.
#
#     이 단계에서 쓰는 값은 '이탈도' 가 아니라 '상대가격' 입니다.
#
#         상대가격 = 그 시점 가격 ÷ 그 해 그 상품의 중앙값
#
#     물가상승만 걷어내고 계절은 그대로 둔 값입니다.
#     여름에 기온이 높고 여름 배추가 비싸면 그 관계가 그대로 잡힙니다.
#     "그 해 날씨가 유별나서" 가 아니라 "실제 가격이 기온과 함께 움직였는가" 를
#     묻는 것이라, 계절이 만든 동행도 관계에 포함해 셉니다.
#
#     대신 계절이 살아 있으면 상관의 절대값이 크게 나옵니다.
#     그래서 판정선을 이탈도 때(0.2 / 0.3)보다 높게 잡습니다
#     (Q2_WEAK_LINE / Q2_STRONG_LINE).
#
#     해석할 때는 '계절이 둘을 함께 움직였을 수 있다' 를 반드시 함께 적습니다.
# ---------------------------------------------------------

def analyze_q2(R):

    if not R["has_weather"]:
        return {"available": False}, None

    cfg, unit, max_lag = R["cfg"], R["unit"], R["max_lag"]
    series, info = R["series"], R["info"]

    print(f"\n[{cfg['label']}] Q2  기온·강수량과의 관계  (계절 포함)")

    wx = series.dropna(subset=["temp", "rain"])

    if wx.empty:
        print("  기상 값이 전부 비어 있습니다.")
        return {"available": False}, None

    # 전체를 한 덩어리로 묶은 값. 품목마다 방향이 달라 대개 상쇄된다.
    # 품목별로 봐야 보인다는 것을 보여 주는 용도다.
    temp_all = corr_of(wx["temp"], wx["price_idx"])
    rain_all = corr_of(wx["rain"], wx["price_idx"])

    print(f"  기온 vs 가격지수 {temp_all:+.3f} · 강수 vs 가격지수 {rain_all:+.3f}"
          f"   ← 전체 한 덩어리 (상쇄되어 작게 나오는 게 정상)")

    rows = []

    for pkey, sub in wx.groupby("pkey", observed=True):

        if len(sub) < R["min_obs"]:
            continue

        s = sub.sort_values("t").set_index("t")
        s = s[~s.index.duplicated()]

        rec = {"pkey": pkey, "n": len(sub)}

        for lag in range(max_lag + 1):

            # 기상이 lag 만큼 앞선다 — 그 시점 기상 vs lag 뒤 가격
            target = s["price_idx"].reindex(s.index + lag)

            for name in ("temp", "rain"):
                rec[f"{name}_lag{lag}"] = r2(
                    corr_of(s[name].to_numpy(), target.to_numpy()))

        rows.append(rec)

    q2 = pd.DataFrame(rows)

    if q2.empty:
        print("  상관을 낼 수 있는 상품이 없습니다.")
        return {"available": False}, None

    for name in ("temp", "rain"):

        cols = [f"{name}_lag{k}" for k in range(max_lag + 1)]

        # 시차를 밀면 짝이 모자라 한 상품의 모든 시차가 NaN 이 될 수 있다.
        # 그 행까지 idxmax 에 넘기면 pandas 가 ValueError 를 낸다.
        #   ValueError: Encountered all NA values
        # 값이 하나라도 있는 행만 골라 넘긴다.
        have = q2[cols].notna().any(axis=1)

        best = pd.Series(index=q2.index, dtype=object)

        if have.any():
            best.loc[have] = q2.loc[have, cols].abs().idxmax(axis=1)

        if (~have).any():
            print(f"  {name}: 시차 상관이 전부 비어 판정 못 한 상품 {(~have).sum():,}개")

        # 판정 못 한 상품이 하나라도 있으면 컬럼이 object 타입이 된다.
        # 그대로 두면 바로 다음 줄 .abs() 가 None 에서 터진다.
        #   TypeError: bad operand type for abs(): 'NoneType'
        # 숫자형으로 못 박아 두면 판정 못 한 자리는 NaN 이 되고,
        # NaN 은 비교에서 조용히 False 가 되어 뒤가 전부 안전해진다.
        q2[f"{name}_best_lag"] = pd.to_numeric(
            pd.Series([int(str(c).replace(f"{name}_lag", "")) if isinstance(c, str) else None
                       for c in best], index=q2.index), errors="coerce")

        q2[f"{name}_best_corr"] = pd.to_numeric(
            pd.Series([q2.loc[i, c] if isinstance(c, str) else None
                       for i, c in best.items()], index=q2.index), errors="coerce")

    # 기온·강수 중 더 센 쪽으로 그 상품의 '관계 세기' 를 정한다.
    # 기온만 보면 비에만 반응하는 품목(장마 피해)이 통째로 빠진다.
    q2["best_abs"] = q2[["temp_best_corr", "rain_best_corr"]].abs().max(axis=1)

    q2 = q2.merge(info[["pkey"] + PRODUCT_KEYS], on="pkey", how="left")
    q2 = q2.sort_values("best_abs", ascending=False, na_position="last")
    q2.to_csv(R["q_files"][2], index=False, encoding="utf-8-sig")

    weak = q2[q2["best_abs"] >= Q2_WEAK_LINE]
    strong = q2[q2["best_abs"] >= Q2_STRONG_LINE]

    print(f"  판정선(계절 포함) 약함 {Q2_WEAK_LINE} · 뚜렷 {Q2_STRONG_LINE}")
    print(f"  상품 {len(q2):,}개 · 뚜렷 {len(strong):,}개 · 약하지만 있음 {len(weak):,}개")

    if len(strong):
        lag_med = strong[["temp_best_lag", "rain_best_lag"]].min(axis=1).median()
        print(f"  뚜렷한 상품의 반응 시차 중앙값 {lag_med:.0f}{unit}")

    # 극단 기상
    ww = (wx.groupby(["year", "slot", "t"], observed=True)
          .agg(temp=("temp", "first"), rain=("rain", "first")).reset_index())

    hot_line = float(ww["temp"].quantile(EXTREME_Q))
    wet_line = float(ww["rain"].quantile(EXTREME_Q))
    window = R["event_window"]

    events = {"폭염": [], "호우": []}

    for label, frame in (("폭염", ww[ww["temp"] >= hot_line]),
                         ("호우", ww[ww["rain"] >= wet_line])):

        acc = []

        for _, ev in frame.iterrows():
            win = wx[(wx["t"] >= ev["t"]) & (wx["t"] <= ev["t"] + window)]

            if win.empty:
                continue

            # 여기서도 계절을 걷어내지 않는다.
            # 상대가격 평균이 1.10 이면 '그 해 평균보다 10% 비쌌다' 는 뜻이다.
            for item, value in win.groupby("item_name", observed=True)["price_idx"].mean().items():
                acc.append({"item": item, "rel": value})

        if not acc:
            continue

        summ = (pd.DataFrame(acc).groupby("item")["rel"]
                .agg(["mean", "size"]).reset_index())

        summ = summ[summ["size"] >= 3].sort_values("mean", ascending=False)

        events[label] = [{"item": str(r["item"]),
                          "pct": round((r["mean"] - 1) * 100, 1), "n": int(r["size"])}
                         for _, r in summ.head(12).iterrows()]

    print(f"  폭염 {hot_line:.1f}도 이상 / 호우 {wet_line:.1f}mm 이상 "
          f"(이후 {window}{unit} 관찰)")

    payload = {
        "available": True,

        # 화면이 "이 결과가 계절을 걷어낸 값인가" 를 구분하는 표시.
        # 옛 결과 파일에는 이 값이 없어서, 대시보드가 경고를 띄운다.
        "basis": "raw",

        "overall": {"temp": r2(temp_all), "rain": r2(rain_all)},
        "weakLine": Q2_WEAK_LINE, "strongLine": Q2_STRONG_LINE, "maxLag": max_lag,
        "counts": {"total": int(len(q2)), "weak": int(len(weak)),
                   "strong": int(len(strong))},
        "thresholds": {"hot": round(hot_line, 1), "wet": round(wet_line, 1),
                       "window": window},
        "events": events, "products": [], "cut": 0}

    return payload, q2


# ---------------------------------------------------------
# Q3 — 물가로 얼마나 설명되는가
# ---------------------------------------------------------

def analyze_q3(R, cpi_pack):

    cfg = R["cfg"]
    series = R["series"]

    print(f"\n[{cfg['label']}] Q3  물가로 얼마나 설명되는가")

    yearly_cpi, reason = cpi_pack

    if yearly_cpi is None:
        print(f"  {reason}")
        return {"available": False, "reason": reason}

    yearly_cpi, counts = yearly_cpi

    years = sorted(set(series["year"]) & set(yearly_cpi.index))

    if len(years) < 2:
        msg = "가격과 물가지수가 겹치는 해가 2개 미만입니다."
        print(f"  {msg}")
        return {"available": False, "reason": msg}

    y0, y1 = years[0], years[-1]

    # 끝 해가 덜 찼으면 계절에 치우친다. 완전한 해를 함께 알려 준다.
    note = ""
    full_years = [y for y in years if counts.get(y, 12) >= 12]

    if counts.get(y1, 12) < 12:
        note = (f"{y1}년 물가지수는 {int(counts.get(y1))}개월치뿐이라 "
                f"연평균이 계절에 치우칩니다.")
        print(f"  [주의] {note}")

        if full_years and full_years[-1] != y1:
            print(f"         12개월이 다 찬 마지막 해는 {full_years[-1]}년입니다.")

    cpi0, cpi1 = float(yearly_cpi[y0]), float(yearly_cpi[y1])
    cpi_growth = (cpi1 / cpi0 - 1) * 100

    print(f"  비교 구간 {y0} ~ {y1}  물가 {cpi_growth:+.1f}%")

    item_year = (series[series["year"].isin(years)]
                 .groupby(["item_name", "year"], observed=True)["price"]
                 .median().reset_index())

    rows = []

    for item, sub in item_year.groupby("item_name", observed=True):

        have = sub.set_index("year")["price"]

        if y0 not in have or y1 not in have or have[y0] <= 0:
            continue

        nominal = (have[y1] / have[y0] - 1) * 100
        real = ((have[y1] / (cpi1 / 100)) / (have[y0] / (cpi0 / 100)) - 1) * 100
        explained = (cpi_growth / nominal * 100) if nominal > 0 else None

        rows.append({"item_name": item,
                     "y0_price": round(float(have[y0]), 1),
                     "y1_price": round(float(have[y1]), 1),
                     "nominal_pct": round(nominal, 1),
                     "real_pct": round(real, 1),
                     "explained_pct": round(min(explained, 999), 1)
                     if explained is not None else None})

    q3 = pd.DataFrame(rows)

    if q3.empty:
        msg = "두 해 모두 관측된 품목이 없습니다."
        print(f"  {msg}")
        return {"available": False, "reason": msg}

    q3 = q3.sort_values("nominal_pct", ascending=False)
    q3.to_csv(R["q_files"][3], index=False, encoding="utf-8-sig")

    faster = q3[q3["real_pct"] > 0]

    print(f"  품목 {len(q3)}개 · 물가보다 더 오름 {len(faster)}개 "
          f"({len(faster) / len(q3) * 100:.0f}%)")
    print(f"  명목 중앙값 {q3['nominal_pct'].median():+.1f}% / "
          f"실질 중앙값 {q3['real_pct'].median():+.1f}%")

    for _, r in q3.head(5).iterrows():
        print(f"    {str(r['item_name']):<12} 명목 {r['nominal_pct']:>+7.1f}% "
              f"실질 {r['real_pct']:>+7.1f}%")

    return {
        "available": True, "y0": int(y0), "y1": int(y1),
        "cpiGrowth": round(cpi_growth, 1),
        "cpiSeries": [{"year": int(y), "cpi": round(float(yearly_cpi[y]), 1)}
                      for y in years],
        "partialNote": note,
        "medianNominal": round(float(q3["nominal_pct"].median()), 1),
        "medianReal": round(float(q3["real_pct"].median()), 1),
        "fasterCount": int(len(faster)), "totalItems": int(len(q3)),
        # r2() 를 거치는 이유
        #   explained_pct 는 명목이 내린 품목에서 None 이 된다.
        #   그런데 DataFrame 에 담기는 순간 None 은 NaN(실수)으로 바뀌고,
        #   json.dumps 는 그것을 표준이 아닌 NaN 리터럴로 적는다.
        #   그러면 화면에서 null 검사에 걸리지 않아 'NaN%' 가 그대로 찍힌다.
        #   r2() 로 통과시키면 제대로 null 이 되어 화면이 걸러낼 수 있다.
        "items": [{"item": str(r["item_name"]),
                   "nominal": r2(r["nominal_pct"], 1),
                   "real": r2(r["real_pct"], 1),
                   "explained": r2(r["explained_pct"], 1)}
                  for _, r in q3.iterrows()]}


# ---------------------------------------------------------
# Q4 — 지금 가격이 과거 분포의 어디인가
# ---------------------------------------------------------

def analyze_q4(R):

    cfg, unit = R["cfg"], R["unit"]
    series, info = R["series"], R["info"]

    print(f"\n[{cfg['label']}] Q4  가격 위치 (과거 같은 시기 대비)")

    info_by_key = info.set_index("pkey")

    last_t = int(series["t"].max())
    last_row = series[series["t"] == last_t].iloc[0]

    # 계절 칸(slot) 은 주별=주차, 월별=월, 일별=주차 다.
    # 일별에서 slot 을 '일' 이라고 부르면 틀린 말이 된다. 실제 날짜로 적는다.
    if R["freq"] == "day" and R["day_base"] is not None:
        as_of_date = R["day_base"] + pd.Timedelta(days=last_t)
        label = as_of_date.strftime("%Y-%m-%d")
        year_of = int(as_of_date.year)

    elif R["freq"] == "month":
        label = f"{int(last_row['year'])}년 {int(last_row['slot'])}월"
        year_of = int(last_row["year"])

    else:
        label = f"{int(last_row['year'])}년 {int(last_row['slot'])}주차"
        year_of = int(last_row["year"])

    compare = (f"{int(last_row['slot'])}월" if R["freq"] == "month"
               else f"{int(last_row['slot'])}주차")

    as_of = {"year": year_of, "slot": int(last_row["slot"]), "unit": unit,
             "label": label, "compare": compare}

    print(f"  기준 시점: {label}  (과거의 같은 {compare}{wa_gwa(compare)} 비교)")

    # 상품마다 전체를 훑으면 (상품 수 × 전체 행) 만큼 스캔한다.
    # 일별은 행이 수백만이라 그것만으로 몇 분이 걸린다.
    # 상품별 그룹을 한 번만 돌면서 그 안에서만 찾는다.
    tol = max(1, R["max_lag"] // 4)

    rows = []
    thin_past = 0

    for pkey, sub in series.groupby("pkey", observed=True):

        recent = sub[sub["t"] >= last_t - tol]

        if recent.empty:
            continue

        cur = recent.sort_values("t").iloc[-1]
        slot = int(cur["slot"])

        past = sub[(sub["slot"] == slot) & (sub["year"] < cur["year"])]

        # '최소 3년' 을 건수가 아니라 '서로 다른 해' 로 센다.
        #
        #   일별은 계절 칸이 주차라 한 해에 최대 7일이 들어온다.
        #   건수로 세면 한 해 자료 3일만 있어도 판정이 나가, 그 해가 유별났을 때
        #   "매우 비쌈" 이 근거 없이 찍힌다. 주별·월별은 한 해에 한 줄씩이라
        #   건수와 연수가 사실상 같아 이 변경의 영향을 거의 받지 않는다.
        past_years = int(past["year"].nunique())

        if past_years < R["min_years"]:
            thin_past += 1
            continue

        # 물가를 걷어내지 않는다 — 과거 같은 칸의 '그대로의 가격' 과 견준다.
        #
        #   ★ 물가가 오른 만큼 최근 값이 위쪽에 몰린다. 그래서 이 판정은
        #     "예년 이맘때보다 비싼가" 와 "10년 사이 물가가 올랐나" 를 섞어서 본다.
        #     화면에도 그 사실을 적어 둔다.
        #
        #   price_idx 는 price 를 상수 하나로 나눈 값이라 백분위는 원 가격과 같다.
        pos_pct = float((past["price"] < cur["price"]).mean() * 100)

        verdict = ("매우 비쌈" if pos_pct >= 90 else "비쌈" if pos_pct >= 70 else
                   "보통" if pos_pct >= 30 else "쌈" if pos_pct >= 10 else "매우 쌈")

        if pkey not in info_by_key.index:
            continue

        row = info_by_key.loc[pkey]

        rows.append({"pkey": pkey, **{k: row[k] for k in PRODUCT_KEYS},
                     "year": int(cur["year"]), "slot": slot,
                     "price": round(float(cur["price"]), 1),
                     "pos_pct": round(pos_pct, 1),
                     # past_n 은 '건수' 다. 일별은 계절 칸이 주차라 한 해에 여러 날이 들어와
                     # 45건처럼 나온다. 화면에 '45년' 으로 찍히면 안 되므로 연수를 따로 센다.
                     "past_n": int(len(past)),
                     "past_years": past_years,
                     "verdict": verdict})

    q4 = pd.DataFrame(rows)

    if q4.empty:
        print("  과거 분포와 비교할 수 있는 상품이 없습니다.")
        return {"available": False}, None

    q4 = q4.sort_values("pos_pct", ascending=False)
    q4.to_csv(R["q_files"][4], index=False, encoding="utf-8-sig")

    counts = q4["verdict"].value_counts()
    dear = int((q4["pos_pct"] >= 70).sum())

    if thin_past:
        print(f"  과거 같은 {compare} 자료가 {R['min_years']}개 연도 미만이라 판정 제외: {thin_past:,}개")

    print(f"  판단 가능 {len(q4):,}개 · " + " / ".join(
        f"{v} {int(counts.get(v, 0))}" for v in ("매우 비쌈", "비쌈", "보통", "쌈", "매우 쌈")))
    print(f"  위치 70 이상 {dear:,}개 ({dear / len(q4) * 100:.0f}%) "
          f"— 물가를 걷어내지 않아 최근 값이 위로 쏠린다")

    payload = {"available": True, "asOf": as_of,
               "counts": {v: int(counts.get(v, 0))
                          for v in ("매우 비쌈", "비쌈", "보통", "쌈", "매우 쌈")},
               "dearShare": round(dear / len(q4) * 100, 1), "products": []}

    return payload, q4


# ---------------------------------------------------------
# 저장 · 실행
# ---------------------------------------------------------

def finish(R, q1, q1_products, calendar, strong_season, q2_payload, q2,
           q3_payload, q4_payload, q4):

    cfg, series = R["cfg"], R["series"]

    q1_products.sort(key=lambda d: -d["n"])
    picked = q1_products[:MAX_PRODUCTS]
    picked_keys = {d["pkey"] for d in picked}
    dropped = len(q1_products) - len(picked)

    if dropped:
        print(f"\n[{cfg['label']}] 화면에는 관측이 많은 {len(picked):,}개만 넣습니다 "
              f"(나머지 {dropped:,}개는 csv 에).")

    if q2_payload.get("available") and q2 is not None:

        max_lag = R["max_lag"]

        # Q2 는 '전체 상품 중 뚜렷한 관계를 보이는 상품' 만 싣는다.
        #
        #   Q1·Q4 는 관측이 많은 상품 MAX_PRODUCTS 개(picked)로 자르지만
        #   Q2 는 그 목록에 매이지 않는다. 관측이 적어 잘린 상품에서
        #   뚜렷한 관계가 나오면 그것이야말로 봐야 할 상품이기 때문이다.
        strong_line = q2_payload["strongLine"]
        view = q2[q2["best_abs"] >= strong_line]

        # 뚜렷한 게 하나도 없으면 약한 것이라도 싣는다. 빈 화면보다 낫다.
        if view.empty:
            view = q2[q2["best_abs"] >= q2_payload["weakLine"]]
            q2_payload["listedLine"] = q2_payload["weakLine"]
            q2_payload["listedKind"] = "weak"
        else:
            q2_payload["listedLine"] = strong_line
            q2_payload["listedKind"] = "strong"

        q2_payload["cut"] = max(0, len(view) - MAX_Q2_PRODUCTS)
        view = view.head(MAX_Q2_PRODUCTS)

        if q2_payload["cut"]:
            print(f"[{cfg['label']}] Q2 목록은 상위 {MAX_Q2_PRODUCTS}개까지만 "
                  f"(나머지 {q2_payload['cut']:,}개는 csv 에).")

        q2_payload["products"] = [
            {"pkey": r["pkey"], "item": str(r["item_name"]),
             "variety": str(r["variety_name"]), "grade": str(r["grade_name"]),
             "unit": f"{r['retail_unit_size']} {r['retail_unit_name']}",
             "n": int(r["n"]),
             "tCorr": r2(r["temp_best_corr"]), "tLag": r["temp_best_lag"],
             "rCorr": r2(r["rain_best_corr"]), "rLag": r["rain_best_lag"],
             "tLags": [r2(r.get(f"temp_lag{k}")) for k in range(max_lag + 1)],
             "rLags": [r2(r.get(f"rain_lag{k}")) for k in range(max_lag + 1)]}
            for _, r in view.iterrows()]

        print(f"[{cfg['label']}] Q2 화면 목록 {len(q2_payload['products']):,}개 "
              f"(|r| >= {q2_payload['listedLine']})")

    if q4_payload.get("available") and q4 is not None:

        view = q4[q4["pkey"].isin(picked_keys)]

        q4_payload["products"] = [
            {"pkey": r["pkey"], "item": str(r["item_name"]),
             "variety": str(r["variety_name"]), "grade": str(r["grade_name"]),
             "unit": f"{r['retail_unit_size']} {r['retail_unit_name']}",
             "price": r["price"], "posPct": r["pos_pct"],
             "verdict": r["verdict"], "pastN": r["past_n"],
             "pastYears": r["past_years"]}
            for _, r in view.iterrows()]

    payload = {
        "meta": {
            "freq": R["freq"], "freqLabel": cfg["label"], "unit": R["unit"],
            "cycle": R["cycle"], "maxLag": R["max_lag"], "minObs": R["min_obs"],
            "period": f"{int(series['year'].min())}~{int(series['year'].max())}",
            "products": int(R["n_products"]),
            "items": int(series["item_name"].nunique()),
            "rows": int(len(series)),
            "shown": len(picked), "dropped": dropped,
        },
        "q1": {"products": picked, "calendar": calendar,
               "strongCount": int(len(strong_season)) if strong_season is not None else 0,
               "totalCount": int(len(q1)) if q1 is not None else 0,
               "medianAmplitude": round(float(q1["amplitude"].median()), 3)
               if q1 is not None and len(q1) else 0,
               "strongLine": Q1_STRONG_AMPLITUDE,
               "monthNames": MONTH_NAME},
        "q2": q2_payload, "q3": q3_payload, "q4": q4_payload,
    }

    R["out_json"].write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    size = R["out_json"].stat().st_size / 1024

    print(f"\n[{cfg['label']}] 저장")
    print(f"  {R['out_json'].name:<30} {size:>7,.0f} KB  ← 10_dashboard.py 가 읽습니다")

    for q, path in R["q_files"].items():
        if path.exists():
            print(f"  {path.name:<30}")

    return payload


def analyze(freq, cpi_pack):

    R = run(freq, cpi_pack)

    if R is None:
        return False

    R["freq"] = freq

    q1, q1_products, calendar, strong_season = analyze_q1(R)

    if q1 is None:
        print(f"[{FREQ[freq]['label']}] Q1 을 못 만들어 중단합니다.")
        return False

    q2_payload, q2 = analyze_q2(R)
    q3_payload = analyze_q3(R, cpi_pack)
    q4_payload, q4 = analyze_q4(R)

    finish(R, q1, q1_products, calendar, strong_season,
           q2_payload, q2, q3_payload, q4_payload, q4)

    return True


# ---------------------------------------------------------
# 시작
# ---------------------------------------------------------

arg = (sys.argv[1] if len(sys.argv) > 1 else "week").lower()

if arg == "all":
    wanted = ["week", "month", "day"]

elif arg in FREQ:
    wanted = [arg]

else:
    raise SystemExit(
        f"주기를 알 수 없습니다: {arg}\n"
        f"  python 09_analyze.py [week|month|day|all]")

print("=" * 70)
print("소비자물가지수 읽기 (Q3)")
print("=" * 70)

cpi_pack = load_cpi()

done, skipped = [], []

for freq in wanted:

    paths = [DATA_DIR / f for f in FREQ[freq]["files"]]

    if not any(p.exists() for p in paths):
        skipped.append((freq, f"입력 파일 없음: {', '.join(p.name for p in paths)}"))
        continue

    try:
        if analyze(freq, cpi_pack):
            done.append(freq)
        else:
            skipped.append((freq, "분석 조건 미달 (위 메시지 참고)"))

    except Exception as err:
        skipped.append((freq, f"{type(err).__name__}: {err}"))
        print(f"\n[{FREQ[freq]['label']}] 실패 — {type(err).__name__}: {err}")

print("\n" + "=" * 70)
print("정리")
print("=" * 70)

for freq in done:
    print(f"  완료  {FREQ[freq]['label']:<5} dashboard_data_{freq}.json")

for freq, why in skipped:
    print(f"  건너뜀 {FREQ[freq]['label']:<5} {why}")

if not done:
    raise SystemExit("\n분석된 주기가 하나도 없습니다.")

print("\n다음 단계: python 10_dashboard.py")
