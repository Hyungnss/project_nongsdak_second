@echo off
rem ===========================================================================
rem KAMIS heartbeat check (step 8). Called by run_fetch.bat, right after the
rem fetch. No Task Scheduler entry of its own - see run_fetch.bat for why the
rem separate 19:00 task was dropped. Safe to run by hand any time.
rem
rem   log  : logs\fetch.log     (appended)
rem
rem Verifies the last 7 days actually got collected. For any day with no
rem TBL_FETCH_LOG summary row, or one marked ERROR, it Slack-alerts so a silent
rem miss (PC off, scheduler skip, crash) does not pass unnoticed. Today only
rem counts once CUTOFF_HOUR has passed. Korean notes live in
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
