@echo off
rem ===========================================================================
rem KAMIS daily fetch (step 7). Called by Task Scheduler at 17:30 every day.
rem
rem   task : KAMIS_fetch_1730   (Register-ScheduledTask, -StartWhenAvailable)
rem   log  : logs\fetch.log     (appended; each run starts with a ===== line)
rem
rem ASCII only, on purpose. cmd reads a .bat with whatever console code page is
rem active (65001 here, 949 under Task Scheduler), so any non-ASCII byte - even
rem inside a rem line - desyncs the parser and the rest of the file breaks.
rem Korean notes live in SETUP.md (step 6) and 06_upsert_daily_price.py.
rem
rem why 17:30  : KAMIS publishes at 17:00; before that only livestock has prices.
rem              30 min of margin. If KAMIS is late the day lands partial, but
rem              tomorrow's --days 7 re-ask picks it up, so it self-heals.
rem why --days 7: a once-a-day run asks for that day only, so a missed run would
rem               leave a permanent hole. Re-asking today back through -6 fills a
rem               week of gaps (covers a longer PC-off stretch) and picks up
rem               KAMIS's after-the-fact revisions. MERGE, so no dupes.
rem markets   : 06 fetches retail (01) and wholesale (02) by default, 12 calls
rem               per day. Raw JSON goes to TBL_API_RAW before parsing.
rem ===========================================================================

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

rem %~dp0 = the folder this .bat lives in. A hard-coded path broke when the
rem project moved to a new PC, so follow the file instead.
cd /d "%~dp0"
if not exist logs mkdir logs

rem -u : unbuffered. Redirected to a file, python block-buffers stdout, so a run
rem      killed partway (2026-09-03 18:00 died on ^C after 8s) loses every line it
rem      had printed and the log shows nothing at all. Unbuffered costs nothing at
rem      this volume and keeps the log honest about how far the run got.
.venv\Scripts\python.exe -u database\06_upsert_daily_price.py --days 7 >> logs\fetch.log 2>&1
set FETCH_RC=%ERRORLEVEL%

rem The heartbeat check used to be its own 19:00 task. Both tasks carry
rem -StartWhenAvailable, so after a PC-off night Windows woke them together in
rem arbitrary order (missed runs get up to a 10 min random delay). When the check
rem won the race it read the gap the fetch was still filling and Slack-warned
rem about nothing. Calling it here makes the order certain: the check only ever
rem sees the state the fetch left behind.
call "%~dp0check_fetch.bat"
set CHECK_RC=%ERRORLEVEL%

rem Surface a failure as the task's "Last Run Result". A broken fetch is the
rem bigger news, so it wins; otherwise the check's verdict stands.
if not "%FETCH_RC%"=="0" exit /b %FETCH_RC%
exit /b %CHECK_RC%
