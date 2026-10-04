@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo === PS Homebrew Desk — build Windows (by Pixam) ===
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo Python introuvable. Installe Python 3 depuis python.org et coche "Add to PATH".
  pause
  exit /b 1
)

python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
  echo Echec pip.
  pause
  exit /b 1
)

if not exist "assets\AppIcon.ico" (
  echo assets\AppIcon.ico manquant.
  pause
  exit /b 1
)

echo Nettoyage dist/build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo Compilation PyInstaller...
python -m PyInstaller --noconfirm packaging\pshomebrew-desk.spec
if errorlevel 1 (
  echo Echec build.
  pause
  exit /b 1
)

echo.
echo OK — dossier a zipper / publier :
echo   dist\PSHomebrewDesk\
echo   ^> PSHomebrewDesk.exe  (double-clic)
echo.
echo WebView2 Runtime requis (Edge) si Windows l'a pas deja.
echo Ne publie PAS le dossier source — seulement dist\PSHomebrewDesk\
echo.
pause
