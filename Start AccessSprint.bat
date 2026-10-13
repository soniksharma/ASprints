@echo off
setlocal
cd /d "%~dp0"

where node >nul 2>nul
if errorlevel 1 (
  echo Node.js was not found. Install Node.js 20 or newer, then run npm ci and npx playwright install chromium.
  pause
  exit /b 1
)
if not exist "node_modules\playwright\package.json" (
  echo AccessSprint dependencies are missing. Run npm ci, then npx playwright install chromium.
  pause
  exit /b 1
)

where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3.11 or newer was not found. Install Python and enable the py launcher.
    pause
    exit /b 1
  )
  start "AccessSprint local server" cmd /k python main.py
) else (
  start "AccessSprint local server" cmd /k py -3 main.py
)

powershell -NoProfile -Command "$ready = $false; for ($i = 0; $i -lt 30; $i++) { try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/ -TimeoutSec 1 | Out-Null; $ready = $true; break } catch { Start-Sleep -Milliseconds 300 } }; if (-not $ready) { exit 1 }"
if errorlevel 1 (
  echo AccessSprint did not start on port 8000. Check the server window; use python main.py --port 8001 if needed.
  pause
  exit /b 1
)
start "" http://127.0.0.1:8000/
endlocal
