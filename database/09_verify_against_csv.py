"""API 로 받은 하루치가 원본 CSV 의 같은 날짜분과 같은지 대조한다 (9단계).

  실행:  .venv\\Scripts\\python.exe database\\09_verify_against_csv.py [YYYY-MM-DD]
  기본값: 2026-08-18 (원본 CSV 의 마지막 조사일)

**이 대조를 통과해야 과거 CSV 1년치와 신규 API 분을 한 테이블에서 섞어 쓸 수 있다.**
값이 다르면 DB 에 넣지 말고 05_fetch_kamis.py 의 요청 파라미터부터 다시 본다.
과거분과 신규분이 다른 기준으로 섞이면 나중에 어느 쪽이 틀렸는지 가려낼 수 없다.

DB 는 건드리지 않는다. 파일 두 개만 읽는다.
"""

import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
ORIGIN_CSV = BASE_DIR / "raws" / "kamis_price_data_20250901_20260818.csv"

# 자연키 — 01_create_kamis_table.sql 의 UNIQUE 인덱스와 같은 조합
KEY = ["품목코드", "품종코드", "등급"]
PRICE_COLS = ["당일가격", "1일전가격", "1주일전가격", "2주일전가격",
              "1개월전가격", "1년전가격", "평년가격"]
COMPARE_COLS = ["품목명", "품종명", "단위"] + PRICE_COLS


def norm(df):
    """비교 전에 표기를 맞춘다. 값 자체는 바꾸지 않는다."""
    df = df.copy()
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    # 가격의 천단위 콤마는 표기 차이라 비교에서 제외한다
    for c in PRICE_COLS:
        if c in df.columns:
            df[c] = df[c].str.replace(",", "", regex=False)
    return df


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else "2026-08-18"
    api_csv = BASE_DIR / "raws" / f"kamis_api_{day}.csv"
    if not api_csv.exists():
        raise SystemExit(
            f"API 수집분이 없습니다: {api_csv}\n"
            f"  먼저 실행:  .venv\\Scripts\\python.exe database\\05_fetch_kamis.py {day}")

    api = norm(pd.read_csv(api_csv, encoding="utf-8-sig", dtype=str))
    origin_all = pd.read_csv(ORIGIN_CSV, encoding="utf-8-sig", dtype=str)
    origin = norm(origin_all[origin_all["조사일자"].str.strip() == day])

    print(f"조사일 {day}")
    print(f"  원본 CSV : {len(origin):,}행   ({ORIGIN_CSV.name})")
    print(f"  API 수집 : {len(api):,}행   ({api_csv.name})")

    if origin.empty:
        raise SystemExit("원본 CSV 에 이 날짜가 없습니다. 다른 날짜로 대조하세요.")

    ok = True

    # ── 1. 자연키 집합 ────────────────────────────────────────────────────
    ka, ko = set(map(tuple, api[KEY].values)), set(map(tuple, origin[KEY].values))
    only_api, only_origin = ka - ko, ko - ka
    print(f"\n[1] 행 수 · 자연키")
    print(f"    공통 {len(ka & ko):,} · API 에만 {len(only_api)} · 원본에만 {len(only_origin)}")
    # 원본에만 있는 행은 문제다 — 우리가 받아야 할 걸 못 받고 있다는 뜻이다.
    # API 에만 있는 행은 통과시킨다. 조사가 끊긴 품종도 과거값이 있으면 돌려주는데,
    # 당일가격이 NULL 일 뿐 자료로는 맞다.
    for k in list(only_origin)[:5]:
        ok = False
        print(f"      원본에만(문제): 품목 {k[0]} 품종 {k[1]} 등급 {k[2]!r}")
    for k in list(only_api)[:5]:
        print(f"      API 에만(허용): 품목 {k[0]} 품종 {k[1]} 등급 {k[2]!r}")

    # ── 2. 등급 '-' 개수 ──────────────────────────────────────────────────
    na, no = (api["등급"] == "-").sum(), (origin["등급"] == "-").sum()
    print(f"\n[2] 등급 '-' 개수   API {na} · 원본 {no}   {'일치' if na == no else '불일치'}")
    if na != no:
        ok = False

    # ── 3. 이름·단위는 정확히 같아야 한다 ─────────────────────────────────
    # 파라미터를 잘못 넣으면(도매·지역·kg환산) 여기가 먼저 깨진다.
    merged = api.merge(origin, on=KEY, suffixes=("_api", "_org"))
    print(f"\n[3] 공통 {len(merged):,}행 · 이름과 단위 (틀리면 파라미터 문제)")
    for c in ["품목명", "품종명", "단위"]:
        diff = merged[merged[f"{c}_api"] != merged[f"{c}_org"]]
        print(f"    {c:<10} {'일치' if diff.empty else f'불일치 {len(diff)}건'}")
        if not diff.empty:
            ok = False
            for _, r in diff.head(3).iterrows():
                print(f"      {r['품목코드']}/{r['품종코드']}/{r['등급']}  "
                      f"API {r[f'{c}_api']!r}  vs  원본 {r[f'{c}_org']!r}")

    # ── 4. 가격은 개정과 오류를 구분한다 ──────────────────────────────────
    # KAMIS 는 공표 뒤에도 값을 보정하고, 비어 있던 1년전·평년을 나중에 채운다.
    # 그건 정상이므로 통과시키고, 값이 통째로 다른 경우만 잡는다.
    REVISION_TOLERANCE = 0.05        # 5% 이내 차이는 개정으로 본다
    print(f"\n[4] 가격 대조 (개정 허용, 5% 넘는 차이만 문제로 본다)")
    for c in PRICE_COLS:
        a, o = merged[f"{c}_api"], merged[f"{c}_org"]
        diff = merged[a != o]
        if diff.empty:
            print(f"    {c:<10} 일치")
            continue

        filled, revised, broken = [], [], []
        for _, r in diff.iterrows():
            va, vo = r[f"{c}_api"], r[f"{c}_org"]
            tag = f"{r['품목코드']}/{r['품종코드']}/{r['등급']}"
            if vo == "-" and va != "-":
                filled.append((tag, va))            # 비었던 값이 채워짐
                continue
            try:
                fa, fo = float(va), float(vo)
            except ValueError:
                broken.append((tag, va, vo))        # 값 -> '-' 로 사라짐 등
                continue
            gap = abs(fa - fo) / fo if fo else 1.0
            (revised if gap <= REVISION_TOLERANCE else broken).append(
                (tag, va, vo) if gap > REVISION_TOLERANCE else (tag, va, vo, gap))

        parts = []
        if filled:
            parts.append(f"신규 채움 {len(filled)}")
        if revised:
            parts.append(f"개정 {len(revised)}")
        if broken:
            parts.append(f"**문제 {len(broken)}**")
        print(f"    {c:<10} " + " · ".join(parts))
        for t in filled[:2]:
            print(f"      채움 {t[0]}  원본 '-' -> API {t[1]}")
        for t in revised[:2]:
            print(f"      개정 {t[0]}  {t[2]} -> {t[1]}  ({t[3] * 100:.2f}%)")
        for t in broken[:3]:
            ok = False
            print(f"      문제 {t[0]}  API {t[1]!r}  vs  원본 {t[2]!r}")

    # ── 5. 단위 환산 여부 ─────────────────────────────────────────────────
    units = sorted(api["단위"].unique())
    kg_only = units == ["1kg"]
    print(f"\n[5] 단위 {len(units)}종  {units[:8]}{' ...' if len(units) > 8 else ''}")
    if kg_only:
        ok = False
        print("    전부 1kg 이다 - p_convert_kg_yn 이 Y 로 들어갔다. N 으로 고칠 것.")

    print("\n" + ("=" * 60))
    if ok:
        print("통과. API 수집분과 원본 CSV 가 같은 기준이다.")
        print("과거 1년치와 섞어 써도 된다. 다음은 5단계(MERGE 적재).")
    else:
        print("불일치가 있다. DB 에 넣지 말고 05_fetch_kamis.py 의 파라미터부터 다시 볼 것.")
        sys.exit(1)


if __name__ == "__main__":
    main()
