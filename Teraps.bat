@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 teraps.py
  exit /b %errorlevel%
)

where python >nul 2>nul
if %errorlevel%==0 (
  python teraps.py
  exit /b %errorlevel%
)

echo Python nao encontrado. Instale Python 3 e execute Teraps.bat novamente.
pause
exit /b 1
