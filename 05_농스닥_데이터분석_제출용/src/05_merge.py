"""
5단계 — 주별 가격 + 주별 날씨 결합

실행:
    python 05_merge.py

입력  data/processed/price_weekly.parquet          (03_weekly.py 결과)
      data/raw/average_temp_precip_w2016_2025.csv  (전처리된 주별 날씨)

출력  data/processed/price_weather_weekly.parquet   (다음 단계용)
      data/processed/price_weather_weekly.csv       (눈으로 확인용)

결합 키
    year + week 두 개뿐입니다.
    날씨가 전국 하나라 지역 구분이 없어, 같은 주의 모든 시도에
    같은 기온·강수량이 붙습니다. 지역차를 보려면 지점별 날씨가 필요합니다.

주의해야 할 것 — 연말연시
    ISO 주차는 12월 말 주가 다음 해 1주가 됩니다.

        2018-12-31(월) ~ 2019-01-06(일)  →  ISO 2019년 1주

    그런데 price_weekly 의 year 는 '월요일이 속한 해' 라서 2018 입니다.
    이대로 (2018, 1주) 로 붙이면 2018년 1월 첫 주 날씨가 딸려옵니다.
    한 해 어긋난 날씨가 조용히 섞이는 겁니다.

    그래서 결합 전에 year 를 ISO 기준으로 맞춥니다. (FIX_ISO_YEAR)
    보정 전후 매칭률을 둘 다 찍어 주므로, 날씨 파일이 어느 기준인지
    확인한 뒤 판단하세요.
"""

from pathlib import Path

import pandas as pd


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_DIR = PROJECT_ROOT / "data" / "processed"

PRICE_FILE = DATA_DIR / "price_weekly.parquet"
PRICE_FILE_CSV = DATA_DIR / "price_weekly.csv"

WEATHER_FILE = RAW_DIR / "average_temp_precip_w2016_2025.csv"

OUT_FILE = DATA_DIR / "price_weather_weekly.parquet"
OUT_FILE_CSV = DATA_DIR / "price_weather_weekly.csv"


# 날씨에서 뺄 컬럼
DROP_COLUMNS = ["location"]

# 날씨 값 컬럼 — 실제 파일에 맞춰 두세요.
WEATHER_VALUES = ["avg_tmp", "precip", "min_avgtmp", "max_avgtmp"]

# 연말연시 year 보정 (위 docstring 참고)
#   True  : 12월의 1주 → 다음 해, 1월의 52·53주 → 이전 해로 맞춰 결합
#   False : year 를 그대로 두고 결합
FIX_ISO_YEAR = True

# 날씨가 없는 주를 어떻게 할지
#   "keep" : 남기고 날씨는 빈칸 (가격 행 수가 유지됩니다)
#   "drop" : 날씨가 붙은 주만 남김
ON_MISSING = "keep"

# csv 도 함께 남길지
SAVE_CSV = True
CSV_MAX_ROWS = 0


# ---------------------------------------------------------
# 0. 도우미
# ---------------------------------------------------------

def read_csv_any(path, **kwargs):
    """인코딩을 순서대로 시도해 읽습니다."""

    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs)
        except UnicodeDecodeError:
            continue

    raise RuntimeError(f"인코딩 판별 실패: {path.name}")


def save(frame, parquet_path, csv_path):

    saved = []

    try:
        frame.to_parquet(parquet_path, index=False)
        saved.append(parquet_path)

    except Exception as err:
        print(f"(parquet 저장 실패: {err})")
        print("  pip install pyarrow 를 권합니다. csv 로만 남깁니다.")

    limit = CSV_MAX_ROWS if (CSV_MAX_ROWS > 0 and saved) else 0

    if SAVE_CSV or not saved:
        part = frame if limit <= 0 else frame.head(limit)
        part.to_csv(csv_path, index=False, encoding="utf-8-sig")
        saved.append(csv_path)

    for path in saved:
        size_mb = path.stat().st_size / 1024 / 1024
        note = f"  ← 확인용 상위 {limit:,}행" if (path is csv_path and limit) else ""
        print(f"  {path.name:<30} {size_mb:>8,.1f} MB{note}")


# ---------------------------------------------------------
# 1. 가격 읽기
# ---------------------------------------------------------

print("=" * 60)
print("데이터 출처")
print("=" * 60)

print(f"가격 폴더: {DATA_DIR}")
print(f"날씨 폴더: {RAW_DIR}")

if PRICE_FILE.exists():
    price = pd.read_parquet(PRICE_FILE)
    price_source = PRICE_FILE

elif PRICE_FILE_CSV.exists():
    price = read_csv_any(PRICE_FILE_CSV, low_memory=False,
                         dtype={"market_type_code": str, "grade_name": str})
    price_source = PRICE_FILE_CSV

else:
    raise FileNotFoundError(
        f"주별 가격이 없습니다. 먼저 03_weekly.py 를 실행하세요.\n  {PRICE_FILE}"
    )

print(f"\n가격: {price_source.name}  {len(price):,}행 × {len(price.columns)}컬럼")
print(f"      {price['year'].min()}년 ~ {price['year'].max()}년")


# ---------------------------------------------------------
# 2. 날씨 읽기
# ---------------------------------------------------------

if not WEATHER_FILE.exists():
    raise FileNotFoundError(
        f"날씨 파일이 없습니다.\n  {WEATHER_FILE}\n"
        f"  파일명이 다르면 WEATHER_FILE 을 고치세요."
    )

weather = read_csv_any(WEATHER_FILE)
weather.columns = [c.strip() for c in weather.columns]

print(f"날씨: {WEATHER_FILE.name}  {len(weather):,}행 × {len(weather.columns)}컬럼")
print(f"      컬럼 {weather.columns.tolist()}")


# ---------------------------------------------------------
# 3. location 제거
#    지우기 전에 값이 하나뿐인지 확인합니다.
#    여러 지역이 들어 있는데 지우면 같은 주가 여러 행이 되고,
#    결합할 때 가격 행이 그 배수로 불어납니다.
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("날씨 정리")
print("=" * 60)

for col in DROP_COLUMNS:

    if col not in weather.columns:
        print(f"{col} 컬럼이 없습니다 — 건너뜁니다")
        continue

    values = weather[col].dropna().unique()

    print(f"{col} 값: {values.tolist()[:10]} ({len(values)}종)")

    if len(values) > 1:
        raise ValueError(
            f"{col} 에 값이 {len(values)}개 있습니다: {values.tolist()[:10]}\n"
            f"  전국 하나가 아니라 지역별 데이터입니다.\n"
            f"  그냥 지우면 같은 주가 여러 행이 되어 결합이 어긋납니다.\n"
            f"  지역별로 쓰려면 sido_name 과 매핑해 결합 키에 넣으세요."
        )

    weather = weather.drop(columns=[col])
    print(f"  → {col} 제거")

# 값 컬럼 숫자 변환
for col in WEATHER_VALUES:

    if col not in weather.columns:
        print(f"[주의] {col} 컬럼이 없습니다 — WEATHER_VALUES 를 확인하세요")
        continue

    weather[col] = pd.to_numeric(weather[col], errors="coerce")

value_cols = [c for c in WEATHER_VALUES if c in weather.columns]

if not value_cols:
    raise KeyError(
        f"날씨 값 컬럼을 하나도 못 찾았습니다.\n"
        f"  찾은 이름: {WEATHER_VALUES}\n"
        f"  실제 컬럼: {weather.columns.tolist()}\n"
        f"  WEATHER_VALUES 를 실제 컬럼명에 맞춰 주세요."
    )

weather["year"] = pd.to_numeric(weather["year"], errors="coerce").astype("Int64")
weather["week"] = pd.to_numeric(weather["week"], errors="coerce").astype("Int64")

bad = weather["year"].isna() | weather["week"].isna()

if bad.any():
    print(f"year·week 결측 {bad.sum():,}행 제외")
    weather = weather[~bad]

weather["year"] = weather["year"].astype(int)
weather["week"] = weather["week"].astype(int)

# 키가 유일한지 — 여기서 중복이면 결합할 때 행이 불어납니다.
dup = weather.duplicated(subset=["year", "week"], keep=False)

if dup.any():
    print(f"\n[중단] year·week 중복 {dup.sum():,}행")
    print(weather[dup].head(10).to_string(index=False))
    raise ValueError("날씨의 year·week 가 유일하지 않습니다. 결합하면 행이 불어납니다.")

print(f"\n날씨 정리 완료: {len(weather):,}행")
print(f"  값 컬럼: {value_cols}")

# 연도별로 몇 주가 들어 있는지 — 빠진 주가 있으면 그 주는 날씨 없이 결합됩니다.
#   ISO 기준으로 한 해는 52주, 53주인 해도 있습니다.
print("\n연도별 주 수")

gaps = []

for y, sub in weather.groupby("year"):

    have = set(sub["week"])
    missing = sorted(set(range(1, max(have) + 1)) - have)

    note = f"   ← 빠진 주 {missing}" if missing else ""
    print(f"  {y}  {len(sub):>3}주  ({min(have)}~{max(have)}){note}")

    if missing:
        gaps.extend((y, w) for w in missing)

if gaps:
    print(f"\n  빠진 주 {len(gaps)}개 — 이 주의 가격에는 날씨가 붙지 않습니다.")


# ---------------------------------------------------------
# 4. 결합용 year 맞추기
#    price_weekly 의 year 는 '주 월요일이 속한 해' 입니다.
#    ISO 주차와 어긋나는 연말연시만 손봅니다.
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("결합 키 맞추기")
print("=" * 60)

join_year = price["year"].copy()

# 12월인데 1주 → 그 주는 다음 해의 1주입니다.
to_next = (price["month"] == 12) & (price["week"] <= 1)

# 1월인데 52·53주 → 그 주는 이전 해의 마지막 주입니다.
to_prev = (price["month"] == 1) & (price["week"] >= 52)

join_year = join_year.where(~to_next, price["year"] + 1)
join_year = join_year.where(~to_prev, price["year"] - 1)

print(f"연말연시 경계 행: 다음 해로 {to_next.sum():,} / 이전 해로 {to_prev.sum():,}")

# 보정 전후 매칭률을 비교해 어느 기준이 맞는지 볼 수 있게 합니다.
keys = set(zip(weather["year"], weather["week"]))

raw_hit = pd.Series(list(zip(price["year"], price["week"]))).isin(keys).mean()
fix_hit = pd.Series(list(zip(join_year, price["week"]))).isin(keys).mean()

print(f"  보정 안 함 매칭률 {raw_hit * 100:5.1f}%")
print(f"  보정 함   매칭률 {fix_hit * 100:5.1f}%")

if FIX_ISO_YEAR:
    price = price.assign(_join_year=join_year)
    print("  → 보정한 year 로 결합합니다 (FIX_ISO_YEAR=True)")
else:
    price = price.assign(_join_year=price["year"])
    print("  → 원래 year 로 결합합니다 (FIX_ISO_YEAR=False)")

if fix_hit < raw_hit:
    print("\n[참고] 보정하니 매칭률이 떨어집니다. 하지만 높은 쪽이 맞는 게 아닙니다.")
    print("       보정을 안 하면 12월 말 주가 '같은 해 1월 첫 주' 날씨에 붙습니다.")
    print("       그 주는 날씨 파일에 반드시 있으니 100% 가 나오지만, 한 해 어긋난 값입니다.")
    print("       날씨 파일에 빠진 주가 있으면 보정한 쪽만 손해를 봅니다.")
    print("       아래 [경계 확인] 의 실제 기온으로 판단하세요.")

# 매칭률만으로는 판단이 안 됩니다.
#   (2018, 1주) 도 (2019, 1주) 도 날씨 파일에 다 있으니 양쪽 다 100% 로 붙습니다.
#   어느 쪽이 '그 주의 날씨' 인지는 실제 값을 봐야 알 수 있습니다.
boundary = to_next | to_prev

if boundary.any():

    i = price.index[boundary][0]
    row = price.loc[i]

    lookup = weather.set_index(["year", "week"])[value_cols[0]]

    as_is = lookup.get((row["year"], row["week"]))
    fixed = lookup.get((join_year.loc[i], row["week"]))

    print(f"\n[경계 확인] {row['year']}년 {row['month']}월 {row['week']}주 "
          f"({row['item_name']} / {row['sido_name']})")
    print(f"  보정 안 함 → {row['year']}년 {row['week']}주 날씨  "
          f"{value_cols[0]} = {as_is}")
    print(f"  보정 함    → {join_year.loc[i]}년 {row['week']}주 날씨  "
          f"{value_cols[0]} = {fixed}")
    print("  두 값이 다르면, 어느 쪽이 그 주의 실제 날씨인지 확인하세요.")


# ---------------------------------------------------------
# 5. 결합
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("결합")
print("=" * 60)

before = len(price)

merged = price.merge(
    weather.rename(columns={"year": "_join_year"}),
    on=["_join_year", "week"],
    how="left",
)

print(f"가격 {before:,}행 + 날씨 {len(weather):,}행 → {len(merged):,}행")

# left 결합이라 행 수는 그대로여야 합니다. 늘었다면 날씨 키가 중복된 것입니다.
if len(merged) != before:
    raise ValueError(
        f"행 수가 달라졌습니다 ({before:,} → {len(merged):,}).\n"
        f"  날씨의 year·week 가 중복됐을 수 있습니다."
    )

matched = merged[value_cols[0]].notna()

print(f"날씨 붙음: {matched.sum():,}행 ({matched.mean() * 100:.1f}%)")

if (~matched).any():

    # month 와 '실제로 찾아간 주'(_join_year) 를 함께 봐야 원인이 보입니다.
    miss = merged[~matched].groupby(["year", "month", "week", "_join_year"]).size()

    print(f"\n날씨 없는 주 {len(miss)}개 (가격 {(~matched).sum():,}행)")
    print(f"  {'가격 쪽':<20} {'찾아간 날씨':<14} 행 수")

    for (y, m, w, jy), n in miss.head(10).items():

        edge = "  ← 연말 경계 보정됨" if jy != y else ""
        in_file = (jy, w) in keys

        print(f"  {y}년 {m:>2}월 {w:>2}주      {jy}년 {w:>2}주   {n:>9,}행"
              f"{'  (날씨 파일에 있음!)' if in_file else ''}{edge}")

    if len(miss) > 10:
        print(f"  … 외 {len(miss) - 10}개")

    print("\n  '날씨 파일에 있음' 이 뜨면 값이 아니라 형식 문제입니다.")
    print("  (year·week 의 자료형이 다르거나 공백이 섞인 경우)")
    print("  그 외는 날씨 파일에 그 주가 없는 것입니다. 위 '연도별 주 수' 를 보세요.")

if ON_MISSING == "drop":
    merged = merged[matched].reset_index(drop=True)
    print(f"\n날씨 없는 행 제외: {before:,} → {len(merged):,} (ON_MISSING='drop')")


# ---------------------------------------------------------
# 6. 저장
# ---------------------------------------------------------

COLUMN_ORDER = [
    "year", "month", "week",
    "sido_name", "item_name", "variety_name",
    "market_type_code", "grade_name",
    "price", "retail_unit_size", "retail_unit_name",
] + value_cols

merged = merged.drop(columns=["_join_year"])
merged = merged[[c for c in COLUMN_ORDER if c in merged.columns]]

print("\n" + "=" * 60)
print("저장")
print("=" * 60)

print(f"폴더: {DATA_DIR}\n")

save(merged, OUT_FILE, OUT_FILE_CSV)


# ---------------------------------------------------------
# 7. 결과 확인
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("결과")
print("=" * 60)

print(f"행 수      {len(merged):,}")
print(f"컬럼       {merged.columns.tolist()}")
print(f"기간       {merged['year'].min()}년 ~ {merged['year'].max()}년")
print(f"품목       {merged['item_name'].nunique()}개")
print(f"지역       {merged['sido_name'].nunique()}개")

print("\n날씨 컬럼 분포")
print(merged[value_cols].describe().round(1).to_string())

print("\n샘플 5줄")
print(merged.head(5).to_string(index=False))

print("\n→ 같은 주의 여러 지역이 같은 기온·강수량을 갖는 게 맞는지 확인하세요.")
print("   전국 하나짜리 날씨라 지역차는 볼 수 없습니다.")
