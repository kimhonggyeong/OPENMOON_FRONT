@echo off
setlocal
cd /d %~dp0

if not exist .venv (
  py -3.11 -m venv .venv 2>nul || python -m venv .venv
)

call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

if not exist .env copy .env.example .env

pushd frontend
call npm install
if errorlevel 1 (
  echo npm install failed. The bundled prebuilt UI will be used.
) else (
  call npm run build
  if errorlevel 1 echo Frontend build failed. The bundled prebuilt UI will be used.
)
popd

python -m backend.scripts.init_db

echo.
echo Setup complete.
echo Edit .env, then run start.bat
pause
