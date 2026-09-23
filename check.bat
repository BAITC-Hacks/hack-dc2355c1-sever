@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto no_venv
".venv\Scripts\python.exe" smoke_test.py
goto end

:no_venv
echo ERROR: .venv not found. Run setup.bat first.

:end
echo.
pause
