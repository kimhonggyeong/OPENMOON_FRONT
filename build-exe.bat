@echo off
cd /d %~dp0
call .venv\Scripts\activate
pushd frontend
call npm run build
popd
pyinstaller OPENMOON_AI.spec --noconfirm
pause
