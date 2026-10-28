"""
2-a단계 — 필요없는 컬럼 제거 + 컬럼명 통일

실행:
    python 02_preprocess_a.py

입력  data/processed/price_merged.parquet   (00_merge.py 결과)
출력  data/processed/price_a.parquet   (다음 단계용)
      data/processed/price_a.csv       (눈으로 확인용)

하는 일
    분석에 쓸 컬럼만 남기고 이름을 영문으로 바꿉니다.
    데이터 내용은 건드리지 않습니다. (결측 제거·형변환은 다음 단계)
"""

from pathlib import Path

import pandas as pd


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

OUT_DIR = PROJECT_ROOT / "data" / "processed"

IN_FILE = OUT_DIR / "price_merged.parquet"
IN_FILE_CSV = OUT_DIR / "price_merged.csv"

OUT_FILE = OUT_DIR / "price_a.parquet"
OUT_FILE_CSV = OUT_DIR / "price_a.csv"


# 원본 컬럼 → 영문 컬럼 (여기 없는 컬럼은 전부 제거됩니다)
RENAME = {
    "가격등록일자": "date",
    "시도명": "sido_name",
    "품목명": "item_name",
    "품종명": "variety_name",
    "도소매조사구분코드": "market_type_code",
    "산물등급명": "grade_name",
    "품목가격": "price",
    "소매출하단위크기": "retail_unit_size",
    "소매출하단위명": "retail_unit_name",
}

# 00_merge.py 가 붙인 출처 컬럼을 남길지
#   이상한 값을 발견했을 때 어느 파일에서 왔는지 추적하는 데 씁니다.
#   전처리가 다 끝나면 마지막 단계에서 빼세요.
KEEP_SOURCE_FILE = True

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
    raise FileNotFoundError(f"먼저 00_merge.py 를 실행하세요.\n  {IN_FILE}")


df.columns = [c.strip() for c in df.columns]

print(f"원본 컬럼 {len(df.columns)}개")
print(f"  {df.columns.tolist()}")


# ---------------------------------------------------------
# 2. 이름 바꿀 컬럼이 다 있는지 확인
# ---------------------------------------------------------

missing = [c for c in RENAME if c not in df.columns]

if missing:
    raise KeyError(
        f"원본에 없는 컬럼: {missing}\n"
        f"실제 컬럼: {df.columns.tolist()}\n"
        f"RENAME 의 왼쪽 값을 실제 컬럼명에 맞춰 주세요."
    )


# ---------------------------------------------------------
# 3. 남길 컬럼 정하기
# ---------------------------------------------------------

rename_map = dict(RENAME)
keep = list(RENAME.values())

if KEEP_SOURCE_FILE and "출처파일" in df.columns:
    rename_map["출처파일"] = "source_file"
    keep.append("source_file")

dropped = [c for c in df.columns if c not in rename_map]

print(f"\n제거할 컬럼 {len(dropped)}개")

if dropped:
    for col in dropped:
        # 어떤 값이 들어 있던 컬럼인지 같이 보여줍니다.
        sample = df[col].dropna()
        example = sample.iloc[0] if len(sample) else "(전부 비어 있음)"
        print(f"  {col:<25} 예시: {str(example)[:30]}")
else:
    print("  없음")


# ---------------------------------------------------------
# 4. 적용
# ---------------------------------------------------------

df = df.rename(columns=rename_map)[keep]

print(f"\n남은 컬럼 {len(df.columns)}개")
print(f"  {df.columns.tolist()}")


# ---------------------------------------------------------
# 5. 저장
# ---------------------------------------------------------

print()
save(df, OUT_FILE, OUT_FILE_CSV)


# ---------------------------------------------------------
# 6. 확인
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("결과")
print("=" * 60)

print(f"행 수  {len(df):,}")

print("\n샘플 3건")
print(df.head(3).to_string())

print("\n다음 단계: 02_preprocess_b.py (결측 제거)")
