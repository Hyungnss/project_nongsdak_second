r"""중기예보 보관 — 기상청 중기기온 · 중기육상 예보를 발표마다 쌓는다 (TBL_FCST_*).

  uv run python -m collector.forecast            (최근 24시간 안의 발표 중 아직 안 받은 것 전부)

왜 쌓나
  기상청은 최근 24시간 발표분만 준다. 나중에 '예보를 특성으로 쓰자' 고 정했을 때 과거 시점의 예보가
  없으면 학습을 못 한다 (실제 날씨를 쓰면 미래 정보가 섞인다). 그래서 쓸지와 상관없이 지금부터 보관한다.

  · 발표는 하루 두 번(06:00 · 18:00 KST). 발표 30분 뒤부터 받는다.
  · 원문(TBL_FCST_RAW)과 정리본(TBL_FCST_MID_TA · TBL_FCST_MID_LAND)을 같이 넣는다.
  · 이미 받은 (발표, 종류, 구역) 은 건너뛴다 — 스케줄러가 몇 번을 돌려도 같다.
  · 구역 코드는 2026-11-19 에 하나씩 불러 응답을 확인한 것만 쓴다 (활용가이드 별첨 목록은 페이지에 없다).
"""

import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from collector import ingest, loader  # noqa: E402

BASE = "http://apis.data.go.kr/1360000/MidFcstInfoService"
SOURCE = "forecast"
READY_AFTER = timedelta(minutes=30)

LAND = {   # 중기육상 — 광역 권역
    "11B00000": "서울·인천·경기", "11D10000": "강원영서", "11D20000": "강원영동",
    "11C20000": "대전·세종·충남", "11C10000": "충북", "11F20000": "광주·전남", "11F10000": "전북",
    "11H10000": "대구·경북", "11H20000": "부산·울산·경남", "11G00000": "제주",
}
TA = {     # 중기기온 — 도시
    "11B10101": "서울", "11B20201": "인천", "11B20601": "수원", "11B20305": "파주",
    "11D10301": "춘천", "11D10401": "원주", "11D20501": "강릉", "11D20201": "대관령",
    "11C20401": "대전", "11C20101": "서산", "11C20404": "세종", "11C10301": "청주", "11C10101": "충주",
    "11F20501": "광주", "21F20801": "목포", "11F20401": "여수", "11F20601": "순천", "21F20201": "해남",
    "11F10201": "전주", "21F10501": "군산", "11H10701": "대구", "11H10501": "안동", "11H10201": "포항",
    "11H10301": "의성", "11H20201": "부산", "11H20101": "울산", "11H20301": "창원", "11H20701": "진주",
    "11G00201": "제주", "11G00401": "서귀포", "11E00101": "울릉도",
}
OPS = {"ta": ("getMidTa", TA), "land": ("getMidLandFcst", LAND)}


def issuances(now):
    """지금 받을 수 있는 발표 시각들 (최근 24시간 · 발표 30분 뒤부터). 오래된 것부터."""
    out = []
    for back in range(0, 2):
        day = (now - timedelta(days=back)).date()
        for hh in (6, 18):
            t = datetime(day.year, day.month, day.day, hh, tzinfo=config.KST)
            if t + READY_AFTER <= now and now - t < timedelta(hours=24):
                out.append(t)
    return sorted(out)


def parse_ta(item, tm_fc):
    """{'taMin4': 1, 'taMax4': 10, ...} → [(대상일, 최저, 최고)]."""
    days = sorted({int(m.group(2)) for k in item if (m := re.fullmatch(r"ta(Min|Max)(\d+)", k))})
    out = []
    for d in days:
        lo, hi = ingest.num(item.get(f"taMin{d}")), ingest.num(item.get(f"taMax{d}"))
        if lo is None and hi is None:
            continue
        out.append((tm_fc.date() + timedelta(days=d), lo, hi))
    return out


def parse_land(item, tm_fc):
    """rnSt4Am/Pm · wf4Am/Pm ... rnSt8 · wf8 (8일 이후는 하루 값) → [(대상일, 강수확률 오전, 오후, 하늘 오전, 오후)]."""
    days = sorted({int(m.group(1)) for k in item if (m := re.fullmatch(r"rnSt(\d+)(Am|Pm)?", k))})
    out = []
    for d in days:
        am = item.get(f"rnSt{d}Am", item.get(f"rnSt{d}"))
        pm = item.get(f"rnSt{d}Pm", item.get(f"rnSt{d}"))
        wam = item.get(f"wf{d}Am", item.get(f"wf{d}"))
        wpm = item.get(f"wf{d}Pm", item.get(f"wf{d}"))
        r_am, r_pm = ingest.num(am), ingest.num(pm)
        out.append((tm_fc.date() + timedelta(days=d),
                    int(r_am) if r_am is not None else None, int(r_pm) if r_pm is not None else None,
                    (wam or None), (wpm or None)))
    return out


def fetch(op, reg, tm_fc, key):
    body = ingest.get_json(f"{BASE}/{op}", {
        "serviceKey": key, "pageNo": 1, "numOfRows": 10, "dataType": "JSON",
        "regId": reg, "tmFc": tm_fc.strftime("%Y%m%d%H%M")}, timeout=30)
    resp = body.get("response") or {}
    head = resp.get("header") or {}
    code = str(head.get("resultCode"))
    if code == "03":
        return None, body
    if code != "00":
        raise RuntimeError(f"기상청 {code} {head.get('resultMsg')}")
    items = ((resp.get("body") or {}).get("items") or {}).get("item") or []
    if isinstance(items, dict):
        items = [items]
    return (items[0] if items else None), body


def have(conn, tm_fc):
    rows = conn.execute("SELECT KIND, REG_ID FROM TBL_FCST_RAW WHERE TM_FC = %s", (tm_fc,)).fetchall()
    return set(rows)


def save(conn, kind, reg, tm_fc, item, body):
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("""INSERT INTO TBL_FCST_RAW (TM_FC, KIND, REG_ID, BODY) VALUES (%s, %s, %s, %s)
                       ON CONFLICT DO NOTHING""", (tm_fc, kind, reg, json.dumps(body, ensure_ascii=False)))
        n = 0
        if kind == "ta":
            for d, lo, hi in parse_ta(item, tm_fc):
                cur.execute("""INSERT INTO TBL_FCST_MID_TA (TM_FC, REG_ID, TARGET_DATE, TA_MIN, TA_MAX)
                               VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""", (tm_fc, reg, d, lo, hi))
                n += 1
        else:
            for d, ram, rpm, wam, wpm in parse_land(item, tm_fc):
                cur.execute("""INSERT INTO TBL_FCST_MID_LAND (TM_FC, REG_ID, TARGET_DATE, RN_ST_AM, RN_ST_PM, WF_AM, WF_PM)
                               VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                            (tm_fc, reg, d, ram, rpm, wam, wpm))
                n += 1
    return n


def main(argv=None):
    key = ingest.require("DATA_GO_KR_KEY")
    now = datetime.now(config.KST)
    todo = issuances(now)
    print(f"\n===== {config.now_kst():%Y-%m-%d %H:%M} 예보 보관 · 받을 수 있는 발표 "
          f"{', '.join(t.strftime('%m-%d %H시') for t in todo) or '없음'} =====")
    conn = loader.connect()
    conn.autocommit = True
    errors = 0
    try:
        for tm_fc in todo:
            done = have(conn, tm_fc)
            got = rows = 0
            for kind, (op, regs) in OPS.items():
                for reg in regs:
                    if (kind, reg) in done:
                        continue
                    try:
                        item, body = fetch(op, reg, tm_fc, key)
                        if item is None:
                            continue
                        rows += save(conn, kind, reg, tm_fc, item, body)
                        got += 1
                    except Exception as ex:
                        errors += 1
                        print(f"  {tm_fc:%m-%d %H시} {kind} {reg} 오류 — {ingest.hide(str(ex))}")
                    time.sleep(0.15)
            target = f"{tm_fc:%Y%m%d%H%M}"
            if got or errors:
                ingest.log(conn, SOURCE, target, "OK" if got else "ERROR", got, rows,
                           None if not errors else f"오류 {errors}건")
            print(f"  {tm_fc:%m-%d %H시} 발표 · 새로 받은 구역 {got}개 · 정리본 {rows}행"
                  f" (이미 있던 {len(done)}개 건너뜀)")
    finally:
        conn.close()
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
