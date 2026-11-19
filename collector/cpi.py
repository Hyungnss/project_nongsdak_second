r"""소비자물가 — 한국은행 ECOS 901Y010 소비자물가지수(특수분류, 월) → TBL_CPI_MONTHLY.

  매일:  uv run python -m collector.cpi                    (최근 6개월 — 새 달이 나왔는지 확인)
  백필:  uv run python -m collector.cpi --start 201501

왜 901Y010 인가
  901Y009 는 지출 목적별(식료품 · 주류 · 의류 ...) 분류라 '농축수산물' 묶음이 없다.
  901Y010(특수분류)에 농축수산물 · 농산물 · 채소 · 과실 · 축산물 · 수산물 · 신선식품이 있다 (2026-11-19 확인).

AVAILABLE_AT
  · 처음 보는 달: 매일 수집이면 지금(발표 뒤 처음 본 시각), 백필이면 '다음 달 10일 00:00 KST'
    (통계청은 보통 다음 달 첫 주에 발표한다 — 늦게 잡아 미래 정보가 섞이지 않게)
  · 이미 있는 달을 다시 받으면 값만 고치고 AVAILABLE_AT 은 그대로 둔다
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from collector import ingest, loader  # noqa: E402

BASE = "https://ecos.bok.or.kr/api/StatisticSearch"
STAT = "901Y010"
SOURCE = "cpi"
ITEMS = {
    "00": "총지수", "211": "농축수산물", "2111": "농산물", "21111": "곡물", "21112": "채소",
    "21113": "과실", "2112": "축산물", "2113": "수산물", "10": "신선식품", "12": "신선채소",
    "13": "신선과실", "QB": "농산물및석유류제외",
}


def months_back(yyyymm, n):
    y, m = int(yyyymm[:4]), int(yyyymm[4:])
    m -= n
    while m <= 0:
        m += 12
        y -= 1
    return f"{y}{m:02d}"


def backfill_available_at(period):
    """기준월 다음 달 10일 00:00 KST."""
    y, m = int(period[:4]), int(period[4:])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return datetime(y, m, 10, tzinfo=config.KST)


def fetch(item, start, end, key):
    url = f"{BASE}/{key}/json/kr/1/10000/{STAT}/M/{start}/{end}/{item}"
    body = ingest.get_json(url)
    if "StatisticSearch" not in body:
        res = body.get("RESULT") or {}
        if str(res.get("CODE")) == "INFO-200":       # 해당 기간 자료 없음
            return []
        raise RuntimeError(f"ECOS {res.get('CODE')} {res.get('MESSAGE')}")
    return body["StatisticSearch"].get("row") or []


def parse(rows):
    out = []
    for r in rows:
        v = ingest.num(r.get("DATA_VALUE"))
        period = str(r.get("TIME") or "")
        if v is None or len(period) != 6:
            continue
        out.append({"PERIOD": period, "STAT_CODE": STAT, "ITEM_CODE": r.get("ITEM_CODE1"),
                    "ITEM_NAME": r.get("ITEM_NAME1"), "VALUE": v, "UNIT": r.get("UNIT_NAME")})
    return out


UPSERT = """
    INSERT INTO TBL_CPI_MONTHLY (PERIOD, STAT_CODE, ITEM_CODE, ITEM_NAME, VALUE, UNIT, AVAILABLE_AT)
    VALUES (%(PERIOD)s, %(STAT_CODE)s, %(ITEM_CODE)s, %(ITEM_NAME)s, %(VALUE)s, %(UNIT)s, %(AVAILABLE_AT)s)
    ON CONFLICT (PERIOD, STAT_CODE, ITEM_CODE) DO UPDATE SET
        ITEM_NAME = EXCLUDED.ITEM_NAME, VALUE = EXCLUDED.VALUE, UNIT = EXCLUDED.UNIT, FETCHED_AT = now()
"""


def save(conn, rows, backfill):
    now = datetime.now(config.KST)
    with conn.transaction(), conn.cursor() as cur:
        for r in rows:
            cur.execute(UPSERT, {**r, "AVAILABLE_AT": backfill_available_at(r["PERIOD"]) if backfill else now})
    return len(rows)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m collector.cpi", description="ECOS 소비자물가 수집")
    p.add_argument("--start", help="백필 시작월 YYYYMM (주면 백필)")
    a = p.parse_args(sys.argv[1:] if argv is None else argv)
    key = ingest.require("ECOS_KEY")
    end = config.now_kst().strftime("%Y%m")
    backfill = a.start is not None
    start = a.start or months_back(end, 6)

    print(f"\n===== {config.now_kst():%Y-%m-%d %H:%M} 물가 수집 · {STAT} {start} ~ {end}"
          f"{' (백필)' if backfill else ''} =====")
    conn = loader.connect()
    conn.autocommit = True
    errors = 0
    try:
        for code, name in ITEMS.items():
            target = f"{STAT} {code} {start}~{end}"
            try:
                rows = parse(fetch(code, start, end, key))
                n = save(conn, rows, backfill)
                ingest.log(conn, SOURCE, target, "OK" if rows else "NO_DATA", len(rows), n)
                last = max((r["PERIOD"] for r in rows), default="-")
                print(f"  {code:<6} {name:<10} {len(rows):>4}개월 · 최신 {last}")
            except Exception as ex:
                errors += 1
                ingest.log(conn, SOURCE, target, "ERROR", message=f"{type(ex).__name__}: {ex}")
                print(f"  {code:<6} {name:<10} 오류 — {ingest.hide(str(ex))}")
    finally:
        conn.close()
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
