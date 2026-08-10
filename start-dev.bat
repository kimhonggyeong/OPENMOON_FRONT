@echo off
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  pause
  exit /b 1
)
start "OPENMOON Backend" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000"
start "OPENMOON Frontend" cmd /k "cd frontend && npm run dev"
start http://127.0.0.1:5173
