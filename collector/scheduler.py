"""매일 정해진 시각(기본 17:30, 한국 시각)에 수집 → 점검을 돌린다. 컨테이너용.

  실행:  uv run python -m collector.scheduler          (docker compose 의 collector 서비스가 이걸 띄운다)
         uv run python -m collector.scheduler --once   (지금 한 번만 수집 → 점검하고 끝)

이 PC(Windows)에서는 작업 스케줄러 + run_fetch.bat 이 같은 일을 한다. 서버 컨테이너에는
작업 스케줄러가 없어서 이 파일이 그 자리를 맡는다. 하는 일은 run_fetch.bat 과 똑같다.

  1. python -m collector.upsert --days 7   (지난 7일을 다시 받아 빈 날 · 사후 보정을 메운다)
  2. python -m collector.check             (빠진 날이 있으면 슬랙 경고)

  각 단계는 별도 프로세스로 돌린다. 수집이 죽어도(예외 · sys.exit) 스케줄러는 살아서 다음 날을 기다린다.

늦게 켜졌을 때 (작업 스케줄러의 -StartWhenAvailable 과 같은 동작)
  오늘 수집 시각이 이미 지났는데 그 뒤에 수집한 기록(TBL_FETCH_LOG)이 없으면 바로 한 번 돈다.
  서버를 재시작하거나 배포한 직후에도 그날 수집이 빠지지 않게 하려는 것이다.

시각은 전부 한국 시각으로 계산한다 (config.now_kst). 서버 · 컨테이너가 UTC 여도 17:30 은 17:30 이다.
설정 (환경변수, 없으면 기본값)
  FETCH_AT    수집 시각 HH:MM          (기본 17:30 — KAMIS 공표 17:00 + 여유 30분)
  FETCH_DAYS  다시 받을 일수            (기본 7)
"""

import subprocess
import sys
import time as _time
from datetime import datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from collector import loader  # noqa: E402


def _parse_hhmm(s):
    h, m = s.split(":")
    return time(int(h), int(m))


FETCH_AT = _parse_hhmm(config.get("FETCH_AT", "17:30"))
FETCH_DAYS = int(config.get("FETCH_DAYS", "7"))

# 한 번에 오래 자지 않는다. PC 절전 · 시계 보정이 있어도 몇 분 안에 다시 계산하게.
MAX_SLEEP = 300


def next_run(now, ran_today):
    """다음에 돌 시각. now 는 한국 시각(시간대 없는 datetime).

    · 오늘 수집 시각 전이면           -> 오늘 수집 시각
    · 지났는데 오늘 아직 안 돌았으면   -> 지금 (따라잡기)
    · 지났고 이미 돌았으면             -> 내일 수집 시각
    """
    today_at = datetime.combine(now.date(), FETCH_AT)
    if now < today_at:
        return today_at
    if not ran_today:
        return now
    return today_at + timedelta(days=1)


def ran_today(now):
    """오늘 수집 시각 이후에 수집한 기록이 있는지 (시장별 요약행 기준). DB 를 못 보면 False."""
    since = datetime.combine(now.date(), FETCH_AT).replace(tzinfo=config.KST)
    try:
        with loader.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM TBL_FETCH_LOG WHERE CATEGORY_CODE IS NULL AND FETCHED_AT >= %s",
                (since,),
            ).fetchone()
        return row[0] > 0
    except Exception as e:
        print(f"  (수집 기록을 확인하지 못함 — 일단 안 돈 것으로 봄: {type(e).__name__}: {e})", flush=True)
        return False


def run_once():
    """수집 → 점검. run_fetch.bat 과 같다. 수집의 종료 코드를 돌려준다."""
    print(f"\n[scheduler] {config.now_kst():%Y-%m-%d %H:%M:%S} 수집 시작 (--days {FETCH_DAYS})", flush=True)
    fetch = subprocess.run([sys.executable, "-u", "-m", "collector.upsert", "--days", str(FETCH_DAYS)])
    check = subprocess.run([sys.executable, "-u", "-m", "collector.check"])
    print(f"[scheduler] 끝 — 수집 종료코드 {fetch.returncode} · 점검 종료코드 {check.returncode}", flush=True)
    return fetch.returncode


def main():
    if "--once" in sys.argv[1:]:
        sys.exit(run_once())

    print(f"[scheduler] 시작 — 매일 {FETCH_AT:%H:%M}(한국 시각)에 수집 · 지금 {config.now_kst():%Y-%m-%d %H:%M}",
          flush=True)
    tried = set()       # 이 프로세스가 이미 돌려 본 날짜. 실패해도 그날 다시 돌지 않는다
    while True:
        now = config.now_kst()
        # 기록을 보는 건 수집 시각이 지났을 때만. 수집이 실패해 기록이 안 남아도
        # 같은 날 계속 다시 도는 일(= KAMIS 를 쉬지 않고 부르는 일)이 없게 tried 로 막는다.
        done = now.date() in tried or (now.time() >= FETCH_AT and ran_today(now))
        at = next_run(now, done)
        wait = (at - now).total_seconds()
        if wait <= 0:
            tried.add(now.date())
            run_once()
            continue
        print(f"[scheduler] 다음 수집 {at:%Y-%m-%d %H:%M} ({wait / 3600:.1f}시간 뒤)", flush=True)
        while wait > 0:
            _time.sleep(min(wait, MAX_SLEEP))
            wait = (at - config.now_kst()).total_seconds()


if __name__ == "__main__":
    main()
