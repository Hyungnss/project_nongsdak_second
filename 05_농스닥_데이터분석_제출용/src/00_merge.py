"""
0단계 — 연도별 CSV 15개를 하나로 통합

실행:
    python 00_merge.py

하는 일
    1) data/raw 폴더의 CSV 를 모두 찾아 읽는다
    2) 컬럼이 서로 같은지 비교한다   ← 가장 중요
    3) 출처 파일명을 남기고 위아래로 이어붙인다(concat)
    4) 파일별 행수·날짜범위를 요약해 검증한다

왜 concat 인가
    merge 는 다른 정보를 공통 키로 '옆에' 붙일 때 쓴다.
    여기서는 같은 구조의 데이터가 파일만 나뉜 것이므로 '위아래로' 쌓는다.
"""

from pathlib import Path

import pandas as pd


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUT_DIR = PROJECT_ROOT / "data" / "processed"

OUT_DIR.mkdir(parents=True, exist_ok=True)


ENCODINGS = ("utf-8-sig", "cp949", "euc-kr", "utf-8", "utf-16", "utf-16-le", "cp1252")


def sniff_format(path):
    """파일 앞부분 바이트로 정체를 파악합니다.

    확장자가 csv 여도 실제로는 엑셀인 경우가 있습니다.
    """

    with open(path, "rb") as f:
        head = f.read(8)

    if head.startswith(b"PK\x03\x04"):
        return "xlsx"          # zip 시그니처 = 엑셀
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "xls"           # 구형 엑셀
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if head.startswith(b"\xff\xfe") or head.startswith(b"\xfe\xff"):
        return "utf-16"

    return None


def read_csv_any(path):
    """형식과 인코딩을 판별해 읽습니다."""

    fmt = sniff_format(path)

    # 확장자만 csv 인 엑셀 파일 처리
    if fmt in ("xlsx", "xls"):
        print(f"    ※ {path.name} 은 실제로 엑셀 파일입니다 → 엑셀로 읽습니다")
        return pd.read_excel(path, dtype=str), f"excel({fmt})"

    # BOM 으로 확정된 인코딩이 있으면 먼저 시도
    candidates = ([fmt] if fmt else []) + [e for e in ENCODINGS if e != fmt]

    for encoding in candidates:
        try:
            return pd.read_csv(path, encoding=encoding, dtype=str,
                               low_memory=False), encoding
        except (UnicodeDecodeError, UnicodeError):
            continue
        except pd.errors.ParserError:
            # 구분자가 다를 수 있습니다 (탭·세미콜론)
            for sep in ("\t", ";", "|"):
                try:
                    return pd.read_csv(path, encoding=encoding, sep=sep,
                                       dtype=str, low_memory=False), f"{encoding}/sep={sep!r}"
                except Exception:
                    continue

    # charset-normalizer 로 자동 감지 (requests 설치 시 함께 깔려 있습니다)
    try:
        from charset_normalizer import from_path

        best = from_path(path).best()

        if best:
            print(f"    ※ 자동 감지: {best.encoding}")
            return pd.read_csv(path, encoding=best.encoding, dtype=str,
                               low_memory=False), f"{best.encoding}(auto)"

    except ImportError:
        pass
    except Exception:
        pass

    # 마지막 수단 — 깨진 문자는 대체 문자로 바꿔 읽습니다.
    print(f"    ※ {path.name}: 인코딩 판별 실패 → cp949 + errors='replace' 로 강제 읽기")
    print("       일부 글자가 깨질 수 있으니 결과를 반드시 확인하세요.")

    return pd.read_csv(path, encoding="cp949", encoding_errors="replace",
                       dtype=str, low_memory=False), "cp949(replace)"


# ---------------------------------------------------------
# 1. 파일 목록
# ---------------------------------------------------------

files = sorted(RAW_DIR.glob("*.csv"))

if not files:
    raise FileNotFoundError(f"CSV 가 없습니다: {RAW_DIR}")

print(f"CSV {len(files)}개 발견\n")


# ---------------------------------------------------------
# 2. 읽으면서 컬럼 비교
# ---------------------------------------------------------

frames = []
column_sets = {}

for path in files:

    df, encoding = read_csv_any(path)

    # 컬럼명 앞뒤 공백 제거 — 이것만으로도 불일치가 꽤 사라집니다
    df.columns = [c.strip() for c in df.columns]

    column_sets[path.name] = tuple(df.columns)

    # 어느 파일에서 왔는지 남깁니다. 나중에 문제 추적에 씁니다.
    df["출처파일"] = path.name

    frames.append(df)

    print(f"  {path.name}")
    print(f"    {len(df):>10,}행  encoding={encoding}  컬럼 {len(df.columns) - 1}개")


# ---------------------------------------------------------
# 3. 컬럼 일치 검사 — 여기가 핵심
# ---------------------------------------------------------

print("\n" + "=" * 70)
print("컬럼 일치 검사")
print("=" * 70)

unique_sets = set(column_sets.values())

if len(unique_sets) == 1:
    print("모든 파일의 컬럼이 동일합니다.")
    print(f"  {list(unique_sets)[0]}")

else:
    print(f"컬럼 구성이 {len(unique_sets)}가지로 갈립니다. 확인이 필요합니다.\n")

    # 기준은 가장 많은 파일이 쓰는 구성으로 잡습니다.
    from collections import Counter

    counter = Counter(column_sets.values())
    base_cols, base_count = counter.most_common(1)[0]

    print(f"[기준] {base_count}개 파일이 쓰는 구성")
    print(f"  {list(base_cols)}\n")

    for name, cols in column_sets.items():

        if cols == base_cols:
            continue

        only_here = set(cols) - set(base_cols)
        missing = set(base_cols) - set(cols)

        print(f"[다름] {name}")
        if only_here:
            print(f"  이 파일에만 있음: {sorted(only_here)}")
        if missing:
            print(f"  이 파일에 없음:   {sorted(missing)}")

    print("\n→ 컬럼명만 다르고 의미가 같다면, 아래 RENAME 에 매핑을 추가한 뒤 다시 실행하세요.")
    print("   그대로 두면 concat 시 별개 컬럼이 생기고 절반이 NaN 이 됩니다.")


# 컬럼명이 다른 파일이 있으면 여기에 매핑을 채웁니다.
#   예) "조사일자": "가격등록일자"
RENAME = {
    # "조사일자": "가격등록일자",
}

if RENAME:
    frames = [df.rename(columns=RENAME) for df in frames]
    print(f"\n컬럼명 매핑 적용: {RENAME}")


# ---------------------------------------------------------
# 4. 통합
# ---------------------------------------------------------

print("\n" + "=" * 70)
print("통합")
print("=" * 70)

merged = pd.concat(frames, ignore_index=True)

print(f"통합 결과: {len(merged):,}행 × {len(merged.columns)}컬럼")
print(f"컬럼: {merged.columns.tolist()}")

# concat 후 NaN 이 몰린 컬럼이 있으면 컬럼 불일치의 흔적입니다.
na_ratio = merged.isna().mean()
suspicious = na_ratio[na_ratio > 0.3]

if len(suspicious) > 0:
    print("\n[주의] 결측이 30% 넘는 컬럼")
    for col, ratio in suspicious.items():
        print(f"  {col:<20} {ratio * 100:.1f}%")
    print("→ 컬럼명이 파일마다 달라 갈라졌을 수 있습니다. 위 검사 결과와 대조하세요.")


# ---------------------------------------------------------
# 5. 파일별 검증 — 연도가 제자리에 있는지
# ---------------------------------------------------------

print("\n" + "=" * 70)
print("파일별 요약")
print("=" * 70)

DATE_COL = "가격등록일자"

if DATE_COL in merged.columns:

    date = pd.to_datetime(merged[DATE_COL].astype(str).str.strip(), errors="coerce")
    merged["_날짜"] = date

    summary = merged.groupby("출처파일")["_날짜"].agg(
        건수="size", 최소="min", 최대="max"
    )

    print(summary.to_string())

    print("\n연도별 건수")
    print(merged["_날짜"].dt.year.value_counts().sort_index().to_string())

    failed = date.isna().sum()
    if failed:
        print(f"\n날짜 변환 실패: {failed:,}건 (형식이 다른 파일이 있는지 확인)")

    merged = merged.drop(columns=["_날짜"])

else:
    print(f"'{DATE_COL}' 컬럼이 없습니다. 실제 컬럼명을 확인하세요.")


# ---------------------------------------------------------
# 6. 저장
# ---------------------------------------------------------

try:
    out_path = OUT_DIR / "price_merged.parquet"
    merged.to_parquet(out_path, index=False)
except Exception:
    out_path = OUT_DIR / "price_merged.csv"
    merged.to_csv(out_path, index=False, encoding="utf-8-sig")
    print("\n(parquet 실패 — pip install pyarrow 를 권합니다)")

size_mb = out_path.stat().st_size / 1024 / 1024

print(f"\n저장: {out_path}  ({size_mb:,.1f} MB)")
print("다음 단계: python 01_inspect.py")
