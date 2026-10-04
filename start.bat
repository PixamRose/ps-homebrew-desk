@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM Prefer packaged build (no source exposed)
if exist "%~dp0PSHomebrewDesk.exe" (
  start "" "%~dp0PSHomebrewDesk.exe"
  exit /b 0
)
if exist "%~dp0dist\PSHomebrewDesk\PSHomebrewDesk.exe" (
  start "" "%~dp0dist\PSHomebrewDesk\PSHomebrewDesk.exe"
  exit /b 0
)

echo PS Homebrew Desk (Windows) - by Pixam
echo Mode source: Python + WebView2 requis.
python -m pip install --user -r requirements.txt >nul 2>&1
where pythonw >nul 2>&1
if %errorlevel%==0 (
  start "PS Homebrew Desk" pythonw desktop.py
  exit /b 0
)
python desktop.py
if errorlevel 1 (
  echo.
  echo Echec. Verifie Python 3 + WebView2 Runtime.
  echo Ou build un .exe avec scripts\build-windows.bat
  pause
)
