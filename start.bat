@echo off
rem Heimerdinger one-click launcher: build frontend (if needed) + start API at http://127.0.0.1:8100
cd /d %~dp0

if not exist .venv\Scripts\python.exe (
  echo [ERROR] .venv not found. Setup first:
  echo   python -m venv .venv
  echo   .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)

if not exist web\dist\index.html (
  echo [INFO] web\dist not found, building frontend...
  where npm >nul 2>nul
  if errorlevel 1 (
    echo [WARN] npm not found in PATH. Build manually:
    echo   cd web ^&^& npm install ^&^& npm run build
  ) else (
    pushd web
    call npm install --no-audit --no-fund
    call npm run build
    popd
  )
)

start "" http://127.0.0.1:8100
.venv\Scripts\python.exe -m uvicorn heimerdinger.api.main:app --host 127.0.0.1 --port 8100
