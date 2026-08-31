@echo off
setlocal
cd /d %~dp0

call .venv\Scripts\activate
if errorlevel 1 exit /b 1

pushd frontend
call npm run build
if errorlevel 1 (
    popd
    exit /b 1
)
popd

pyinstaller OPENMOON_AI_DATA_FREE.spec --noconfirm --clean ^
  --distpath exe_release_20260829_v7 ^
  --workpath exe_build_temp_20260829_v7
if errorlevel 1 exit /b 1

set RELEASE_DIR=exe_release_20260829_v7\OPENMOON_AI_LAN
mkdir "%RELEASE_DIR%\backend\data\attachments" 2>nul
mkdir "%RELEASE_DIR%\backend\data\generated_quotes" 2>nul
mkdir "%RELEASE_DIR%\backend\data\quotation_files" 2>nul
mkdir "%RELEASE_DIR%\backend\data\raw_mails" 2>nul
mkdir "%RELEASE_DIR%\backend\data\source" 2>nul
mkdir "%RELEASE_DIR%\backend\data\templates" 2>nul

copy /y .env.example "%RELEASE_DIR%\.env.example" >nul
copy /y DATA_FREE_RELEASE_README.txt "%RELEASE_DIR%\사용방법.txt" >nul

echo.
echo Build complete: %RELEASE_DIR%
exit /b 0
