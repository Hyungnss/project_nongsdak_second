"""
3단계 — 주별 평균 집계

실행:
    python 03_weekly.py

입력  data/processed/price_e.parquet     (02_preprocess_e.py 결과)
      없으면 price_clean.parquet         (통합본 02_preprocess.py 결과)

출력  data/processed/price_weekly.parquet   (다음 단계용)
      data/processed/price_weekly.csv       (눈으로 확인용)

산출 컬럼 — 아래 11개만 남깁니다
    year, month, week
    sido_name, item_name, variety_name, market_type_code, grade_name
    price, retail_unit_size, retail_unit_name

주를 어떻게 나누는가
    ISO 기준 — 월요일 시작, 일요일 끝, 한 해가 52~53주입니다.
    year·month 는 그 주 월요일이 속한 연·월입니다.

        예) 2016-02-01(월) ~ 02-07(일)  →  year 2016, month 2, week 5

    한 주가 두 달에 걸치면 월요일이 있는 달로 갑니다.
    ISO 주차라 month 와 어긋나는 주가 생깁니다. (2월인데 week 5)
    연속된 주 번호가 필요해서 이렇게 둡니다.

무엇을 계산하는가
    같은 주·지역·품목·품종·등급·단위 조합의 price 평균입니다.
    단위(size·name)를 키에 넣는 이유는 단위가 다르면 다른 상품이기 때문입니다.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data" / "processed"

# 앞 단계 산출물을 순서대로 찾습니다.
#   a~e 로 나눠 돌렸으면 price_e, 통합본을 돌렸으면 price_clean 입니다.
IN_CANDIDATES = [
    DATA_DIR / "price_e.parquet",
    DATA_DIR / "price_e.csv",
    DATA_DIR / "price_clean.parquet",
    DATA_DIR / "price_clean.csv",
]

OUT_FILE = DATA_DIR / "price_weekly.parquet"
OUT_FILE_CSV = DATA_DIR / "price_weekly.csv"


# 집계 기준 — 이 조합마다 한 행이 나옵니다.
GROUP_KEYS = [
    "year", "month", "week",
    "sido_name", "item_name", "variety_name",
    "market_type_code", "grade_name",
    "retail_unit_size", "retail_unit_name",
]

# 최종 컬럼 — 이 순서 그대로 저장합니다.
FINAL_COLUMNS = GROUP_KEYS[:8] + ["price"] + GROUP_KEYS[8:]

# 분석 대상 품목만 남길지 (통합본 02_preprocess.py 가 붙이는 컬럼)
#   a~e 경로에는 이 컬럼이 없으므로 자동으로 건너뜁니다.
ONLY_ANALYZABLE = True

# 단위가 섞인 품목·품종을 뺄지
DROP_UNIT_MISMATCH = True

# 정렬
#   "date"    year → month → week 오름차순. 오래된 주가 맨 위
#   "series"  품목·품종·지역으로 먼저 묶고, 그 안에서 주 오름차순
SORT_ORDER = "date"

# csv 도 함께 남길지 (앞 단계와 같은 방식)
SAVE_CSV = True
CSV_MAX_ROWS = 0


# ---------------------------------------------------------
# 0. 저장 도우미
# ---------------------------------------------------------

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
        print(f"  {path.name:<24} {size_mb:>8,.1f} MB{note}")


# ---------------------------------------------------------
# 1. 읽기 — 어느 폴더의 어느 파일을 썼는지 남깁니다
# ---------------------------------------------------------

print("=" * 60)
print("데이터 출처")
print("=" * 60)

print(f"폴더: {DATA_DIR}")
print("\n찾은 파일 (위에서부터 먼저 사용)")

source = None

for path in IN_CANDIDATES:

    exists = path.exists()
    mark = "O" if exists else "-"

    if exists:
        size_mb = path.stat().st_size / 1024 / 1024
        mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        detail = f"{size_mb:>8,.1f} MB   수정 {mtime}"
    else:
        detail = "없음"

    used = "  ← 사용" if (exists and source is None) else ""

    print(f"  [{mark}] {path.name:<24} {detail}{used}")

    if exists and source is None:
        source = path

if source is None:
    raise FileNotFoundError(
        f"앞 단계 결과가 없습니다. 02_preprocess_e.py 를 먼저 실행하세요.\n"
        f"  폴더: {DATA_DIR}"
    )

if source.suffix == ".parquet":
    df = pd.read_parquet(source)
else:
    # market_type_code 는 '01' 처럼 앞자리 0 이 있어 숫자로 읽으면 1 이 됩니다.
    df = pd.read_csv(source, encoding="utf-8-sig", low_memory=False,
                     dtype={"market_type_code": str, "grade_name": str})

print(f"\n읽기: {source}")
print(f"      {len(df):,}행 × {len(df.columns)}컬럼")


# ---------------------------------------------------------
# 2. 집계 전 걸러내기
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("집계 전 정리")
print("=" * 60)

if ONLY_ANALYZABLE and "is_analyzable" in df.columns:
    before = len(df)
    df = df[df["is_analyzable"]]
    print(f"분석대상 필터: {before:,} → {len(df):,} (기록이 적은 품목 제외)")

if DROP_UNIT_MISMATCH and "unit_mismatch" in df.columns:
    before = len(df)
    df = df[~df["unit_mismatch"]]
    print(f"단위불일치 제외: {before:,} → {len(df):,}")


# ---------------------------------------------------------
# 3. year · month · week 만들기
#    date 를 그 주 월요일로 내린 뒤 거기서 셋을 뽑습니다.
#    (원본의 year·month 는 조사일 기준이라 주 경계와 어긋납니다)
# ---------------------------------------------------------

if "date" not in df.columns:
    raise KeyError(
        "date 컬럼이 없습니다. 주별 집계는 일자가 있어야 합니다.\n"
        "02_preprocess_d.py 의 KEEP_DATE 를 True 로 두고 다시 실행하세요."
    )

df = df.copy()
df["date"] = pd.to_datetime(df["date"])

bad_date = df["date"].isna()

if bad_date.any():
    print(f"날짜 결측 {bad_date.sum():,}건 제외")
    df = df[~bad_date]

# 월요일로 내림 (dayofweek: 월=0 … 일=6)
week_start = (df["date"] - pd.to_timedelta(df["date"].dt.dayofweek, unit="D")).dt.normalize()

df["year"] = week_start.dt.year
df["month"] = week_start.dt.month
df["week"] = df["date"].dt.isocalendar().week.astype(int)

print(f"\n주 생성: {week_start.nunique():,}개 주 "
      f"({week_start.min().date()} ~ {week_start.max().date()})")
print(f"  week 범위: {df['week'].min()} ~ {df['week'].max()} (ISO 주차)")


# ---------------------------------------------------------
# 4. 주별 집계
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("주별 집계")
print("=" * 60)

print(f"집계 기준: {GROUP_KEYS}")

df["_week_start"] = week_start

weekly = (df.groupby(GROUP_KEYS, observed=True, dropna=False)
          .agg(price=("price", "mean"),
               days=("date", "nunique"),          # 조사일수 — 화면 확인용
               week_start=("_week_start", "min"))  # 정렬용 — 둘 다 저장하지 않습니다
          .reset_index())

weekly["price"] = weekly["price"].round(1)

print(f"집계 결과: {len(df):,}행 → {len(weekly):,}행")

if weekly.empty:
    print("\n집계 결과가 0행입니다. 저장하지 않고 멈춥니다.")
    print("  위 '집계 전 정리' 의 숫자를 보세요.")
    print("  필터가 전부 걸러냈다면 ONLY_ANALYZABLE 을 False 로 두고 다시 실행하세요.")
    raise SystemExit(1)

print("\n주당 조사일수 (한 칸에 며칠치가 들어갔는지 — 저장은 하지 않습니다)")

for days, count in weekly["days"].value_counts().sort_index().items():
    print(f"  {days}일 {count:>12,}행 ({count / len(weekly) * 100:5.1f}%)")

thin = (weekly["days"] == 1).sum()

if thin:
    print(f"  → 1일짜리 {thin:,}행 ({thin / len(weekly) * 100:.1f}%)은 "
          f"평균이라기보다 그날 값 하나입니다.")


# ---------------------------------------------------------
# 5. 컬럼 추리기 + 정렬
# ---------------------------------------------------------

# 정렬은 week 가 아니라 실제 주 시작일로 합니다.
#   ISO 주차는 12월 말 주가 1 로 돌아가므로,
#   year·month·week 로 정렬하면 12/31 주가 12/3 주보다 위로 올라옵니다.
if SORT_ORDER == "date":
    SORT_KEYS = ["week_start", "item_name", "variety_name", "sido_name"]
else:
    SORT_KEYS = ["item_name", "variety_name", "sido_name", "week_start"]

weekly = weekly.sort_values(SORT_KEYS)

period_from = weekly["week_start"].min()
period_to = weekly["week_start"].max() + pd.Timedelta(days=6)

# 여기서 요구한 11개 컬럼만 남깁니다. (days·week_start 는 화면용이라 버립니다)
weekly = weekly[FINAL_COLUMNS].reset_index(drop=True)

print(f"\n컬럼 {len(FINAL_COLUMNS)}개만 남김: {FINAL_COLUMNS}")
print(f"정렬: {SORT_KEYS} (오름차순)")

# 연말연시에는 12월 주가 다음 해 1주로 잡힙니다. (2018-12-31 → week 1)
# month 가 있어 구분되지만, week 만으로 묶으면 섞이므로 알려 둡니다.
mixed = weekly.groupby(["year", "week"])["month"].nunique()
mixed = mixed[mixed > 1]

if len(mixed):
    print(f"\n[참고] 같은 year·week 인데 month 가 다른 조합 {len(mixed)}개")
    print("       ISO 주차라 12월 말 주가 다음 해 1주로 잡힙니다.")
    print("       주 단위로 묶을 때는 year·month·week 를 함께 쓰세요.")


# ---------------------------------------------------------
# 6. 저장
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("저장")
print("=" * 60)

print(f"폴더: {DATA_DIR}\n")

save(weekly, OUT_FILE, OUT_FILE_CSV)


# ---------------------------------------------------------
# 7. 결과 확인
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("결과")
print("=" * 60)

print(f"행 수      {len(weekly):,}")
print(f"컬럼       {weekly.columns.tolist()}")
print(f"기간       {period_from.date()} ~ {period_to.date()}")
print(f"주 조합    {len(weekly.groupby(['year', 'month', 'week'])):,}개")
print(f"품목       {weekly['item_name'].nunique()}개")
print(f"지역       {weekly['sido_name'].nunique()}개")

print("\n연도별 행 수")
print(weekly["year"].value_counts().sort_index().to_string())

print("\n샘플 (저장된 순서 그대로 앞 15줄)")
print(weekly.head(15).to_string(index=False))

print("\n결측 (0 이어야 정상)")
for col in FINAL_COLUMNS:
    n = weekly[col].isna().sum()
    if n:
        print(f"  {col:<20} {n:,}")
print("  " + ("이상 없음" if not weekly.isna().any().any() else ""))
