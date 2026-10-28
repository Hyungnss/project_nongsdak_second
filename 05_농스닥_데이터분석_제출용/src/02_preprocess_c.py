"""
2-c단계 — 결측 제거 (품목 · 품종 · 가격)

실행:
    python 02_preprocess_c.py

입력  data/processed/price_b.parquet
출력  data/processed/price_c.parquet   (다음 단계용)
      data/processed/price_c.csv       (눈으로 확인용)

하는 일
    품목·품종·가격이 비어 있는 행을 제거합니다.
    무엇이 얼마인지 모르는 행은 분석에 쓸 수 없기 때문입니다.

결측을 세 가지로 봅니다
    NaN          진짜 빈 값
    빈 문자열     '' 또는 공백만 있는 값
    가짜 결측     'nan' 'null' '-' 처럼 글자로 들어온 값

    dtype=str 로 읽으면 빈 칸은 NaN 이 되지만
    'nan' 이라는 '글자'는 문자열로 남습니다. isna() 만으로는 못 잡습니다.
"""

from pathlib import Path

import pandas as pd


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

OUT_DIR = PROJECT_ROOT / "data" / "processed"

IN_FILE = OUT_DIR / "price_b.parquet"
IN_FILE_CSV = OUT_DIR / "price_b.csv"

OUT_FILE = OUT_DIR / "price_c.parquet"
OUT_FILE_CSV = OUT_DIR / "price_c.csv"


# 결측으로 볼 문자열
FAKE_NA = ["nan", "null", "none", "na", "n/a", "-", ".", "없음", "미상", "0"]

# 결측 검사할 컬럼
CHECK_COLUMNS = ["item_name", "variety_name", "price"]

# 가격을 숫자로 바꿀지 ('1,234' → 1234)
#   변환 실패도 결측으로 봅니다.
CONVERT_PRICE = True

# 가격이 0 이하인 행도 제거할지
#   결측은 아니지만 시세로 쓸 수 없는 값입니다.
DROP_ZERO_PRICE = True

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
    df = pd.read_csv(IN_FILE_CSV, encoding="utf-8-sig", dtype=str, low_memory=False)
    print(f"읽기: {len(df):,}행 (csv)")

else:
    raise FileNotFoundError(f"먼저 02_preprocess_b.py 를 실행하세요.\n  {IN_FILE}")

start_count = len(df)


# ---------------------------------------------------------
# 2. 문자열 앞뒤 공백 정리
#    '배추 ' 와 '배추' 가 다른 값으로 갈리는 걸 먼저 막습니다.
# ---------------------------------------------------------

text_columns = df.select_dtypes(include="object").columns

for col in text_columns:
    df[col] = df[col].astype(str).str.strip()
    df[col] = df[col].replace({"nan": pd.NA, "None": pd.NA, "": pd.NA})

print(f"공백 정리: {len(text_columns)}개 문자열 컬럼")


# ---------------------------------------------------------
# 3. 결측 판정
# ---------------------------------------------------------

def missing_mask(series):
    """NaN · 빈문자열 · 가짜결측을 하나로 합쳐 돌려줍니다."""

    na = series.isna()

    text = series.fillna("").astype(str).str.strip()

    blank = text.eq("") & ~na
    fake = text.str.lower().isin(FAKE_NA)

    return na, blank, fake


print("\n" + "=" * 60)
print("컬럼별 결측")
print("=" * 60)

drop_mask = pd.Series(False, index=df.index)

for col in CHECK_COLUMNS:

    if col not in df.columns:
        print(f"\n[{col}] 컬럼이 없습니다 — 건너뜁니다")
        continue

    na, blank, fake = missing_mask(df[col])

    # 가격의 '0' 은 FAKE_NA 에 있지만, 숫자 0 은 아래에서 따로 다룹니다.
    if col == "price":
        fake = df[col].fillna("").astype(str).str.strip().str.lower().isin(
            [v for v in FAKE_NA if v != "0"]
        )

    miss = na | blank | fake

    print(f"\n[{col}]")
    print(f"  NaN        {na.sum():>12,}")
    print(f"  빈 문자열   {blank.sum():>12,}")
    print(f"  가짜 결측   {fake.sum():>12,}")
    print(f"  합계       {miss.sum():>12,}  ({miss.mean() * 100:.3f}%)")

    drop_mask |= miss


# ---------------------------------------------------------
# 4. 결측이 어디에 몰려 있나
# ---------------------------------------------------------

if drop_mask.any() and "source_file" in df.columns:

    print("\n" + "=" * 60)
    print("결측 행의 출처파일")
    print("=" * 60)

    by_file = df.loc[drop_mask, "source_file"].value_counts()

    for name, count in by_file.items():
        total = (df["source_file"] == name).sum()
        print(f"  {str(name)[:45]:<45} {count:>8,} / {total:>8,} "
              f"({count / total * 100:5.2f}%)")

    top_share = by_file.iloc[0] / drop_mask.sum()

    if top_share > 0.8:
        print(f"\n  → 결측의 {top_share * 100:.0f}%가 '{by_file.index[0]}' 한 파일에 몰려 있습니다.")
        print("     원본 문제가 아니라 그 파일의 파싱 문제일 수 있습니다.")


# ---------------------------------------------------------
# 5. 제거
# ---------------------------------------------------------

df = df[~drop_mask].copy()

print(f"\n결측 제거: {start_count:,} → {len(df):,}  ({drop_mask.sum():,}건 제외)")


# ---------------------------------------------------------
# 6. 가격 숫자 변환
# ---------------------------------------------------------

if CONVERT_PRICE:

    before = len(df)

    df["price"] = pd.to_numeric(
        df["price"].astype(str).str.replace(",", "").str.strip(),
        errors="coerce"
    )

    failed = df["price"].isna()

    if failed.any():
        print(f"\n숫자 변환 실패 {failed.sum():,}건 제외")
        df = df[~failed].copy()

    if DROP_ZERO_PRICE:

        zero = df["price"] <= 0

        if zero.any():
            print(f"가격 0 이하 {zero.sum():,}건 제외")
            df = df[~zero].copy()

    print(f"가격 정리: {before:,} → {len(df):,}")


# ---------------------------------------------------------
# 7. 저장
# ---------------------------------------------------------

df = df.reset_index(drop=True)

print()
save(df, OUT_FILE, OUT_FILE_CSV)


# ---------------------------------------------------------
# 8. 확인
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("결과")
print("=" * 60)

print(f"시작       {start_count:>12,}행")
print(f"종료       {len(df):>12,}행")
print(f"제거       {start_count - len(df):>12,}행 "
      f"({(start_count - len(df)) / start_count * 100:.2f}%)")

print(f"\n컬럼   {df.columns.tolist()}")

if CONVERT_PRICE:
    print("\n가격 분포")
    print(df["price"].describe().to_string())

print("\n남은 결측 (0 이어야 정상)")
for col in CHECK_COLUMNS:
    if col in df.columns:
        print(f"  {col:<15} {df[col].isna().sum():,}")

print("\n다음 단계: 02_preprocess_d.py (날짜 → year, month)")
