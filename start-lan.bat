@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set DESK_LAN=1
set DESK_HOST=0.0.0.0
if "%DESK_TOKEN%"=="" (
  echo [!] Conseil Pixam: definis DESK_TOKEN avant le LAN, ex:
  echo     set DESK_TOKEN=ton-secret
  echo.
)

if exist "%~dp0PSHomebrewDesk.exe" (
  start "" "%~dp0PSHomebrewDesk.exe"
  exit /b 0
)
if exist "%~dp0dist\PSHomebrewDesk\PSHomebrewDesk.exe" (
  start "" "%~dp0dist\PSHomebrewDesk\PSHomebrewDesk.exe"
  exit /b 0
)

echo PS Homebrew Desk LAN (Windows) - by Pixam
python -m pip install --user -r requirements.txt >nul 2>&1
where pythonw >nul 2>&1
if %errorlevel%==0 (
  start "PS Homebrew Desk LAN" pythonw desktop.py
  exit /b 0
)
python desktop.py
if errorlevel 1 (
  echo.
  echo Echec. Verifie Python 3 + WebView2 Runtime.
  pause
)
