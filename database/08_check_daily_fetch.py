"""오늘 수집이 실제로 됐는지 확인하고, 안 됐으면 슬랙으로 경고한다 (8단계).

  실행:  .venv\\Scripts\\python.exe database\\08_check_daily_fetch.py [YYYY-MM-DD]
  기본값: 오늘

왜 필요한가
  06 의 완료 알림은 '06 이 돌았을 때만' 온다. PC 가 꺼져 있거나 작업 스케줄러가
  걸러 먹거나 스크립트가 시작도 못 하고 죽으면, 수집이 안 됐는데도 슬랙은 조용하다.
  침묵을 성공으로 착각하게 되는 것이다. 이 스크립트가 그 침묵을 대신 깬다.

어떻게
  06 은 하루치를 반영할 때마다 TBL_FETCH_LOG 에 그날의 요약 한 줄
  (CATEGORY_CODE IS NULL) 을 남긴다. 그 요약행을 보고 판단한다.
    · 없음        -> 06 이 아예 안 돌았다. 경고한다.
    · STATUS=OK   -> 정상. (완료 알림은 06 이 이미 보냈으니) 조용히 넘어간다.
    · NO_DATA     -> 주말·공휴일이라 자료가 없는 날. 정상이므로 조용하다.
    · ERROR       -> 실패로 기록됐다. 경고한다.
  DB 에 접속조차 못 하면 그것도 경고한다 (오라클이 죽었을 수 있으므로).

언제 도는가
  06 (18:00) 이 끝난 뒤, 예컨대 19:00 에 작업 스케줄러가 부른다.
  -StartWhenAvailable 로 걸어두면 18시에 꺼져 있던 날도 PC 를 켜는 순간
  뒤늦게라도 확인해 준다.

    task : KAMIS_check_1900
    ex)  Register-ScheduledTask -TaskName KAMIS_check_1900 `
           -Trigger (New-ScheduledTaskTrigger -Daily -At 19:00) `
           -Action (New-ScheduledTaskAction -Execute check_fetch.bat) `
           -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable)

먼저 07_create_fetch_log.sql 로 TBL_FETCH_LOG 를 만들어 둘 것.
"""

import importlib.util
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from notify import notify_slack


def _load(name, filename):
    """파일명이 숫자로 시작해 일반 import 가 안 된다. 경로로 직접 읽어들인다."""
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 접속은 02 의 것을 그대로 쓴다 (06 과 같은 규칙).
loader = _load("kamis_loader", "02_insert_daily_price.py")

SUMMARY_SQL = """
SELECT STATUS, ROWS_FETCHED, ROWS_UPSERTED, MESSAGE
FROM   TBL_FETCH_LOG
WHERE  SURVEY_DATE = TO_DATE(:d, 'YYYY-MM-DD')
  AND  CATEGORY_CODE IS NULL
ORDER  BY LOG_NO DESC
"""


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    try:
        date.fromisoformat(day)
    except ValueError:
        raise SystemExit(f"날짜 형식이 잘못됐습니다: {day!r} (YYYY-MM-DD)")

    print(f"\n===== {date.today()} 수집 점검 · 대상 {day} =====")

    try:
        conn = loader.connect()
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"DB 접속 실패 — {msg}")
        notify_slack(
            f"⚠️ 수집 점검 실패 · {day}\n"
            f"DB 에 접속하지 못해 오늘 수집 여부를 확인할 수 없습니다.\n{msg}"
        )
        sys.exit(1)

    try:
        with conn.cursor() as cur:
            cur.execute(SUMMARY_SQL, d=day)
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        print("경고: 오늘 수집 요약 기록이 없습니다.")
        notify_slack(
            f"⚠️ 오늘({day}) 수집 기록이 없습니다.\n"
            "18:00 수집이 실행되지 않았을 수 있습니다 "
            "(PC 꺼짐 · 스케줄러 누락 · 스크립트 크래시). 확인해 주세요."
        )
        sys.exit(1)

    status, fetched, upserted, message = row
    if status == "OK":
        print(f"정상: 오늘 수집 OK · 받은 {fetched or 0:,} · 반영 {upserted or 0:,}")
    elif status == "NO_DATA":
        print("정상: 오늘은 자료 없음 (주말·공휴일이면 정상).")
    else:
        print(f"경고: 오늘 수집이 실패로 기록됨 — {message}")
        notify_slack(
            f"⚠️ 오늘({day}) 수집이 실패로 기록돼 있습니다.\n"
            f"{message or ''}\nlogs\\fetch.log 를 확인해 주세요."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
