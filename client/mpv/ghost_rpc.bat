@echo off
REM ==========================================
REM  GHOST ENGINE - RPC LAUNCHER
REM ==========================================
REM  Optional. mpv starts the agent itself when it opens, so Rich Presence
REM  already works without this file. Double-click it only to watch the agent
REM  work or to try the overrides below — if mpv already has its own copy
REM  running, this one reports the lock and closes. With no mpv open at all it
REM  waits 30 seconds for one and then leaves.
REM
REM  Put this next to mpv.exe and it needs no configuration: the bridge file
REM  is found beside it.

setlocal
cd /d "%~dp0"

REM Uncomment and edit only if you need to override the defaults.
REM set GHOST_RPC_PIPE=0          & REM which Discord client, when several run
REM set GHOST_RPC_ACTIVITY=watching  & REM force one activity kind
REM set GHOST_RPC_CLIENT_ID=      & REM your own Discord application

where py >nul 2>&1
if errorlevel 1 (
    echo Python launcher "py" not found. Install Python from python.org,
    echo ticking "Add Python to PATH", then run this again.
    pause
    exit /b 1
)

py -c "import pypresence" >nul 2>&1
if errorlevel 1 (
    echo Installing pypresence...
    py -m pip install --quiet -r requirements.txt || (
        echo Install failed. Run:  py -m pip install pypresence
        pause
        exit /b 1
    )
)

py ghost_rpc.py
pause
endlocal
