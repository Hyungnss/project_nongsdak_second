"""
2-d단계 — 날짜 파싱 및 year · month 분리

실행:
    python 02_preprocess_d.py

입력  data/processed/price_c.parquet
출력  data/processed/price_d.parquet   (다음 단계용)
      data/processed/price_d.csv       (눈으로 확인용)

하는 일
    date 컬럼을 날짜형으로 바꾸고 year · month · day 로 나눕니다.
    날씨 데이터가 년월 단위이므로, 결합하려면 year·month 가 필요합니다.

주의
    파일마다 날짜 형식이 다를 수 있습니다.
    ('2021-07-01' / '20210701' / '2021.07.01')
    한 형식으로만 시도하면 특정 파일이 통째로 날아갑니다.
"""

from pathlib import Path

import pandas as pd


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

OUT_DIR = PROJECT_ROOT / "data" / "processed"

IN_FILE = OUT_DIR / "price_c.parquet"
IN_FILE_CSV = OUT_DIR / "price_c.csv"

OUT_FILE = OUT_DIR / "price_d.parquet"
OUT_FILE_CSV = OUT_DIR / "price_d.csv"


# 순서대로 시도할 날짜 형식
DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y%m%d",
    "%Y.%m.%d",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y년 %m월 %d일",
]

# date 컬럼을 남길지
#   03 단계에서 월별로 집계하면 자연히 사라지지만,
#   일별 분석(급등 시점 찾기 등)에는 필요합니다.
KEEP_DATE = True

# 데이터가 있어야 할 기간 — 벗어난 날짜를 찾기 위한 기준
VALID_YEAR_MIN = 2016
VALID_YEAR_MAX = 2025

# 단계마다 csv 도 함께 남길지
#   parquet 은 사람이 못 읽습니다. 값이 맞게 나왔는지 눈으로 보려면 csv 가 필요합니다.
SAVE_CSV = True

# csv 에 남길 행 수 — 0 이면 전체
#   전체는 수백 MB 가 될 수 있습니다. 확인만 할 거면 50000 정도로 충분합니다.
CSV_MAX_ROWS = 0


# ---------------------------------------------------------
# 0. 저장 도우미
#    parquet 은 다음 단계가 읽고, csv 는 사람이 열어 확인합니다.
#    단계마다 csv 가 남으므로 어디서 값이 틀어졌는지 되짚을 수 있습니다.
# ---------------------------------------------------------

def save(frame, parquet_path, csv_path):

    saved = []

    try:
        frame.to_parquet(parquet_path, index=False)
        saved.append(parquet_path)

    except Exception as err:
        print(f"(parquet 저장 실패: {err})")
        print("  pip install pyarrow 를 권합니다. csv 로만 남깁니다.")

    # parquet 이 없으면 다음 단계가 이 csv 를 읽습니다.
    # 그때 잘라 저장하면 데이터가 소리 없이 사라지므로 전체를 씁니다.
    limit = CSV_MAX_ROWS if (CSV_MAX_ROWS > 0 and saved) else 0

    if SAVE_CSV or not saved:
        part = frame if limit <= 0 else frame.head(limit)
        part.to_csv(csv_path, index=False, encoding="utf-8-sig")
        saved.append(csv_path)

    for path in saved:
        size_mb = path.stat().st_size / 1024 / 1024
        note = f"  ← 확인용 상위 {limit:,}행" if (path is csv_path and limit) else ""
        print(f"저장: {path}  ({size_mb:,.1f} MB){note}")


# ---------------------------------------------------------
# 1. 읽기
# ---------------------------------------------------------

if IN_FILE.exists():
    df = pd.read_parquet(IN_FILE)
    print(f"읽기: {len(df):,}행 (parquet)")

elif IN_FILE_CSV.exists():
    df = pd.read_csv(IN_FILE_CSV, encoding="utf-8-sig", low_memory=False)
    print(f"읽기: {len(df):,}행 (csv)")

else:
    raise FileNotFoundError(f"먼저 02_preprocess_c.py 를 실행하세요.\n  {IN_FILE}")

start_count = len(df)

raw = df["date"].astype(str).str.strip()

print(f"\n원본 형식 예시: {raw.head(5).tolist()}")
print(f"글자 수 분포: {raw.str.len().value_counts().head(5).to_dict()}")


# ---------------------------------------------------------
# 2. 파싱 — 여러 형식을 순서대로
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("날짜 파싱")
print("=" * 60)

# 먼저 pandas 자동 판별
date = pd.to_datetime(raw, errors="coerce")

print(f"  자동 판별      성공 {date.notna().sum():>12,} / 실패 {date.isna().sum():>10,}")

# 실패한 것만 형식을 지정해 다시 시도
for fmt in DATE_FORMATS:

    still_na = date.isna()

    if not still_na.any():
        break

    retry = pd.to_datetime(raw[still_na], format=fmt, errors="coerce")

    recovered = retry.notna().sum()

    if recovered > 0:
        date.loc[still_na] = retry
        print(f"  {fmt:<20} 추가 복구 {recovered:>12,}")


failed = date.isna()

print(f"\n최종 실패: {failed.sum():,}건")


# ---------------------------------------------------------
# 3. 실패한 값 확인 — 어느 파일에서 왔나
# ---------------------------------------------------------

if failed.any():

    print("\n" + "=" * 60)
    print("파싱 실패 상세")
    print("=" * 60)

    print("\n실패한 값 예시")
    for value, count in raw[failed].value_counts().head(10).items():
        print(f"  {value!r:<30} {count:>10,}건")

    if "source_file" in df.columns:

        print("\n출처파일별")

        by_file = df.loc[failed, "source_file"].value_counts()

        for name, count in by_file.items():
            total = (df["source_file"] == name).sum()
            print(f"  {str(name)[:45]:<45} {count:>8,} / {total:>8,} "
                  f"({count / total * 100:5.1f}%)")

        top_share = by_file.iloc[0] / failed.sum()

        if top_share > 0.8:
            print(f"\n  → 실패의 {top_share * 100:.0f}%가 '{by_file.index[0]}' 한 파일입니다.")
            print("     그 파일만 다시 받거나, 위 '실패한 값 예시'를 보고")
            print("     DATE_FORMATS 에 형식을 추가하세요.")

    df = df[~failed].copy()
    date = date[~failed]

    print(f"\n제외: {start_count:,} → {len(df):,}")


# ---------------------------------------------------------
# 4. year · month · day 분리
# ---------------------------------------------------------

df["date"] = date

df["year"] = df["date"].dt.year
df["month"] = df["date"].dt.month
df["day"] = df["date"].dt.day

print("\nyear · month · day 생성 완료")


# ---------------------------------------------------------
# 5. 기간을 벗어난 날짜 확인
# ---------------------------------------------------------

out_of_range = (df["year"] < VALID_YEAR_MIN) | (df["year"] > VALID_YEAR_MAX)

if out_of_range.any():

    print(f"\n[주의] {VALID_YEAR_MIN}~{VALID_YEAR_MAX} 범위를 벗어난 행: "
          f"{out_of_range.sum():,}건")
    print(df.loc[out_of_range, "year"].value_counts().sort_index().to_string())
    print("  형식을 잘못 읽었을 수 있습니다. (예: 20210701 을 2021-07-01 이 아닌 값으로)")


# ---------------------------------------------------------
# 6. 저장
# ---------------------------------------------------------

if not KEEP_DATE:
    df = df.drop(columns=["date"])
    print("\ndate 컬럼 제거 (KEEP_DATE=False)")

# 컬럼 순서 — year, month 를 앞으로
front = [c for c in ["year", "month", "day", "date"] if c in df.columns]
rest = [c for c in df.columns if c not in front]

df = df[front + rest].reset_index(drop=True)

print()
save(df, OUT_FILE, OUT_FILE_CSV)


# ---------------------------------------------------------
# 7. 검증
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("결과")
print("=" * 60)

print(f"시작   {start_count:>12,}행")
print(f"종료   {len(df):>12,}행")
print(f"컬럼   {df.columns.tolist()}")

if "date" in df.columns:
    print(f"기간   {df['date'].min().date()} ~ {df['date'].max().date()}")

print("\n연도별 건수")
print(df["year"].value_counts().sort_index().to_string())

print("\n월별 건수")
print(df["month"].value_counts().sort_index().to_string())

# 연도-월 조합이 몇 개인지 — 10년치면 120개가 완전한 상태
ym_count = df.groupby(["year", "month"]).size()

print(f"\n연도-월 조합: {len(ym_count)}개 "
      f"(2016~2025 전체면 120개)")

if len(ym_count) < 120:

    all_ym = {(y, m) for y in range(VALID_YEAR_MIN, VALID_YEAR_MAX + 1)
              for m in range(1, 13)}
    missing_ym = sorted(all_ym - set(ym_count.index))

    print(f"  빠진 연월 {len(missing_ym)}개: {missing_ym[:24]}")

# 조사는 평일에만 이뤄집니다.
if "date" in df.columns:

    weekend = df["date"].dt.dayofweek >= 5

    print(f"\n주말 데이터: {weekend.sum():,}건 ({weekend.mean() * 100:.2f}%)")

    if weekend.sum() > 0:
        print("  가격 조사는 평일에만 이뤄지므로, 많으면 날짜 파싱을 의심해 보세요.")

print("\n다음 단계: 02_preprocess_e.py (단위 정규화)")
