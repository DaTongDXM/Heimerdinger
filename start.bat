@echo off
rem timoo one-click launcher: API + Web UI at http://127.0.0.1:8100
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo [ERROR] .venv not found. Setup first:
  echo   python -m venv .venv
  echo   .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)
start "" http://127.0.0.1:8100
.venv\Scripts\python.exe -m uvicorn timoo.api.main:app --host 127.0.0.1 --port 8100
