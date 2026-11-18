"""KAMIS OpenAPI 로 하루치 소매·도매 시세를 받아 CSV 와 같은 모양으로 만든다.

  응답 확인:  .venv\\Scripts\\python.exe database\\05_fetch_kamis.py --probe [YYYY-MM-DD]
  하루치 수집: .venv\\Scripts\\python.exe database\\05_fetch_kamis.py [YYYY-MM-DD]
  기본 날짜:  오늘   (CSV 파일로 떨구는 건 소매만 한다 — 과거 CSV 와 대조하는 용도라서)

--probe 는 부류 하나(채소류)만 불러 응답 생김새를 보여준다. 코드를 믿기 전에
실제 응답을 눈으로 확인하는 단계다.

기본 실행은 6개 부류를 순회해 raws/kamis_api_YYYY-MM-DD.csv 로 떨군다.
**이 스크립트는 DB 를 건드리지 않는다.** 적재는 06 이 한다.

만드는 DataFrame 은 기존 CSV 와 같은 17컬럼이다. 그래야
02_insert_daily_price.py 의 build_rows() 를 그대로 재사용할 수 있고,
변환 규칙(등급 '-' -> '없음', 가격 '-' -> NULL)이 한 곳에만 남는다.
"""

import hashlib
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
import config  # noqa: E402

BASE_URL = "http://www.kamis.or.kr/service/price/xml.do"

# 부류코드 -> 부류명. 01_create_kamis_table.sql 의 CATEGORY_CODE 주석과 같은 값이다.
CATEGORIES = {
    "100": "식량작물", "200": "채소류", "300": "특용작물",
    "400": "과실류", "500": "축산물", "600": "수산물",
}
LIVESTOCK = "500"

# p_product_cls_code -> TBL_DAILY_PRICE.MARKET_TYPE
RETAIL, WHOLESALE = "01", "02"
MARKETS = {RETAIL: "소매", WHOLESALE: "도매"}

# CSV 가격 컬럼 -> API 필드
PRICE_MAP = [
    ("당일가격", "dpr1"), ("1일전가격", "dpr2"), ("1주일전가격", "dpr3"),
    ("2주일전가격", "dpr4"), ("1개월전가격", "dpr5"),
    ("1년전가격", "dpr6"), ("평년가격", "dpr7"),
]

CSV_COLUMNS = [
    "조사일자", "구분", "부류명", "부류코드", "품목코드", "품목명",
    "품종코드", "품종명", "등급", "단위",
] + [c for c, _ in PRICE_MAP]


def build_kind_name(kind_name, unit, cat_code):
    """품종명에 단위를 어떻게 붙일지 결정한다.

    기존 43,480행을 조사한 결과, 품종명 끝에 '(단위)' 가 붙는지가 부류에 따라
    정확히 갈린다 (예외 0건).
      · 100·200·300·400·600  36,172행 -> 100% 붙어 있음  예) 여름(고랭지)(1포기)
      · 500 축산물            7,308행 -> 0% 붙어 있음    예) 안심

    그래서 f"{kind_name}({unit})" 로 일괄 처리하면 축산물 7,308행이 어긋난다.
    이미 '(단위)' 로 끝나면 다시 붙이지 않으므로, API 가 어느 형태로 주든 맞는다.
    """
    name = str(kind_name).strip()
    unit = str(unit).strip()

    if config.KAMIS_KIND_NAME_MODE == "verbatim":
        return name
    if cat_code == LIVESTOCK:
        return name
    if not unit or name.endswith(f"({unit})"):
        return name
    return f"{name}({unit})"


def call_api(cat_code, regday, cls=RETAIL):
    """한 부류의 하루치 원본 응답(JSON) 을 그대로 돌려준다. cls: 01 소매 / 02 도매."""
    cert_key, cert_id = config.require_kamis()
    params = {
        "action": "dailyPriceByCategoryList",
        "p_cert_key": cert_key,
        "p_cert_id": cert_id,
        "p_returntype": "json",
        "p_product_cls_code": cls,        # 01=소매 · 02=도매. 과거 CSV 43,480행은 전부 소매
        "p_item_category_code": cat_code,
        "p_regday": regday,
        "p_convert_kg_yn": "N",           # Y 로 하면 1kg 환산가라 과거분과 자릿수가 어긋난다
        # p_country_code 는 넣지 않는다. 넣으면 그 지역 값이 오는데 기존 데이터는 전국값이다.
    }
    r = requests.get(BASE_URL, params=params, timeout=20)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        # 인증 실패 등은 JSON 이 아니라 XML/HTML 로 오는 경우가 있다
        raise SystemExit(
            f"JSON 이 아닌 응답이 왔습니다 (HTTP {r.status_code}).\n"
            f"  인증키를 확인해 주세요.\n  앞부분: {r.text[:300]}"
        )


def error_code_of(body):
    """error_code 를 꺼낸다.

    문서와 달리 최상위가 아니라 data 안에 들어 있다 (정상은 '000').
    무자료로 data 가 리스트로 오면 최상위에 있을 수 있어 양쪽을 다 본다.
    """
    data = body.get("data")
    if isinstance(data, dict) and "error_code" in data:
        return str(data["error_code"])
    if "error_code" in body:
        return str(body["error_code"])
    return None


def extract_items(body):
    """응답에서 item 목록을 꺼낸다. 모양이 흔들려도 견디게 한다.

    자료가 없는 날은 data 가 리스트로 오고, 1건뿐인 날은 item 이 리스트가 아니라
    객체 하나로 오는 API 가 흔하다. 둘 다 방어한다.
    """
    data = body.get("data")
    if isinstance(data, list):        # 무자료
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return [it for it in items if isinstance(it, dict)]


def pick(it, *names):
    """여러 후보 이름 중 실제로 있는 필드를 꺼낸다.

    실제 응답은 item_code·kind_code 인데 문서에는 itemcode·kindcode 로 적혀 있다.
    어느 쪽이 와도 받도록 둘 다 본다.
    """
    for n in names:
        v = it.get(n)
        if v not in (None, ""):
            return str(v).strip()
    return ""


# day2~day4 는 "1일전 (10/13)" 처럼 실제 날짜를 괄호에 적어 준다. 연도는 없다.
_DAY_LABEL = re.compile(r"\((\d{1,2})/(\d{1,2})\)")


def label_date(label, regday):
    """'1일전 (10/13)' -> '2026-10-13'. 날짜가 없거나 이상하면 None.

    연도가 없으므로 조사일의 연도를 붙이고, 그게 조사일보다 뒤면 작년으로 본다
    (1월 초 조사의 '2주일전 (12/22)' 같은 경우).
    """
    m = _DAY_LABEL.search(str(label or ""))
    if not m:
        return None
    base = date.fromisoformat(regday)
    try:
        d = date(base.year, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None
    if d > base:
        try:
            d = date(base.year - 1, d.month, d.day)
        except ValueError:          # 2/29
            return None
    # 2주일전이 두 달 넘게 멀면 연도 추정이 틀린 것이다
    if base - d > timedelta(days=60):
        return None
    return d.isoformat()


def rows_from(body, cat_code, regday, cls=RETAIL):
    """응답 하나를 CSV 모양 dict 목록으로 바꾼다.

    CSV 17컬럼 외에 '등급코드'·'1일전일자'·'1주일전일자'·'2주일전일자' 를 더 담는다.
    CSV 로 떨굴 때는 CSV_COLUMNS 로 잘려 빠지고, 06 의 MERGE 만 이 값을 쓴다.
    """
    rows = []
    for it in extract_items(body):
        item_code = pick(it, "item_code", "itemcode")
        if not item_code:             # 합계행 같은 빈 항목 방어
            continue
        unit = str(it.get("unit", "")).strip()
        row = {
            "조사일자": regday,                       # 응답에 없다. 요청한 날짜를 채운다.
            "구분": MARKETS[cls],                      # p_product_cls_code
            "부류명": CATEGORIES[cat_code],
            "부류코드": cat_code,
            "품목코드": item_code,
            "품목명": pick(it, "item_name"),
            "품종코드": pick(it, "kind_code", "kindcode"),
            "품종명": build_kind_name(it.get("kind_name", ""), unit, cat_code),
            "등급": str(it.get("rank", "-")).strip() or "-",
            "단위": unit,
        }
        for csv_col, api_col in PRICE_MAP:
            row[csv_col] = str(it.get(api_col, "-")).strip() or "-"
        row["등급코드"] = pick(it, "rank_code") or None
        row["1일전일자"] = label_date(it.get("day2"), regday)
        row["1주일전일자"] = label_date(it.get("day3"), regday)
        row["2주일전일자"] = label_date(it.get("day4"), regday)
        rows.append(row)
    return rows


def fetch_category_status(cat_code, regday, cls=RETAIL):
    """(행 목록, error_code) 를 돌려준다."""
    body = call_api(cat_code, regday, cls)
    return rows_from(body, cat_code, regday, cls), error_code_of(body)


def fetch_category(cat_code, regday):
    """한 부류의 하루치를 CSV 모양 dict 목록으로."""
    rows, _ = fetch_category_status(cat_code, regday)
    return rows


def fetch_day(regday):
    """6개 부류를 순회해 하루치 전체를 DataFrame 으로."""
    all_rows = []
    for code, name in CATEGORIES.items():
        got = fetch_category(code, regday)
        print(f"  {code} {name:<6} {len(got):>4}행")
        all_rows.extend(got)
        time.sleep(0.5)               # 연속 호출 간격
    return pd.DataFrame(all_rows, columns=CSV_COLUMNS)


SECRET_KEYS = {"p_cert_key", "p_cert_id"}


def mask(v):
    """출력에서 인증 정보를 가린다.

    KAMIS 는 응답의 condition 에 요청 파라미터를 그대로 되돌려준다. 거기에
    p_cert_key·p_cert_id 가 들어 있어서, 응답을 그대로 찍으면 인증키가
    터미널과 로그에 남는다.
    """
    if isinstance(v, dict):
        return {k: ("***" if k in SECRET_KEYS else mask(x)) for k, x in v.items()}
    if isinstance(v, list):
        return [mask(x) for x in v]
    return v


def raw_text(body):
    """TBL_API_RAW 에 넣을 원문과 그 해시. 인증키·ID 는 가린다.

    응답의 condition 에 p_cert_key·p_cert_id 가 그대로 돌아온다. 그대로 저장하면
    DB 를 읽을 수 있는 사람 누구나 인증키를 보게 된다.
    키 순서를 고정해(sort_keys) 같은 응답이면 해시도 같게 만든다.
    """
    text = json.dumps(mask(body), ensure_ascii=False, sort_keys=True)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def probe(regday, cat_code="200"):
    """응답 생김새를 눈으로 확인한다 (3단계). 파일도 DB 도 건드리지 않는다."""
    print(f"조사일 {regday} · 부류 {cat_code} {CATEGORIES[cat_code]}\n")
    body = call_api(cat_code, regday)

    print("── 최상위 키 ──")
    for k, v in body.items():
        if k == "data":
            print(f"  data          : {type(v).__name__}")
        else:
            print(f"  {k:<14}: {mask(v)!r}")

    data = body.get("data")
    if isinstance(data, dict):
        print("\n── data 안의 키 ──")
        for k, v in data.items():
            print(f"  {k:<14}: {type(v).__name__}"
                  + (f" (len {len(v)})" if isinstance(v, list) else f" = {v!r}"))

    items = extract_items(body)
    print(f"\n── item {len(items)}건 ──")
    if not items:
        print("  자료 없음. 주말·공휴일이면 정상이다.")
        return

    print("\n첫 항목 원본:")
    print(json.dumps(items[0], ensure_ascii=False, indent=2))

    print("\n── 확인할 다섯 가지 ──")
    print(f"  1. data 타입        : {type(data).__name__}"
          f"  (무자료일 때 list 로 오는지는 휴일에 다시 볼 것)")
    print(f"  2. error_code       : {error_code_of(body)!r}  ('000' 이 정상)")
    print(f"  3. item 타입        : {type((body.get('data') or {}).get('item')).__name__}"
          f"  (1건일 때 dict 로 오는 API 가 흔하다)")
    dpr1 = [str(i.get('dpr1', '')) for i in items]
    print(f"  4. dpr1 예시        : {dpr1[:5]}")
    print(f"     콤마 포함 {sum(',' in v for v in dpr1)}건 · '-' {dpr1.count('-')}건")
    ranks = [str(i.get('rank', '')) for i in items]
    print(f"  5. rank '-'         : {ranks.count('-')}건 / {len(ranks)}건")

    print("\n── 품종명 규칙 확인 (가장 걸리기 쉬운 함정) ──")
    for it in items[:5]:
        raw = str(it.get("kind_name", "")).strip()
        unit = str(it.get("unit", "")).strip()
        made = build_kind_name(raw, unit, cat_code)
        mark = "그대로" if made == raw else "단위 붙임"
        print(f"  API {raw!r} + 단위 {unit!r}  ->  {made!r}  ({mark})")
    print(f"\n  현재 모드: {config.KAMIS_KIND_NAME_MODE}")
    print("  기존 CSV 는 채소류(200)가 '여름(고랭지)(1포기)' 처럼 단위가 붙어 있다.")
    print("  위 결과가 그 모양이면 맞다. 확정은 9단계 대조에서 한다.")


def main():
    args = [a for a in sys.argv[1:] if a != "--probe"]
    day = args[0] if args else date.today().isoformat()

    if "--probe" in sys.argv:
        probe(day)
        return

    print(f"수집 시작 · {day}")
    df = fetch_day(day)
    print(f"\n{day} · 총 {len(df):,}행")
    if df.empty:
        print("자료가 없습니다. 주말·공휴일이면 정상입니다.")
        return

    priced = (df["당일가격"] != "-").sum()
    print(f"당일가격 있는 행 {priced:,} / {len(df):,}"
          f" (결측 {100 * (1 - priced / len(df)):.1f}%)")

    out = BASE_DIR / "raws" / f"kamis_api_{day}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"저장: {out}")
    print("\n원본 CSV 와 같은 모양인지 확인한 뒤 적재한다 (9단계 대조).")


if __name__ == "__main__":
    main()
