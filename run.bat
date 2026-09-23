@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto no_venv
echo Starting demo on http://localhost:8501
echo Close this window to stop it.
".venv\Scripts\python.exe" -m streamlit run app.py
goto end

:no_venv
echo ERROR: .venv not found. Run setup.bat first.

:end
echo.
pause
