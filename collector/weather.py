r"""관측 날씨 — 기상청 ASOS 일자료(공공데이터포털) → TBL_WEATHER_DAILY. 전국 관측소 전부.

  매일:  uv run python -m collector.weather                         (전 관측소 최근 7일 — 늦게 올라온 값 · 정정 반영)
  백필:  uv run python -m collector.weather --start 2015-01-01 --end 2026-11-18
  일부:  uv run python -m collector.weather --stations 100,261 --days 30

기상청은 '전날까지' 만 준다 — 범위에 오늘이 들어가면 요청 전체가 실패한다. 그래서 끝은 항상 어제(KST)로 자른다.
한 번에 999일까지 받는다 (넘으면 쪽을 넘긴다). 관측소마다 호출하므로 매일 97번 · 11년 백필은 약 500번.

AVAILABLE_AT (그 값을 알 수 있게 된 시각)
  · 처음 들어가는 행: 매일 수집이면 지금, 백필이면 '관측일 다음 날 11:00 KST' (일자료는 다음 날 오전에 나온다)
  · 이미 있는 행을 다시 받으면 값은 고치되 AVAILABLE_AT 은 그대로 둔다 (처음 알게 된 시각이 맞다)
"""

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from collector import ingest, loader  # noqa: E402

URL = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
PAGE = 999
SOURCE = "weather"

# 2026-11-17 기준 응답하는 ASOS 관측소 97곳 (번호 90~299 를 하루치씩 불러 확인). 시도는 이름으로 정했다.
STATIONS = {
    90: ("속초", "강원"), 93: ("북춘천", "강원"), 95: ("철원", "강원"), 98: ("동두천", "경기"),
    99: ("파주", "경기"), 100: ("대관령", "강원"), 101: ("춘천", "강원"), 102: ("백령도", "인천"),
    104: ("북강릉", "강원"), 105: ("강릉", "강원"), 106: ("동해", "강원"), 108: ("서울", "서울"),
    112: ("인천", "인천"), 114: ("원주", "강원"), 115: ("울릉도", "경북"), 119: ("수원", "경기"),
    121: ("영월", "강원"), 127: ("충주", "충북"), 129: ("서산", "충남"), 130: ("울진", "경북"),
    131: ("청주", "충북"), 133: ("대전", "대전"), 135: ("추풍령", "충북"), 136: ("안동", "경북"),
    137: ("상주", "경북"), 138: ("포항", "경북"), 140: ("군산", "전북"), 143: ("대구", "대구"),
    146: ("전주", "전북"), 152: ("울산", "울산"), 155: ("창원", "경남"), 156: ("광주", "광주"),
    159: ("부산", "부산"), 162: ("통영", "경남"), 165: ("목포", "전남"), 168: ("여수", "전남"),
    169: ("흑산도", "전남"), 170: ("완도", "전남"), 172: ("고창", "전북"), 174: ("순천", "전남"),
    177: ("홍성", "충남"), 181: ("서청주", "충북"), 184: ("제주", "제주"), 185: ("고산", "제주"),
    188: ("성산", "제주"), 189: ("서귀포", "제주"), 192: ("진주", "경남"), 201: ("강화", "인천"),
    202: ("양평", "경기"), 203: ("이천", "경기"), 211: ("인제", "강원"), 212: ("홍천", "강원"),
    216: ("태백", "강원"), 217: ("정선군", "강원"), 221: ("제천", "충북"), 226: ("보은", "충북"),
    232: ("천안", "충남"), 235: ("보령", "충남"), 236: ("부여", "충남"), 238: ("금산", "충남"),
    239: ("세종", "세종"), 243: ("부안", "전북"), 244: ("임실", "전북"), 245: ("정읍", "전북"),
    247: ("남원", "전북"), 248: ("장수", "전북"), 251: ("고창군", "전북"), 252: ("영광군", "전남"),
    253: ("김해시", "경남"), 254: ("순창군", "전북"), 255: ("북창원", "경남"), 257: ("양산시", "경남"),
    258: ("보성군", "전남"), 259: ("강진군", "전남"), 260: ("장흥", "전남"), 261: ("해남", "전남"),
    262: ("고흥", "전남"), 263: ("의령군", "경남"), 264: ("함양군", "경남"), 266: ("광양시", "전남"),
    268: ("진도군", "전남"), 271: ("봉화", "경북"), 272: ("영주", "경북"), 273: ("문경", "경북"),
    276: ("청송군", "경북"), 277: ("영덕", "경북"), 278: ("의성", "경북"), 279: ("구미", "경북"),
    281: ("영천", "경북"), 283: ("경주시", "경북"), 284: ("거창", "경남"), 285: ("합천", "경남"),
    288: ("밀양", "경남"), 289: ("산청", "경남"), 294: ("거제", "경남"), 295: ("남해", "경남"),
    296: ("북부산", "부산"),
}

# DB 열 ← 기상청 항목
FIELDS = {
    "AVG_TA": "avgTa", "MIN_TA": "minTa", "MAX_TA": "maxTa", "SUM_RN": "sumRn",
    "AVG_RHM": "avgRhm", "MIN_RHM": "minRhm", "SUM_SS_HR": "sumSsHr", "SUM_GSR": "sumGsr",
    "AVG_WS": "avgWs", "MAX_WS": "maxWs", "DD_MES": "ddMes", "AVG_TS": "avgTs", "MIN_TG": "minTg",
}
ZERO_IF_EMPTY = {"SUM_RN", "DD_MES"}      # 비 · 눈이 없던 날은 빈 값으로 온다 → 0


def parse(items):
    """기상청 item 목록 → DB 행 dict 목록. 날짜가 없는 행은 뺀다."""
    out = []
    for it in items or []:
        try:
            d = date.fromisoformat(str(it.get("tm"))[:10])
            stn = int(it.get("stnId"))
        except (TypeError, ValueError):
            continue
        row = {"OBS_DATE": d, "STN_ID": stn}
        for col, key in FIELDS.items():
            row[col] = ingest.num(it.get(key), 0.0 if col in ZERO_IF_EMPTY else None)
        out.append(row)
    return out


def fetch(stn, start, end, key):
    """관측소 하나의 [start, end] 를 쪽을 넘겨 가며 모두 받는다."""
    items, page = [], 1
    while True:
        body = ingest.get_json(URL, {
            "serviceKey": key, "pageNo": page, "numOfRows": PAGE, "dataType": "JSON",
            "dataCd": "ASOS", "dateCd": "DAY", "startDt": start.strftime("%Y%m%d"),
            "endDt": end.strftime("%Y%m%d"), "stnIds": str(stn)})
        resp = body.get("response") or {}
        head = resp.get("header") or {}
        code = str(head.get("resultCode"))
        if code == "03":                      # NO_DATA
            return items
        if code != "00":
            raise RuntimeError(f"기상청 {code} {head.get('resultMsg')}")
        b = resp.get("body") or {}
        got = (b.get("items") or {}).get("item") or []
        if isinstance(got, dict):
            got = [got]
        items.extend(got)
        if len(items) >= int(b.get("totalCount") or 0) or not got:
            return items
        page += 1


UPSERT = f"""
    INSERT INTO TBL_WEATHER_DAILY (OBS_DATE, STN_ID, {", ".join(FIELDS)}, AVAILABLE_AT)
    VALUES (%(OBS_DATE)s, %(STN_ID)s, {", ".join(f"%({c})s" for c in FIELDS)}, %(AVAILABLE_AT)s)
    ON CONFLICT (OBS_DATE, STN_ID) DO UPDATE SET
        {", ".join(f"{c} = EXCLUDED.{c}" for c in FIELDS)}, FETCHED_AT = now()
"""


def available_at(obs_date, backfill, now):
    if backfill:
        return datetime.combine(obs_date + timedelta(days=1), datetime.min.time()).replace(
            hour=11, tzinfo=config.KST)
    return now


def save(conn, rows, backfill):
    now = datetime.now(config.KST)
    with conn.transaction(), conn.cursor() as cur:
        for r in rows:
            cur.execute(UPSERT, {**r, "AVAILABLE_AT": available_at(r["OBS_DATE"], backfill, now)})
    return len(rows)


def save_stations(conn, ids):
    with conn.transaction(), conn.cursor() as cur:
        for sid in ids:
            name, sido = STATIONS[sid]
            cur.execute("""
                INSERT INTO TBL_WEATHER_STATION (STN_ID, STN_NAME, SIDO) VALUES (%s, %s, %s)
                ON CONFLICT (STN_ID) DO UPDATE SET STN_NAME = EXCLUDED.STN_NAME, SIDO = EXCLUDED.SIDO,
                                                   UPDATED_AT = now()""", (sid, name, sido))


def refresh_station_dates(conn):
    with conn.transaction():
        conn.execute("""
            UPDATE TBL_WEATHER_STATION s SET FIRST_DATE = w.f, LAST_DATE = w.l, UPDATED_AT = now()
            FROM (SELECT STN_ID, MIN(OBS_DATE) f, MAX(OBS_DATE) l FROM TBL_WEATHER_DAILY GROUP BY 1) w
            WHERE w.STN_ID = s.STN_ID""")


def chunks(start, end, size=PAGE):
    out, s = [], start
    while s <= end:
        e = min(s + timedelta(days=size - 1), end)
        out.append((s, e))
        s = e + timedelta(days=1)
    return out


def parse_args(argv):
    p = argparse.ArgumentParser(prog="python -m collector.weather", description="기상청 ASOS 일자료 수집")
    p.add_argument("--days", type=int, default=7, help="최근 며칠 (기본 7, 어제까지)")
    p.add_argument("--start", type=date.fromisoformat, help="백필 시작일 (주면 --days 무시)")
    p.add_argument("--end", type=date.fromisoformat, help="백필 종료일 (기본 어제)")
    p.add_argument("--stations", help="관측소 번호 쉼표 목록 (기본 전부)")
    p.add_argument("--sleep", type=float, default=0.2)
    return p.parse_args(argv)


def main(argv=None):
    a = parse_args(sys.argv[1:] if argv is None else argv)
    key = ingest.require("DATA_GO_KR_KEY")
    yesterday = config.now_kst().date() - timedelta(days=1)
    end = min(a.end or yesterday, yesterday)
    backfill = a.start is not None
    start = a.start or (end - timedelta(days=a.days - 1))
    ids = [int(x) for x in a.stations.split(",")] if a.stations else sorted(STATIONS)
    unknown = [i for i in ids if i not in STATIONS]
    if unknown:
        raise SystemExit(f"모르는 관측소 번호: {unknown}")

    print(f"\n===== {config.now_kst():%Y-%m-%d %H:%M} 날씨 수집 · {start} ~ {end} · 관측소 {len(ids)}곳"
          f"{' (백필)' if backfill else ''} =====")
    conn = loader.connect()
    conn.autocommit = True
    errors = total = 0
    try:
        save_stations(conn, ids)
        for n, sid in enumerate(ids, 1):
            for s, e in chunks(start, end):
                target = f"{sid} {s}~{e}"
                try:
                    rows = parse(fetch(sid, s, e, key))
                    total += save(conn, rows, backfill)
                    ingest.log(conn, SOURCE, target, "OK" if rows else "NO_DATA", len(rows), len(rows))
                except Exception as ex:
                    errors += 1
                    ingest.log(conn, SOURCE, target, "ERROR", message=f"{type(ex).__name__}: {ex}")
                    print(f"  {STATIONS[sid][0]}({sid}) {s}~{e} 오류 — {ingest.hide(str(ex))}")
                time.sleep(a.sleep)
            if n % 20 == 0 or n == len(ids):
                print(f"  [{n}/{len(ids)}] 누적 {total:,}행 · 오류 {errors}")
        refresh_station_dates(conn)
    finally:
        conn.close()
    print(f"끝: {total:,}행 반영 · 오류 {errors}")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
