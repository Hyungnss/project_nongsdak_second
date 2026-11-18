r"""최근 며칠치 수집이 실제로 됐는지 확인하고, 빠진 날이 있으면 슬랙으로 경고한다 (8단계).

  실행:  uv run python -m collector.check [--days N]
         uv run python -m collector.check YYYY-MM-DD
  기본값: 최근 7일

왜 필요한가
  upsert 의 완료 알림은 'upsert 가 돌았을 때만' 온다. PC 가 꺼져 있거나 작업 스케줄러가
  걸러 먹거나 스크립트가 시작도 못 하고 죽으면, 수집이 안 됐는데도 슬랙은 조용하다.
  침묵을 성공으로 착각하게 되는 것이다. 이 스크립트가 그 침묵을 대신 깬다.

왜 '오늘' 이 아니라 '최근 N 일' 인가
  예전에는 date.today() 하루만 봤는데, 그러면 정작 밤새 PC 가 꺼져 있던 날을
  놓친다. 점검이 밀려서 다음 날 아침에 뒤늦게 실행되면 today 는 이미
  '다음 날' 로 바뀌어 있다. 아직 수집 시각이 오지도 않은 날의 기록을 찾으니 당연히
  없고, 그래서 헛경보가 나간다. 정작 빠진 어제는 쳐다보지도 않는다.
  헛경보가 반복되면 진짜 경고도 흘려보게 되므로, 지나간 날들을 훑는 쪽으로 바꿨다.

  범위를 7 일로 잡은 것은 run_fetch.bat 의 --days 7 백필과 맞추기 위해서다.
  그 안의 구멍은 다음 수집이 알아서 메우고, 그보다 오래된 구멍은 영구적이라
  사람이 손을 대야 한다.

오늘을 언제 포함하나
  FETCH_TIME(17:30, run_fetch.bat 의 예약 시각) 을 넘겼을 때만 센다. 수집이 돌았을
  시각이 지나야 '기록이 없으면 이상한' 날이 되기 때문이다. 아침에 뒤늦게 돌 때
  오늘이 빠지는 것도 같은 이유다. run_fetch.bat 의 예약 시각을 옮기면 이 값도
  같이 옮겨야 한다. 어긋나면 갓 끝난 수집을 점검이 건너뛰거나(늦게 잡으면),
  아직 오지 않은 수집을 놓쳤다고 경고한다(이르게 잡으면).

어떻게 판단하나
  upsert 는 하루치를 반영할 때마다 TBL_FETCH_LOG 에 그날의 요약 한 줄
  (CATEGORY_CODE IS NULL) 을 남긴다. 그 요약행을 보고 판단한다.
    · 없음        -> upsert 가 그날 안 돌았다. 경고한다.
    · STATUS=OK   -> 정상. (완료 알림은 upsert 가 이미 보냈으니) 조용히 넘어간다.
    · NO_DATA     -> 주말·공휴일이라 자료가 없는 날. 정상이므로 조용하다.
    · ERROR       -> 실패로 기록됐다. 경고한다.
  DB 에 접속조차 못 하면 그것도 경고한다 (오라클이 죽었을 수 있으므로).

  요약행은 소매·도매마다 하나씩 남는다 (2026-10-15~). 둘 다 따로 본다 —
  도매만 실패해도 '그날은 됐다' 고 넘어가면 도매 탭이 조용히 멈춘다.

언제 도는가
  자체 예약 작업은 없다. run_fetch.bat 이 upsert 를 끝낸 직후 check_fetch.bat 을
  call 로 부른다. 즉 17:30 수집 → 곧바로 점검이다.

  예전에는 19:00 짜리 작업(KAMIS_check_1900) 이 따로 있었다. 두 작업 모두
  -StartWhenAvailable 이라, 밤새 PC 가 꺼져 있다 아침에 켜지면 Windows 가 둘을
  한꺼번에 깨웠다. 밀린 작업은 최대 10 분 랜덤 지연으로 실행되므로 순서가 정해지지
  않는데, 점검이 먼저 이기면 수집이 아직 채우는 중인 구멍을 보고 헛경보를 보냈다.
  한 배치 안에서 순서대로 부르면 점검은 언제나 수집이 남긴 결과만 본다.

  손으로 확인하고 싶으면 아무 때나 직접 돌려도 된다. 그때는 오늘이 아직
  FETCH_TIME 전이라면 점검 대상에서 빠진다.

먼저 07_create_fetch_log.sql 로 TBL_FETCH_LOG 를 만들어 둘 것.
"""

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

# python collector/check.py 로 직접 돌려도 config · collector 를 찾도록 루트를 경로에 넣는다.
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from collector import loader  # noqa: E402  접속은 loader 의 것을 그대로 쓴다 (upsert 와 같은 규칙)
from collector.notify import notify_slack  # noqa: E402

# 기본 점검 범위. run_fetch.bat 의 --days 7 백필과 맞춘다.
DEFAULT_DAYS = 7

# 오늘을 점검 대상에 넣는 기준 시각. run_fetch.bat 의 예약 시각과 같아야 한다.
# 수집이 돌았을 시각이 지나야 '기록이 없으면 이상한' 날이 되기 때문이다.
FETCH_TIME = time(17, 30)


# 점검할 시장. upsert 가 --market all 로 둘 다 받는다.
MARKETS = ["소매", "도매"]

# 한 날짜에 요약행이 여러 번 쌓일 수 있다 (재실행). LOG_NO 오름차순으로 읽어
# 나중 것으로 덮으면 각 날짜의 최신 상태만 남는다.
SUMMARY_SQL = """
SELECT TO_CHAR(SURVEY_DATE, 'YYYY-MM-DD'), COALESCE(MARKET_TYPE, '소매'),
       STATUS, ROWS_FETCHED, ROWS_UPSERTED, MESSAGE
FROM   TBL_FETCH_LOG
WHERE  CATEGORY_CODE IS NULL
  AND  SURVEY_DATE BETWEEN %(d1)s::date AND %(d2)s::date
ORDER  BY SURVEY_DATE, LOG_NO
"""


def parse_args(argv, now):
    """점검할 날짜 목록을 만든다. 날짜를 직접 주면 그 하루만 본다 (테스트용)."""
    if len(argv) > 1 and not argv[1].startswith("--"):
        day = argv[1]
        try:
            date.fromisoformat(day)
        except ValueError:
            raise SystemExit(f"날짜 형식이 잘못됐습니다: {day!r} (YYYY-MM-DD)")
        return [day]

    days = DEFAULT_DAYS
    if "--days" in argv:
        try:
            days = int(argv[argv.index("--days") + 1])
        except (IndexError, ValueError):
            raise SystemExit("--days 뒤에 숫자를 주세요. 예: --days 7")
        if days < 1:
            raise SystemExit("--days 는 1 이상이어야 합니다.")

    today = now.date()
    out = []
    for back in range(days - 1, -1, -1):
        d = today - timedelta(days=back)
        # 오늘은 17:30 수집이 끝났을 시간이 지나야 '없으면 이상한' 날이 된다.
        if d == today and now.time() < FETCH_TIME:
            continue
        out.append(d.isoformat())
    return out


def fetch_summaries(conn, days):
    """(날짜, 시장) -> (STATUS, 받은행, 반영행, 메시지). 기록이 없으면 키가 없다."""
    found = {}
    with conn.cursor() as cur:
        cur.execute(SUMMARY_SQL, {"d1": days[0], "d2": days[-1]})
        for day, market, status, fetched, upserted, message in cur:
            found[(day, market)] = (status, fetched, upserted, message)
    return found


def main():
    now = datetime.now()
    days = parse_args(sys.argv, now)

    print(f"\n===== {now:%Y-%m-%d %H:%M} 수집 점검 =====")
    if not days:
        print(f"점검할 날이 없습니다 (오늘은 {FETCH_TIME:%H:%M} 이후에 봅니다).")
        return
    print(f"대상 {days[0]} ~ {days[-1]} ({len(days)}일)")

    try:
        conn = loader.connect()
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"DB 접속 실패 — {msg}")
        notify_slack(
            f"⚠️ KAMIS 수집 점검 실패 · {days[0]} ~ {days[-1]}\n"
            f"DB 에 접속하지 못해 수집 여부를 확인할 수 없습니다.\n{msg}"
        )
        sys.exit(1)

    try:
        found = fetch_summaries(conn, days)
    finally:
        conn.close()

    missing, failed = [], []
    for day in days:
        for market in MARKETS:
            tag = f"{day} {market}"
            row = found.get((day, market))
            if row is None:
                print(f"  {tag}  기록 없음")
                missing.append(tag)
                continue
            status, fetched, upserted, message = row
            if status == "OK":
                print(f"  {tag}  OK       받은 {fetched or 0:,} · 반영 {upserted or 0:,}")
            elif status == "NO_DATA":
                print(f"  {tag}  자료 없음 (주말·공휴일이면 정상)")
            else:
                print(f"  {tag}  실패 — {message}")
                failed.append((tag, message))

    if not missing and not failed:
        print(f"정상: {len(days)}일 모두 소매·도매 기록이 있습니다.")
        return

    # 빠진 날이 백필 범위(run_fetch.bat --days 7) 안이면 다음 수집이 메운다.
    # 그보다 오래된 구멍은 스스로 사라지지 않으니 따로 짚어 준다.
    lines = [f"⚠️ KAMIS 수집 점검 · {days[0]} ~ {days[-1]}"]
    if missing:
        lines.append(f"기록 없음 ({len(missing)}건): {', '.join(missing)}")
    for day, message in failed:
        lines.append(f"실패 기록 {day}: {message or ''}")
    lines.append(
        "PC 꺼짐 · 스케줄러 누락 · 스크립트 크래시 중 하나입니다. "
        "logs\\fetch.log 를 확인해 주세요."
    )
    print("\n".join(lines[1:]))
    notify_slack("\n".join(lines))
    sys.exit(1)


if __name__ == "__main__":
    main()
