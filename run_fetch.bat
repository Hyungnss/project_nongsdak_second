@echo off
rem ===========================================================================
rem KAMIS daily fetch (step 7). Called by Task Scheduler at 18:00 every day.
rem
rem   task : KAMIS_fetch_1800   (Register-ScheduledTask, -StartWhenAvailable)
rem   log  : logs\fetch.log     (appended; each run starts with a ===== line)
rem
rem ASCII only, on purpose. cmd reads a .bat with whatever console code page is
rem active (65001 here, 949 under Task Scheduler), so any non-ASCII byte - even
rem inside a rem line - desyncs the parser and the rest of the file breaks.
rem Korean notes live in REALTIME_MIGRATION.md and 06_upsert_daily_price.py.
rem
rem why 18:00  : KAMIS publishes at 17:00; before that only livestock has prices
rem why --days 7: a once-a-day run asks for that day only, so a missed run would
rem               leave a permanent hole. Re-asking today back through -6 fills a
rem               week of gaps (covers a longer PC-off stretch) and picks up
rem               KAMIS's after-the-fact revisions. MERGE, so no dupes.
rem ===========================================================================

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "C:\Users\euclid_edu\Desktop\Hyun\project_grocery_price_insights_service"
if not exist logs mkdir logs

rem -u : unbuffered. Redirected to a file, python block-buffers stdout, so a run
rem      killed partway (2026-09-03 18:00 died on ^C after 8s) loses every line it
rem      had printed and the log shows nothing at all. Unbuffered costs nothing at
rem      this volume and keeps the log honest about how far the run got.
.venv\Scripts\python.exe -u database\06_upsert_daily_price.py --days 7 >> logs\fetch.log 2>&1

rem Surface a failed load as the task's "Last Run Result".
exit /b %ERRORLEVEL%
