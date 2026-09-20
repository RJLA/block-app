@echo off
REM Build AllowlistGuard.exe  --  run on a Windows 10/11 machine with Python 3.9+
REM Uses the repo-local .venv and creates it on first run; the system Python is
REM only ever used to bootstrap that virtual environment.
setlocal
pushd "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
  echo Creating virtual environment in .venv ...
  where python >nul 2>&1 || (echo Python not found on PATH & popd & exit /b 1)
  python -m venv .venv || (popd & exit /b 1)
  "%VENV_PY%" -m pip install --upgrade pip || (popd & exit /b 1)
  "%VENV_PY%" -m pip install -r requirements-dev.txt || (popd & exit /b 1)
)

"%VENV_PY%" -m PyInstaller --version >nul 2>&1 || (
  echo Installing build dependencies ...
  "%VENV_PY%" -m pip install -r requirements-dev.txt || (popd & exit /b 1)
)

if not exist default_allowlist.json (
  echo {"websites": ["google.com", "wikipedia.org"], "apps": ["chrome", "msedge", "notepad"], "dry_run": true} > default_allowlist.json
)

if not exist assets\mascot.ico (
  echo Missing assets\mascot.ico ^-- run: .venv\Scripts\python.exe tools\make_assets.py
  popd & exit /b 1
)

"%VENV_PY%" -m PyInstaller ^
  --onefile ^
  --windowed ^
  --noconfirm ^
  --name AllowlistGuard ^
  --uac-admin ^
  --icon "assets\mascot.ico" ^
  --add-data "default_allowlist.json;." ^
  --add-data "assets;assets" ^
  allowlist_guard.py || (popd & exit /b 1)

echo.
echo Done: dist\AllowlistGuard.exe
popd
endlocal
