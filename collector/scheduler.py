"""매일 정해진 시각(한국 시각)에 수집 작업들을 돌린다. 컨테이너용.

  실행:  uv run python -m collector.scheduler                 (docker compose 의 collector 서비스가 이걸 띄운다)
         uv run python -m collector.scheduler --once          (가격 수집 → 점검만 지금 한 번 하고 끝)
         uv run python -m collector.scheduler --once weather  (그 작업만 지금 한 번)

작업 (JOBS)
  forecast_am  06:40  python -m collector.forecast      중기예보 보관 (06시 발표분)
  weather      11:30  python -m collector.weather       관측 날씨 — 전 관측소 최근 7일
  cpi          11:40  python -m collector.cpi           소비자물가 — 최근 6개월 (새 달이 나왔는지)
  price        17:30  python -m collector.upsert --days 7 → python -m collector.check → python -m collector.predict
                      (예측은 그날 정정된 가격까지 반영하려고 수집 · 점검 뒤에 돈다)
  forecast_pm  18:40  python -m collector.forecast      중기예보 보관 (18시 발표분)

  이 PC(Windows)에서는 가격 수집을 작업 스케줄러 + run_fetch.bat 이 한다. 서버 컨테이너에는 작업 스케줄러가
  없어서 이 파일이 그 자리를 맡는다. 각 작업은 별도 프로세스로 돌린다 — 죽어도 스케줄러는 산다.

늦게 켜졌을 때 (작업 스케줄러의 -StartWhenAvailable 과 같은 동작)
  오늘 그 작업 시각이 지났는데 그 뒤의 기록이 없으면 바로 한 번 돈다. 가격은 TBL_FETCH_LOG,
  나머지는 TBL_INGEST_LOG 를 본다. 서버를 재시작하거나 배포한 직후에도 그날 작업이 빠지지 않는다.
  예보는 최근 24시간 발표분만 받을 수 있어서 특히 중요하다.

시각은 전부 한국 시각으로 계산한다 (config.now_kst). 서버 · 컨테이너가 UTC 여도 17:30 은 17:30 이다.
설정 (환경변수, 없으면 기본값)
  FETCH_AT    가격 수집 시각 HH:MM   (기본 17:30 — KAMIS 공표 17:00 + 여유 30분)
  FETCH_DAYS  가격을 다시 받을 일수   (기본 7)
"""

import subprocess
import sys
import time as _time
from dataclasses import dataclass, field
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


@dataclass
class Job:
    name: str
    at: time
    commands: list = field(default_factory=list)   # 차례로 돌릴 [모듈, 인자...] 목록
    source: str | None = None                       # TBL_INGEST_LOG.SOURCE (None 이면 가격 — TBL_FETCH_LOG)


JOBS = [
    Job("forecast_am", time(6, 40), [["collector.forecast"]], "forecast"),
    Job("weather", time(11, 30), [["collector.weather", "--days", "7"]], "weather"),
    Job("cpi", time(11, 40), [["collector.cpi"]], "cpi"),
    Job("price", FETCH_AT, [["collector.upsert", "--days", str(FETCH_DAYS)], ["collector.check"],
                            ["collector.predict"]]),
    Job("forecast_pm", time(18, 40), [["collector.forecast"]], "forecast"),
]


def next_run(now, ran_today, at=FETCH_AT):
    """다음에 돌 시각. now 는 한국 시각(시간대 없는 datetime).

    · 오늘 작업 시각 전이면           -> 오늘 그 시각
    · 지났는데 오늘 아직 안 돌았으면   -> 지금 (따라잡기)
    · 지났고 이미 돌았으면             -> 내일 그 시각
    """
    today_at = datetime.combine(now.date(), at)
    if now < today_at:
        return today_at
    if not ran_today:
        return now
    return today_at + timedelta(days=1)


def ran_today(now, job=None):
    """오늘 그 작업 시각 이후의 기록이 있는지. DB 를 못 보면 False.

    가격(job 없음 · source 없음)은 TBL_FETCH_LOG 의 시장별 요약행, 나머지는 TBL_INGEST_LOG.
    """
    at = job.at if job else FETCH_AT
    since = datetime.combine(now.date(), at).replace(tzinfo=config.KST)
    try:
        with loader.connect() as conn:
            if job is None or job.source is None:
                sql = "SELECT COUNT(*) FROM TBL_FETCH_LOG WHERE CATEGORY_CODE IS NULL AND FETCHED_AT >= %s"
                row = conn.execute(sql, (since,)).fetchone()
            else:
                sql = "SELECT COUNT(*) FROM TBL_INGEST_LOG WHERE SOURCE = %s AND FETCHED_AT >= %s"
                row = conn.execute(sql, (job.source, since)).fetchone()
        return row[0] > 0
    except Exception as e:
        print(f"  (기록을 확인하지 못함 — 일단 안 돈 것으로 봄: {type(e).__name__}: {e})", flush=True)
        return False


def run_job(job):
    """작업의 명령들을 차례로 돌린다. 첫 명령의 종료 코드를 돌려준다."""
    print(f"\n[scheduler] {config.now_kst():%Y-%m-%d %H:%M:%S} {job.name} 시작", flush=True)
    codes = [subprocess.run([sys.executable, "-u", "-m", *cmd]).returncode for cmd in job.commands]
    print(f"[scheduler] {job.name} 끝 — 종료코드 {codes}", flush=True)
    return codes[0]


def run_once():
    """가격 수집 → 점검. run_fetch.bat 과 같다 (예전 --once 와 같은 동작)."""
    return run_job(next(j for j in JOBS if j.name == "price"))


def plan(now, tried):
    """작업마다 다음 시각. tried: 이 프로세스가 이미 돌려 본 (작업, 날짜)."""
    out = []
    for job in JOBS:
        done = (job.name, now.date()) in tried or (now.time() >= job.at and ran_today(now, job))
        out.append((next_run(now, done, job.at), job))
    return sorted(out, key=lambda x: x[0])


def main():
    args = sys.argv[1:]
    if "--once" in args:
        names = [a for a in args if a != "--once"]
        if not names:
            sys.exit(run_once())
        sys.exit(max(run_job(next(j for j in JOBS if j.name == n)) for n in names))

    print(f"[scheduler] 시작 — {' · '.join(f'{j.name} {j.at:%H:%M}' for j in JOBS)} (한국 시각)"
          f" · 지금 {config.now_kst():%Y-%m-%d %H:%M}", flush=True)
    tried = set()       # 실패해도 같은 날 다시 돌지 않게 (= 외부 API 를 쉬지 않고 부르는 일이 없게)
    while True:
        now = config.now_kst()
        upcoming = plan(now, tried)
        due = [job for at, job in upcoming if at <= now]
        if due:
            for job in due:
                tried.add((job.name, now.date()))
                run_job(job)
            continue
        at, job = upcoming[0]
        wait = (at - now).total_seconds()
        print(f"[scheduler] 다음 {job.name} {at:%Y-%m-%d %H:%M} ({wait / 3600:.1f}시간 뒤)", flush=True)
        while wait > 0:
            _time.sleep(min(wait, MAX_SLEEP))
            wait = (at - config.now_kst()).total_seconds()


if __name__ == "__main__":
    main()
