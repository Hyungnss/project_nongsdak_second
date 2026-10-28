"""
14단계 — 가격이 가장 크게 오른 해 찾기

실행:
    python 14_year_rise.py

입력  data/processed/price_e.parquet   (02_preprocess_e.py 결과)
      없으면 price_e.csv 를 읽습니다.

출력  data/processed/year_rise.csv        연도별 상승률
      data/processed/year_rise_items.csv  가장 많이 오른 해의 품목별 상승률
      화면에도 전부 찍습니다. 웹페이지는 만들지 않습니다.


무엇을 구하는가

    "전년 대비 가격이 가장 많이 오른 해는 언제인가"

    가격 수준이 가장 높은 해가 아니라, 가장 많이 '오른' 해입니다.
    물가는 해마다 조금씩 오르므로 가격 수준은 보통 마지막 해가 제일 높습니다.
    그건 답이 될 수 없습니다.


그냥 평균 내면 왜 틀리는가 — 세 가지 함정

    1) 품목 구성이 해마다 바뀐다
       2020년에 없던 비싼 품목이 2021년에 들어오면
       가격이 오르지 않았어도 평균은 올라갑니다.
       → 두 해에 '모두 있는' 상품만 짝지어 비교합니다.

    2) 조사 달이 해마다 다르다
       올해가 1~8월까지만 있으면, 배추가 비싼 겨울이 빠져
       실제보다 싸게 나옵니다.
       → 두 해에 '공통으로 있는 달'만 씁니다.

    3) 비싼 품목이 평균을 끌고 간다
       한우 1kg 과 배추 1kg 을 같이 평균 내면 한우만 보입니다.
       → 상품마다 '몇 배가 됐는지' 비율을 낸 뒤,
         그 비율들의 중앙값을 씁니다. 금액이 아니라 배율로 봅니다.


계산 방법

    상품    = 품목 + 품종 + 등급 + 단위계열(unit_base)
    월 대표 = 그 상품 그 달의 unit_price 중앙값
    상품 비율 = (올해 공통달 중앙값) / (작년 공통달 중앙값)
    그 해 상승률 = 상품 비율들의 중앙값

    unit_price 는 02_preprocess_e.py 가 만든 1단위당 가격입니다.
    무게는 kg 로 환산돼 있어 '100g 에서 1kg 로 조사단위가 바뀐' 경우에도
    값이 튀지 않습니다.

    kg 계열과 마리·포기 계열은 성격이 달라 unit_base 로 갈라 둡니다.
    같은 상품끼리만 비교하므로 섞일 일은 없습니다.


한계

    · 명목 가격입니다. 물가상승분을 빼지 않았습니다.
      물가를 걷어낸 실질 상승은 09_analyze.py 의 Q3 를 보세요.
    · 지역(시도)을 나누지 않고 전국을 묶어 중앙값을 냅니다.
      조사 지역 구성이 크게 바뀐 해가 있으면 그만큼 흔들립니다.
    · 상관이 아니라 단순 비교입니다. '왜 올랐는지' 는 말하지 않습니다.
"""

import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data" / "processed"

IN_FILE = DATA_DIR / "price_e.parquet"
IN_FILE_CSV = DATA_DIR / "price_e.csv"

OUT_YEAR = DATA_DIR / "year_rise.csv"
OUT_ITEM = DATA_DIR / "year_rise_items.csv"


# 상품을 가르는 기준
#   등급까지 넣습니다. 상품과 중품은 가격대가 달라 섞으면 안 됩니다.
PRODUCT_KEYS = ["item_name", "variety_name", "grade_name", "unit_base"]

# 두 해를 견주려면 겹치는 달이 최소 몇 개는 있어야 하는가
#   6 이면 반년입니다. 3 으로 낮추면 계절이 한쪽으로 쏠릴 수 있습니다.
MIN_MONTHS = 6

# 그 해 상승률을 믿으려면 짝지어진 상품이 최소 몇 개는 있어야 하는가
MIN_PRODUCTS = 10

# 단위가 도중에 바뀐 행(unit_mismatch)을 뺄지
#   unit_price 가 이미 단위크기로 나눈 값이라 보통은 둬도 됩니다.
#   결과가 의심스러우면 True 로 두고 다시 돌려 비교해 보세요.
DROP_UNIT_MISMATCH = False

# 품목별 표에 몇 개까지 찍을지 (csv 에는 전부 들어갑니다)
TOP_N = 15

# 분석에 실제로 쓰는 컬럼만 읽습니다.
#   price_e 는 date · price · sido_name 등 안 쓰는 컬럼이 많습니다.
#   수백만 행에서는 그것만 빼도 읽는 시간과 메모리가 크게 줄어듭니다.
USE_COLS = ["year", "month", "item_name", "variety_name", "grade_name",
            "unit_price", "unit_base", "market_type_code", "unit_mismatch"]

# 문자열을 category 로 읽으면 메모리가 훨씬 적게 듭니다.
#   같은 품목명이 수만 번 반복되므로 효과가 큽니다.
CAT_COLS = ["item_name", "variety_name", "grade_name",
            "unit_base", "market_type_code"]

_T0 = time.time()


def tick(message):
    """어디서 시간이 걸리는지 보이게 합니다. 멈춘 건지 도는 건지 알 수 있습니다."""
    print(f"  [{time.time() - _T0:5.1f}초] {message}")


# ---------------------------------------------------------
# 0. 표 맞추기
#    한글은 터미널에서 두 칸을 차지하는데 파이썬 format 은 한 칸으로 셉니다.
#    그대로 두면 한글이 섞인 열이 오른쪽으로 밀려 표가 어긋납니다.
# ---------------------------------------------------------

def width(text):
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1
               for ch in str(text))


def lpad(text, n):
    return str(text) + " " * max(0, n - width(text))


def rpad(text, n):
    return " " * max(0, n - width(text)) + str(text)


# ---------------------------------------------------------
# 1. 읽기
# ---------------------------------------------------------

print("=" * 66)
print("가격이 가장 크게 오른 해 찾기")
print("=" * 66)

if IN_FILE.exists():
    print(f"\n읽기: {IN_FILE.name}")
    try:
        df = pd.read_parquet(IN_FILE, columns=USE_COLS)
    except Exception as err:
        # 파일에 없는 컬럼을 지정하면 오류가 납니다. 그때는 통째로 읽습니다.
        # (parquet 은 문자열이 object 로 들어오는데, 측정해 보니 그대로가 제일 빠릅니다.
        #  category 로 바꾸면 메모리는 줄지만 그룹 묶기가 오히려 느려집니다.)
        print(f"  일부 컬럼만 읽기 실패 — 전체를 읽습니다 ({type(err).__name__})")
        df = pd.read_parquet(IN_FILE)
    tick(f"{len(df):,}행 읽음")

elif IN_FILE_CSV.exists():
    print(f"\n읽기: {IN_FILE_CSV.name}")
    print("  (parquet 이 없어 csv 를 읽습니다. 큰 파일이면 여기가 제일 오래 걸립니다.")
    print("   pip install pyarrow 후 02_preprocess_e.py 를 다시 돌리면 훨씬 빨라집니다.)")
    df = pd.read_csv(
        IN_FILE_CSV, encoding="utf-8-sig",
        usecols=lambda c: c in USE_COLS,            # 없는 컬럼은 조용히 넘어갑니다
        dtype={c: "category" for c in CAT_COLS},
        low_memory=False)
    tick(f"{len(df):,}행 읽음")

else:
    raise FileNotFoundError(
        f"먼저 02_preprocess_e.py 를 실행하세요.\n"
        f"  찾은 곳: {IN_FILE}")

need = ["year", "month", "unit_price", "unit_base", "item_name"]
missing = [c for c in need if c not in df.columns]

if missing:
    raise KeyError(
        f"꼭 필요한 컬럼이 없습니다: {missing}\n"
        f"  실제 컬럼: {df.columns.tolist()}\n"
        f"  unit_price · unit_base 는 02_preprocess_e.py 가 만듭니다. "
        f"price_d 를 잘못 넣지 않았는지 확인하세요.")

# 없어도 되는 상품 키는 '-' 로 채웁니다 (등급이 없는 자료도 있습니다)
for col in PRODUCT_KEYS:
    if col not in df.columns:
        print(f"  {col} 컬럼이 없어 '-' 로 채웁니다")
        df[col] = "-"


# ---------------------------------------------------------
# 2. 걸러내기
# ---------------------------------------------------------

start = len(df)

df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
df["year"] = pd.to_numeric(df["year"], errors="coerce")
df["month"] = pd.to_numeric(df["month"], errors="coerce")

bad = (df["unit_price"].isna() | ~np.isfinite(df["unit_price"])
       | (df["unit_price"] <= 0)
       | df["year"].isna() | df["month"].isna())

if bad.any():
    print(f"  가격·날짜가 비었거나 0 이하인 행 제외: {bad.sum():,}건")
    df = df[~bad]          # 불리언 색인이 이미 새 프레임을 만듭니다. copy() 는 낭비입니다.

df["year"] = df["year"].astype("int16")
df["month"] = df["month"].astype("int8")

tick(f"거르기 끝  {len(df):,}행")

if DROP_UNIT_MISMATCH and "unit_mismatch" in df.columns:
    n = int(df["unit_mismatch"].sum())
    if n:
        print(f"  단위가 도중에 바뀐 행 제외: {n:,}건 (DROP_UNIT_MISMATCH=True)")
        df = df[~df["unit_mismatch"]]

elif "unit_mismatch" in df.columns and df["unit_mismatch"].any():
    print(f"  단위가 도중에 바뀐 행 {int(df['unit_mismatch'].sum()):,}건이 섞여 있습니다.")
    print(f"    unit_price 가 단위크기로 나눈 값이라 보통은 괜찮습니다.")
    print(f"    의심되면 DROP_UNIT_MISMATCH = True 로 두고 다시 돌려 비교하세요.")

# 도매가 섞여 있으면 가격대가 달라 결과가 흔들립니다
if "market_type_code" in df.columns and df["market_type_code"].nunique() > 1:
    print(f"\n  [주의] 도소매 구분이 {df['market_type_code'].nunique()}종 섞여 있습니다: "
          f"{sorted(df['market_type_code'].dropna().unique())[:5]}")
    print(f"         02_preprocess_b.py 에서 소매만 남겼는지 확인하세요.")

print(f"  분석 대상: {len(df):,}행 (시작 {start:,}행)")


# ---------------------------------------------------------
# 3. 상품 · 월 대표값
#    같은 달에 조사가 여러 번 있으므로 먼저 달 단위로 접습니다.
#    이렇게 해야 조사 횟수가 많은 달이 결과를 끌고 가지 않습니다.
# ---------------------------------------------------------

# 상품에 번호를 매깁니다.
#   전에는 df[KEYS].astype(str).agg(" | ".join, axis=1) 로 문자열을 만들었는데,
#   agg(axis=1) 은 행마다 파이썬 함수를 부르는 방식이라 500만 행에 10초가 넘게 듭니다.
#   ngroup 은 같은 일을 C 쪽에서 처리해 0.4초면 끝나고,
#   뒤따르는 groupby·merge 도 문자열 대신 정수를 다뤄 더 빨라집니다.
grp = df.groupby(PRODUCT_KEYS, observed=True, sort=False)
df["pkey"] = grp.ngroup()
tick(f"상품 번호 매김  {df['pkey'].nunique():,}개")

monthly = (df.groupby(["pkey", "year", "month"], observed=True)["unit_price"]
             .median()
             .reset_index(name="v"))
tick(f"월 대표값 계산  {len(monthly):,}칸")

years = sorted(monthly["year"].unique())

print(f"\n기간: {years[0]} ~ {years[-1]}  ({len(years)}개 연도)")
print(f"상품: {monthly['pkey'].nunique():,}개  "
      f"(품목 {df['item_name'].nunique():,}개)")

# 연도마다 몇 달치가 있는지 — 덜 찬 해를 미리 알려 둡니다
span = monthly.groupby("year")["month"].nunique()
partial = span[span < 12]

if len(partial):
    print("\n  달이 덜 찬 해가 있습니다:")
    for y, m in partial.items():
        print(f"    {y}년 {m}개월치")
    print("    → 겹치는 달만 비교하므로 상승률 자체는 왜곡되지 않습니다.")
    print("      다만 그 해는 몇 달만으로 판단한 값이라는 점을 기억하세요.")


# ---------------------------------------------------------
# 4. 전년 대비 상승률
#    (pkey, month) 로 붙이면 '두 해 모두에 있는 상품' 과
#    '두 해 공통인 달' 이 한 번에 걸러집니다.
# ---------------------------------------------------------

print("\n" + "=" * 66)
print("연도별 상승률 (전년 대비)")
print("=" * 66)

# 번호 → 이름 되찾기용. 정수 한 칸으로 중복을 지워 문자열 비교를 피합니다.
info = (df[["pkey"] + PRODUCT_KEYS]
        .drop_duplicates("pkey")
        .set_index("pkey"))

rows = []
ratios_by_year = {}

for prev, cur in zip(years, years[1:]):

    if cur - prev != 1:
        print(f"  {prev} → {cur}: 사이에 빠진 해가 있어 건너뜁니다")
        continue

    a = monthly[monthly["year"] == prev]
    b = monthly[monthly["year"] == cur]

    pair = a.merge(b, on=["pkey", "month"], suffixes=("_0", "_1"))

    if pair.empty:
        print(f"  {prev} → {cur}: 겹치는 상품·달이 없어 건너뜁니다")
        continue

    g = pair.groupby("pkey", observed=True).agg(
        v0=("v_0", "median"), v1=("v_1", "median"), months=("month", "nunique"))

    g = g[g["months"] >= MIN_MONTHS]

    if len(g) < MIN_PRODUCTS:
        print(f"  {prev} → {cur}: 짝지어진 상품이 {len(g)}개뿐이라 건너뜁니다 "
              f"(최소 {MIN_PRODUCTS}개)")
        continue

    g["ratio"] = g["v1"] / g["v0"]
    ratios_by_year[cur] = g

    rise = (g["ratio"].median() - 1) * 100
    up_share = (g["ratio"] > 1).mean() * 100

    rows.append({
        "year": cur,
        "prev_year": prev,
        "rise_pct": round(rise, 2),
        "up_share_pct": round(up_share, 1),
        "products": len(g),
        "median_months": int(g["months"].median()),
    })

if not rows:
    raise SystemExit(
        "\n비교할 수 있는 연도 짝이 없습니다.\n"
        "  기간이 1년뿐이거나, 겹치는 상품·달이 너무 적습니다.\n"
        f"  MIN_MONTHS({MIN_MONTHS}) · MIN_PRODUCTS({MIN_PRODUCTS}) 를 낮춰 보세요.")

year_tbl = pd.DataFrame(rows)

# 화면용 막대 — 눈으로 크기를 견주기 쉽게
scale = max(abs(year_tbl["rise_pct"]).max(), 1)

print("\n" + lpad("연도", 8) + rpad("상승률", 9) + "   " + lpad("", 24)
      + rpad("오른 상품", 10) + rpad("상품 수", 9) + rpad("공통 달", 9))
print("-" * 66)

for _, r in year_tbl.iterrows():
    # iterrows 는 한 줄을 하나의 dtype 으로 묶어 정수 칸도 float 가 된다.
    # 그대로 찍으면 "상품 15.0개" 처럼 나오므로 int 로 되돌린다.
    bar_len = int(abs(r["rise_pct"]) / scale * 22)
    bar = ("+" if r["rise_pct"] >= 0 else "-") * max(bar_len, 1)
    print(lpad(int(r["year"]), 8)
          + f"{r['rise_pct']:>8.2f}%" + "   " + lpad(bar, 24)
          + f"{r['up_share_pct']:>9.1f}%"
          + f"{int(r['products']):>9,}"
          + f"{int(r['median_months']):>9}")


# ---------------------------------------------------------
# 5. 답
# ---------------------------------------------------------

best = year_tbl.loc[year_tbl["rise_pct"].idxmax()]
worst = year_tbl.loc[year_tbl["rise_pct"].idxmin()]

print("\n" + "=" * 66)
print("답")
print("=" * 66)

print(f"\n  가격이 가장 크게 오른 해는  {int(best['year'])}년  입니다.")
print(f"    {int(best['prev_year'])}년 대비 {best['rise_pct']:+.2f}%  "
      f"(상품 {int(best['products']):,}개의 중앙값)")
print(f"    그 해에 오른 상품이 전체의 {best['up_share_pct']:.1f}% 였습니다.")

if best["rise_pct"] <= 0:
    print("\n    [주의] 가장 큰 값도 0% 이하입니다. "
          "이 기간에는 오른 해가 없었다는 뜻입니다.")

# 최솟값이 양수면 '내린' 게 아니라 '덜 오른' 것이다. 말을 바꿔야 한다.
if worst["rise_pct"] < 0:
    print(f"\n  가장 많이 내린 해는 {int(worst['year'])}년 "
          f"({worst['rise_pct']:+.2f}%) 입니다.")
else:
    print(f"\n  가장 적게 오른 해는 {int(worst['year'])}년 "
          f"({worst['rise_pct']:+.2f}%) 입니다. 내린 해는 없습니다.")

# 사람 눈으로 다시 확인할 수 있게 근거를 한 줄 덧붙입니다
tie = year_tbl[year_tbl["rise_pct"] >= best["rise_pct"] - 0.5]

if len(tie) > 1:
    others = ", ".join(f"{int(y)}년({v:+.2f}%)"
                       for y, v in zip(tie["year"], tie["rise_pct"])
                       if y != best["year"])
    print(f"\n    [참고] {others} 와 0.5%p 안쪽 차이입니다. "
          f"어느 해라고 단정하기 어렵습니다.")


# ---------------------------------------------------------
# 6. 그 해에 무엇이 올랐나
# ---------------------------------------------------------

print("\n" + "=" * 66)
print(f"{int(best['year'])}년에 많이 오른 품목")
print("=" * 66)

g = ratios_by_year[int(best["year"])].join(info)

by_item = (g.groupby("item_name", observed=True)
             .agg(rise_pct=("ratio", lambda s: (s.median() - 1) * 100),
                  products=("ratio", "size"))
             .sort_values("rise_pct", ascending=False)
             .reset_index())

by_item["rise_pct"] = by_item["rise_pct"].round(2)

print("\n" + lpad("품목", 18) + rpad("상승률", 10) + rpad("상품 수", 10))
print("-" * 40)

for _, r in by_item.head(TOP_N).iterrows():
    print(lpad(r["item_name"], 18)
          + f"{r['rise_pct']:>9.2f}%" + f"{int(r['products']):>10,}")

if len(by_item) > TOP_N:
    print(f"\n  ... 나머지 {len(by_item) - TOP_N}개 품목은 {OUT_ITEM.name} 에 있습니다.")

fell = by_item[by_item["rise_pct"] < 0]

if len(fell):
    print(f"\n  같은 해에 내린 품목도 {len(fell)}개 있습니다. 낙폭이 큰 순으로 5개:")
    for _, r in fell.tail(5)[::-1].iterrows():
        print("    " + lpad(r["item_name"], 18) + f"{r['rise_pct']:>9.2f}%")


# ---------------------------------------------------------
# 7. 저장
# ---------------------------------------------------------

year_tbl.to_csv(OUT_YEAR, index=False, encoding="utf-8-sig")
by_item.to_csv(OUT_ITEM, index=False, encoding="utf-8-sig")

print("\n" + "=" * 66)
print("저장")
print("=" * 66)
print(f"  {OUT_YEAR}")
print(f"  {OUT_ITEM}")

print(f"\n총 {time.time() - _T0:.1f}초 걸렸습니다.")

print("\n보고서에 함께 적을 것")
print("  · 명목 가격입니다. 물가상승분을 빼지 않았습니다.")
print("  · 두 해 모두에 있는 상품, 두 해 공통인 달만 견줬습니다.")
print("  · 금액 평균이 아니라 상품별 배율의 중앙값입니다.")
print("    비싼 품목 하나가 전체를 끌고 가지 않게 하려는 것입니다.")
