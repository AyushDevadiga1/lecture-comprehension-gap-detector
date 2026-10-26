@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  LecGap - starting backend + frontend
echo ============================================================

REM Remove a stale E2E proxy target left by Playwright; otherwise Vite
REM proxies to the dead test backend on port 8123 and nothing loads.
if exist "frontend-react\.e2e\backend.url" (
    del "frontend-react\.e2e\backend.url"
    echo Removed stale frontend-react\.e2e\backend.url
)

REM --- backend ---------------------------------------------------------------
set "PYEXE="
where py >nul 2>&1 && py -3.11 -c "import uvicorn" >nul 2>&1 && set "PYEXE=py -3.11"
if not defined PYEXE (
    python -c "import uvicorn" >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
    echo ERROR: no Python with uvicorn found.
    echo Install deps: conda env create -f environment.yml ^&^& conda activate lecgap
    pause
    exit /b 1
)

echo Starting backend on http://localhost:8000 ...
start "LecGap Backend" cmd /k "%PYEXE% -m uvicorn backend.main:app --port 8000"

REM Wait for backend health (up to ~30s)
set /a tries=0
:wait_backend
curl -s http://localhost:8000/health >nul 2>&1
if %errorlevel%==0 goto backend_ready
set /a tries+=1
if %tries% geq 15 (
    echo WARNING: backend did not respond within 30s; continuing anyway.
    goto backend_ready
)
timeout /t 2 /nobreak >nul
goto wait_backend
:backend_ready
echo Backend is up.

REM --- frontend --------------------------------------------------------------
echo Starting frontend on http://localhost:5173 ...
start "LecGap Frontend" cmd /k "cd /d "%~dp0frontend-react" && npm run dev"

REM Give Vite a moment to boot, then open the browser.
timeout /t 8 /nobreak >nul
start "" "http://localhost:5173"

echo.
echo Both servers are running in separate windows.
echo Close those windows (or press Ctrl+C in each) to stop LecGap.
echo.
pause
