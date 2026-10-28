"""
16단계 — 계절 진폭 분포 보기  (Q1 판정선을 정하기 위한 자료)

실행:
    python 16_amplitude_dist.py            있는 주기 전부
    python 16_amplitude_dist.py week       주별만
    python 16_amplitude_dist.py month day  월별·일별

입력  data/processed/q1_season_<주기>.csv     (09_analyze.py 결과)
출력  화면 + reports/amplitude_dist_<주기>.txt  (화면에 찍힌 것과 같은 내용)


무엇에 쓰는가

    09_analyze.py 는 계절 진폭 0.20 이상을 '뚜렷한 계절 패턴' 으로 본다.
    그런데 이 0.20 은 근거가 있는 값이 아니라 그냥 박혀 있던 숫자다.

    이 스크립트는 "이 자료에서 진폭이 실제로 어떻게 퍼져 있는가" 를 보여 준다.
    그것을 보고 판정선을 정하면 보고서에 이렇게 쓸 수 있다.

        "이 자료에서 진폭 상위 25%(0.__ 이상)를 뚜렷하다고 봤다"

    정한 값은 09_analyze.py 의 Q1_STRONG_AMPLITUDE 에 넣으면 된다.


계절 진폭이란

    평년값(그 주차의 가격지수 중앙값)의 최대 - 최소.
    0.50 이면 1년 사이 그 상품 평소 값의 50%p 만큼 오르내렸다는 뜻이다.

    ★ 지금 파이프라인은 물가상승을 걷어내지 않는다.
      10년 동안 값이 오르기만 한 상품도 최고-최저 차이가 벌어져
      계절 패턴이 없어도 진폭이 커질 수 있다.
      그래서 아래 '연도 추세' 칸을 함께 본다.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data" / "processed"
OUT_DIR = PROJECT_ROOT / "reports"

OUT_DIR.mkdir(parents=True, exist_ok=True)

FREQ_LABEL = {"day": "일별", "week": "주별", "month": "월별"}

# 화면에 견줘 볼 고정 판정선 후보
FIXED_LINES = [0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60]

# 지금 09_analyze.py 가 쓰는 값.
# 같은 숫자를 두 파일에 박아 두면 한쪽만 고쳤을 때 조용히 어긋난다.
# 그래서 09_analyze.py 에서 직접 읽어 온다. 못 읽으면 0.20 으로 둔다.
def current_line(default=0.20):

    import re

    source = CURRENT_DIR / "09_analyze.py"

    if not source.exists():
        return default

    hit = re.search(r"^Q1_STRONG_AMPLITUDE\s*=\s*([0-9.]+)",
                    source.read_text(encoding="utf-8"), re.M)

    return float(hit.group(1)) if hit else default


CURRENT_LINE = current_line()

HIST_STEP = 0.05      # 히스토그램 칸 너비
HIST_WIDTH = 46       # 막대 최대 길이 (글자 수)
TOP_N = 15            # 품목 요약에 보여줄 개수


def load(freq):
    """q1_season_<주기>.csv 를 읽는다. 없으면 None."""

    path = DATA_DIR / f"q1_season_{freq}.csv"

    if not path.exists():
        return None, f"{path.name} 없음 — python 09_analyze.py {freq} 를 먼저 돌리세요"

    frame = pd.read_csv(path)

    if "amplitude" not in frame.columns:
        return None, f"{path.name} 에 amplitude 컬럼이 없습니다: {list(frame.columns)}"

    frame["amplitude"] = pd.to_numeric(frame["amplitude"], errors="coerce")

    blank = frame["amplitude"].isna().sum()
    frame = frame.dropna(subset=["amplitude"])

    if frame.empty:
        return None, f"{path.name} 에 쓸 수 있는 진폭 값이 없습니다"

    return (frame, blank), None


def bar(count, biggest):
    """개수를 막대 글자로 바꾼다."""

    if biggest <= 0:
        return ""

    return "█" * max(1, round(count / biggest * HIST_WIDTH)) if count else ""


def report(freq, frame, blank, lines):
    """한 주기의 분포를 lines 에 쌓는다 (화면과 파일에 같이 쓰려고)."""

    put = lines.append
    amp = frame["amplitude"]
    total = len(amp)
    label = FREQ_LABEL.get(freq, freq)

    put("")
    put("=" * 68)
    put(f"{label}  계절 진폭 분포   상품 {total:,}개")
    put("=" * 68)

    if blank:
        put(f"  진폭이 비어 제외한 상품 {blank:,}개")

    # --- 요약 ---
    put("")
    put("[요약]")
    put(f"  최소 {amp.min():.3f}   최대 {amp.max():.3f}   "
        f"평균 {amp.mean():.3f}   중앙값 {amp.median():.3f}   "
        f"표준편차 {amp.std():.3f}")

    # --- 분위수 ---
    put("")
    put("[분위수]  '상위 N%' 는 진폭이 큰 쪽에서 센 것")
    put("  " + "-" * 60)
    put(f"  {'백분위':<8}{'진폭':>9}   {'뜻':<30}")
    put("  " + "-" * 60)

    for q, note in [(0.05, "가장 계절색이 옅은 쪽"), (0.10, ""), (0.25, "하위 4분의 1"),
                    (0.50, "한가운데"), (0.75, "상위 25% 선"), (0.90, "상위 10% 선"),
                    (0.95, "상위 5% 선"), (0.99, "가장 계절색이 진한 쪽")]:
        put(f"  {f'{q * 100:.0f}%':<8}{amp.quantile(q):>9.3f}   {note:<30}")

    put("  " + "-" * 60)

    # --- 히스토그램 ---
    put("")
    put(f"[퍼진 모양]  칸 너비 {HIST_STEP}")

    top = float(np.ceil(amp.max() / HIST_STEP) * HIST_STEP)
    edges = np.arange(0, top + HIST_STEP, HIST_STEP)
    counts, _ = np.histogram(amp, bins=edges)
    biggest = counts.max() if len(counts) else 0

    for i, count in enumerate(counts):

        if count == 0 and i > 0 and counts[i:].sum() == 0:
            break

        lo, hi = edges[i], edges[i + 1]
        mark = " <- 지금 판정선" if lo <= CURRENT_LINE < hi else ""

        put(f"  {lo:>4.2f}~{hi:<4.2f} {count:>6,}  {bar(count, biggest)}{mark}")

    # --- 판정선 후보 ---
    put("")
    put("[판정선을 어디에 두면 몇 개가 '뚜렷' 이 되는가]")
    put("  " + "-" * 60)
    put(f"  {'판정선':<10}{'뚜렷 개수':>10}{'비율':>9}   {'설명':<24}")
    put("  " + "-" * 60)

    rows = [(v, "지금 값" if abs(v - CURRENT_LINE) < 1e-9 else "") for v in FIXED_LINES]

    for q, note in [(0.50, "중앙값 (절반이 뚜렷)"), (0.75, "상위 25%"), (0.90, "상위 10%")]:
        rows.append((round(float(amp.quantile(q)), 3), note))

    for value, note in sorted(rows):
        hit = int((amp >= value).sum())
        put(f"  {value:<10.3f}{hit:>10,}{hit / total * 100:>8.0f}%   {note:<24}")

    put("  " + "-" * 60)
    put("  ※ 분위수로 정하면 '이 자료에서 상위 N%' 라고 근거를 댈 수 있다.")
    put("     고정값으로 정하면 다른 자료와 견주기 좋다. 둘 중 하나를 고르면 된다.")

    # --- 물가 추세가 얼마나 섞였는가 (있을 때만) ---
    if "years" in frame.columns:
        put("")
        put("[참고] 관측 연수별 진폭 중앙값 — 기간이 길수록 물가 추세가 더 섞인다")
        by_years = (frame.groupby("years")["amplitude"]
                    .agg(["size", "median"]).reset_index())

        for _, r in by_years.iterrows():
            put(f"  {int(r['years'])}년치  상품 {int(r['size']):>5,}개   "
                f"진폭 중앙값 {r['median']:.3f}")

    # --- 품목별 ---
    if "item_name" in frame.columns:

        by_item = (frame.groupby("item_name")["amplitude"]
                   .agg(["size", "median"]).reset_index()
                   .sort_values("median", ascending=False))

        put("")
        put(f"[품목별 진폭 중앙값]  품목 {len(by_item):,}개 중 큰 쪽 {TOP_N}개")

        for _, r in by_item.head(TOP_N).iterrows():
            put(f"  {str(r['item_name'])[:16]:<18}{r['median']:>7.3f}   "
                f"상품 {int(r['size']):>4,}개")

        put("")
        put(f"[품목별 진폭 중앙값]  작은 쪽 {TOP_N}개")

        for _, r in by_item.tail(TOP_N).iloc[::-1].iterrows():
            put(f"  {str(r['item_name'])[:16]:<18}{r['median']:>7.3f}   "
                f"상품 {int(r['size']):>4,}개")

    # --- 경계에 걸친 상품 (눈으로 확인할 후보) ---
    name_cols = [c for c in ("item_name", "variety_name") if c in frame.columns]

    if name_cols:
        near = frame.assign(gap=(frame["amplitude"] - CURRENT_LINE).abs()) \
                    .sort_values("gap").head(10)

        put("")
        put(f"[지금 판정선 {CURRENT_LINE} 언저리 상품 10개]")
        put("  대시보드 평년 밴드를 열어 계절 모양이 실제로 보이는지 확인할 후보다.")

        for _, r in near.iterrows():
            name = " / ".join(str(r[c]) for c in name_cols)
            put(f"  {name[:28]:<30}{r['amplitude']:>7.3f}")

    return lines


targets = [a for a in sys.argv[1:] if not a.startswith("-")] or list(FREQ_LABEL)

lines = []
done, skipped = [], []

for freq in targets:

    if freq not in FREQ_LABEL:
        skipped.append((freq, "모르는 주기 (day · week · month 중 하나)"))
        continue

    loaded, why = load(freq)

    if loaded is None:
        skipped.append((freq, why))
        continue

    frame, blank = loaded
    report(freq, frame, blank, lines)
    done.append(freq)

    out = OUT_DIR / f"amplitude_dist_{freq}.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    lines = []

print("=" * 68)
print("계절 진폭 분포")
print("=" * 68)

for freq in done:
    path = OUT_DIR / f"amplitude_dist_{freq}.txt"
    print(path.read_text(encoding="utf-8"))
    print(f"\n  저장: {path}")

for freq, why in skipped:
    print(f"\n  건너뜀  {FREQ_LABEL.get(freq, freq)}  {why}")

if not done:
    raise SystemExit("\n읽을 수 있는 q1_season_<주기>.csv 가 없습니다.")

print("\n" + "-" * 68)
print("정한 값은 09_analyze.py 의 Q1_STRONG_AMPLITUDE 에 넣고 다시 돌리면 됩니다.")
print("reports/amplitude_dist_<주기>.txt 를 그대로 보내 주시면 같이 보겠습니다.")
