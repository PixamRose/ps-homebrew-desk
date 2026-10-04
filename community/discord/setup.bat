@echo off
setlocal
cd /d "%~dp0"

echo === Pixam Community — setup Discord ===
echo.

if not exist .env (
  echo [!] Fichier .env manquant.
  echo     Copie .env.example vers .env et renseigne DISCORD_TOKEN + DISCORD_GUILD_ID
  copy .env.example .env >nul
  notepad .env
  echo.
  echo Relance setup.bat une fois .env rempli.
  pause
  exit /b 1
)

python -m pip install -r requirements.txt -q
if errorlevel 1 (
  echo [!] pip a echoue. Verifie que Python est installe et dans le PATH.
  pause
  exit /b 1
)

python setup_server.py
echo.
pause
