"""
2-b단계 — 소매만 남기기

실행:
    python 02_preprocess_b.py

입력  data/processed/price_a.parquet
출력  data/processed/price_b.parquet   (다음 단계용)
      data/processed/price_b.csv       (눈으로 확인용)

하는 일
    도매·친환경 등을 빼고 소매 조사 행만 남깁니다.
    데이터가 크게 줄어 이후 단계가 빨라집니다.
"""

from pathlib import Path

import pandas as pd


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

OUT_DIR = PROJECT_ROOT / "data" / "processed"

IN_FILE = OUT_DIR / "price_a.parquet"
IN_FILE_CSV = OUT_DIR / "price_a.csv"

OUT_FILE = OUT_DIR / "price_b.parquet"
OUT_FILE_CSV = OUT_DIR / "price_b.csv"


# 소매로 볼 코드값
#   실행하면 실제 분포를 먼저 찍어 주므로, 다르면 여기를 고치세요.
RETAIL_CODES = {"01", "1", "소매"}

# 필터 후 market_type_code 는 한 값만 남습니다.
#   컬럼을 계속 들고 갈지 여부입니다.
KEEP_CODE_COLUMN = True

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
    raise FileNotFoundError(f"먼저 02_preprocess_a.py 를 실행하세요.\n  {IN_FILE}")


# ---------------------------------------------------------
# 2. 코드값 분포 확인
# ---------------------------------------------------------

codes = df["market_type_code"].astype(str).str.strip()

print("\n" + "=" * 60)
print("market_type_code 분포")
print("=" * 60)

dist = codes.value_counts(dropna=False)

for code, count in dist.items():
    mark = "  ← 소매" if code in RETAIL_CODES else ""
    print(f"  {code!r:<10} {count:>12,}건 ({count / len(df) * 100:5.1f}%){mark}")


# ---------------------------------------------------------
# 3. 필터
# ---------------------------------------------------------

is_retail = codes.isin(RETAIL_CODES)

if not is_retail.any():
    raise ValueError(
        f"소매 코드를 못 찾았습니다.\n"
        f"실제 값: {dist.index.tolist()}\n"
        f"RETAIL_CODES 를 위 분포에 맞춰 고쳐 주세요."
    )

before = len(df)
df = df[is_retail].copy()

print(f"\n소매만 남김: {before:,} → {len(df):,}  ({before - len(df):,}건 제외)")


# 필터 후 값이 하나뿐이면 컬럼이 의미를 잃습니다.
remaining = df["market_type_code"].nunique()

if remaining == 1 and not KEEP_CODE_COLUMN:
    df = df.drop(columns=["market_type_code"])
    print("  market_type_code 컬럼 제거 (값이 하나뿐)")
elif remaining == 1:
    print(f"  market_type_code 는 '{df['market_type_code'].iloc[0]}' 하나만 남음 (컬럼 유지)")


# ---------------------------------------------------------
# 4. 저장
# ---------------------------------------------------------

df = df.reset_index(drop=True)

print()
save(df, OUT_FILE, OUT_FILE_CSV)


# ---------------------------------------------------------
# 5. 확인
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("결과")
print("=" * 60)

print(f"행 수  {len(df):,}")
print(f"컬럼   {df.columns.tolist()}")

print("\n지역 분포 (상위 25)")
print(df["sido_name"].value_counts().head(25).to_string())

print("\n단위명 분포")
print(df["retail_unit_name"].value_counts().to_string())

print("\n샘플 3건")
print(df.head(3).to_string())

print("\n다음 단계: 02_preprocess_c.py (결측 제거)")
