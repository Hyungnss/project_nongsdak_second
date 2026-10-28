"""
2-e단계 — 단위 정규화 (단가 계산)

실행:
    python 02_preprocess_e.py

입력  data/processed/price_d.parquet
출력  data/processed/price_e.parquet   (다음 단계용)
      data/processed/price_e.csv       (눈으로 확인용)

왜 필요한가
    품목마다 조사 단위가 다릅니다.

        배추   1 포기      쌀     20 kg
        고등어 1 마리      미나리 100 g

    가격을 그대로 비교하면 '20kg 쌀'과 '1포기 배추'를 견주는 꼴이 됩니다.
    단위크기로 나눠 1단위당 가격을 구하고,
    무게 단위는 kg 기준으로 다시 맞춥니다.

    다만 kg 계열과 개수 계열(마리·포기)은 성격이 달라
    unit_base 로 구분해 둡니다. 둘을 섞어 비교하면 안 됩니다.
"""

from pathlib import Path

import numpy as np
import pandas as pd


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

OUT_DIR = PROJECT_ROOT / "data" / "processed"

IN_FILE = OUT_DIR / "price_d.parquet"
IN_FILE_CSV = OUT_DIR / "price_d.csv"

OUT_FILE = OUT_DIR / "price_e.parquet"
OUT_FILE_CSV = OUT_DIR / "price_e.csv"


# 무게 단위를 kg 로 환산하는 배수
#   실행하면 실제 단위명 분포를 찍어 주므로, 빠진 게 있으면 추가하세요.
WEIGHT_UNITS = {
    "kg": 1.0, "KG": 1.0, "Kg": 1.0,
    "g": 0.001, "G": 0.001,
    "톤": 1000.0, "t": 1000.0,
}

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
    df["date"] = pd.to_datetime(df["date"])
    print(f"읽기: {len(df):,}행 (csv)")

else:
    raise FileNotFoundError(f"먼저 02_preprocess_d.py 를 실행하세요.\n  {IN_FILE}")

start_count = len(df)


# ---------------------------------------------------------
# 2. 단위 구성 확인
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("단위명 분포")
print("=" * 60)

unit_dist = df["retail_unit_name"].value_counts(dropna=False)

for name, count in unit_dist.items():
    mark = "  ← 무게(kg 환산)" if name in WEIGHT_UNITS else ""
    print(f"  {str(name):<10} {count:>12,}건 ({count / len(df) * 100:5.1f}%){mark}")

not_mapped = [n for n in unit_dist.index
              if pd.notna(n) and n not in WEIGHT_UNITS]

print(f"\n개수 단위(환산 없이 1단위당 가격): {not_mapped}")


# ---------------------------------------------------------
# 3. 단위크기 숫자 변환
# ---------------------------------------------------------

df["retail_unit_size"] = pd.to_numeric(
    df["retail_unit_size"].astype(str).str.replace(",", "").str.strip(),
    errors="coerce"
)

bad = df["retail_unit_size"].isna() | (df["retail_unit_size"] <= 0)

if bad.any():
    print(f"\n단위크기 이상 {bad.sum():,}건 제외")
    print(df.loc[bad, ["item_name", "variety_name", "retail_unit_name"]]
          .head(5).to_string())
    df = df[~bad].copy()


# ---------------------------------------------------------
# 4. 단가 계산
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("단가 계산")
print("=" * 60)

# 1단위당 가격
df["unit_price"] = df["price"] / df["retail_unit_size"]

# 무게 단위면 kg 기준으로 환산
#   예) 100 g 에 3,000원  →  1g 당 30원  →  1kg 당 30,000원
ratio = df["retail_unit_name"].map(WEIGHT_UNITS)
is_weight = ratio.notna()

df["unit_price"] = np.where(is_weight, df["unit_price"] / ratio, df["unit_price"])
df["unit_base"] = np.where(is_weight, "kg", df["retail_unit_name"])

df["unit_price"] = df["unit_price"].round(2)

print(f"  무게 단위 {is_weight.sum():,}건 → kg 기준 환산")
print(f"  개수 단위 {(~is_weight).sum():,}건 → 그대로")

print("\nunit_base 분포")
print(df["unit_base"].value_counts().to_string())


# ---------------------------------------------------------
# 5. 단위 일관성 검사
#    품목만 보면 안 됩니다.
#    고등어는 생물이 '마리', 염장이 '손' 처럼
#    품종이 다르면 단위도 다른 게 정상입니다.
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("단위 일관성 (품목 + 품종 기준)")
print("=" * 60)

df["_unit"] = (df["retail_unit_size"].astype(str)
               + " " + df["retail_unit_name"].astype(str))

counts = df.groupby(["item_name", "variety_name"], observed=True)["_unit"].nunique()
problem = counts[counts > 1]

df["unit_mismatch"] = pd.MultiIndex.from_frame(
    df[["item_name", "variety_name"]]
).isin(problem.index)

print(f"\n같은 품목·품종인데 단위가 2개 이상: {len(problem)}개 조합")

if len(problem) == 0:
    print("  없음 — 품종 단위로 분석하면 안전합니다.")

else:
    changed, coexist = [], []

    for item, variety in problem.index:

        sub = df[(df["item_name"] == item) & (df["variety_name"] == variety)]

        detail = (sub.groupby("_unit")
                  .agg(n=("_unit", "size"), y0=("year", "min"), y1=("year", "max"))
                  .sort_values("n", ascending=False))

        spans = list(zip(detail["y0"], detail["y1"]))
        overlap = any(
            spans[i][0] <= spans[j][1] and spans[j][0] <= spans[i][1]
            for i in range(len(spans)) for j in range(i + 1, len(spans))
        )

        (coexist if overlap else changed).append((item, variety, detail))

    if changed:
        print(f"\n[위험] 단위가 도중에 교체됨 — {len(changed)}개")
        print("       연도가 겹치지 않습니다. 시계열이 끊깁니다.")

        for item, variety, detail in changed:
            print(f"\n  {item} / {variety}")
            for unit, row in detail.iterrows():
                print(f"    {unit:<12} {row['n']:>8,}건  ({row['y0']}~{row['y1']})")

    if coexist:
        print(f"\n[확인] 같은 기간에 병존 — {len(coexist)}개")
        print("       등급·규격 차이일 수 있습니다.")

        for item, variety, detail in coexist:
            total = detail["n"].sum()
            print(f"\n  {item} / {variety}")
            for unit, row in detail.iterrows():
                print(f"    {unit:<12} {row['n']:>8,}건 ({row['n'] / total * 100:5.1f}%)  "
                      f"({row['y0']}~{row['y1']})")

    print(f"\n→ unit_mismatch 컬럼에 표시했습니다. "
          f"({df['unit_mismatch'].sum():,}건)")
    print("   지우지 않았으니 다음 단계에서 뺄지 판단하세요.")

df = df.drop(columns=["_unit"])


# ---------------------------------------------------------
# 6. 저장
# ---------------------------------------------------------

df = df.reset_index(drop=True)

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

print("\nunit_price 분포 (kg 기준만)")
kg_only = df[df["unit_base"] == "kg"]["unit_price"]
print(kg_only.describe().to_string())

print("\nkg당 단가가 비싼 품목 상위 10")
top = (df[df["unit_base"] == "kg"]
       .groupby("item_name", observed=True)["unit_price"]
       .median()
       .sort_values(ascending=False)
       .head(10))
for item, price in top.items():
    print(f"  {item:<15} {price:>12,.0f}원/kg")

print("\nkg당 단가가 싼 품목 상위 10")
bottom = (df[df["unit_base"] == "kg"]
          .groupby("item_name", observed=True)["unit_price"]
          .median()
          .sort_values()
          .head(10))
for item, price in bottom.items():
    print(f"  {item:<15} {price:>12,.0f}원/kg")

print("\n→ 위 두 목록이 상식과 맞는지 확인하세요.")
print("   소고기·잣이 비싸고 배추·무가 싸면 환산이 제대로 된 것입니다.")

print("\n샘플 3건")
print(df[["year", "month", "item_name", "variety_name", "price",
          "retail_unit_size", "retail_unit_name", "unit_price", "unit_base"]]
      .head(3).to_string(index=False))

print("\n다음 단계: 03_weekly.py (주별 평균)")
