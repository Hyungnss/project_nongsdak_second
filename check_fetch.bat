@echo off
rem ===========================================================================
rem KAMIS heartbeat check (step 8). Called by Task Scheduler at 19:00 every day.
rem
rem   task : KAMIS_check_1900   (Register-ScheduledTask, -StartWhenAvailable)
rem   log  : logs\fetch.log     (appended)
rem
rem Verifies today's 18:00 fetch actually ran. If TBL_FETCH_LOG has no OK
rem summary row for today, it Slack-alerts so a silent miss (PC off, scheduler
rem skip, crash) does not pass unnoticed. Korean notes live in
rem database\08_check_daily_fetch.py.
rem
rem ASCII only, on purpose (same reason as run_fetch.bat).
rem ===========================================================================

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "C:\Users\euclid_edu\Desktop\Hyun\project_grocery_price_insights_service"
if not exist logs mkdir logs

.venv\Scripts\python.exe -u database\08_check_daily_fetch.py >> logs\fetch.log 2>&1

exit /b %ERRORLEVEL%
