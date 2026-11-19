@echo off
rem ===========================================================================
rem KAMIS heartbeat check (step 8). Called by run_fetch.bat, right after the
rem fetch. No Task Scheduler entry of its own - see run_fetch.bat for why the
rem separate 19:00 task was dropped. Safe to run by hand any time.
rem
rem   log  : logs\fetch.log     (appended)
rem
rem Verifies the last 7 days actually got collected. For any day with no
rem TBL_FETCH_LOG summary row, or one marked ERROR, it warns (exit 1) so a silent
rem miss (PC off, scheduler skip, crash) does not pass unnoticed. Today only
rem counts once CUTOFF_HOUR has passed. Korean notes live in
rem collector\check.py.
rem
rem ASCII only, on purpose (same reason as run_fetch.bat).
rem ===========================================================================

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

rem %~dp0 = the folder this .bat lives in. A hard-coded path broke when the
rem project moved to a new PC, so follow the file instead.
cd /d "%~dp0"
if not exist logs mkdir logs

.venv\Scripts\python.exe -u -m collector.check >> logs\fetch.log 2>&1

exit /b %ERRORLEVEL%
