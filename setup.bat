@echo off
setlocal
cd /d "%~dp0"
echo ====================================
echo   Setup: virtualenv + packages
echo ====================================
echo.

py --version >nul 2>&1
if errorlevel 1 goto try_python
set PY=py
goto have_python

:try_python
python --version >nul 2>&1
if errorlevel 1 goto no_python
set PY=python
goto have_python

:no_python
echo ERROR: Python not found.
echo Install it from python.org, tick "Add Python to PATH", then run this again.
goto end

:have_python
echo [1/4] Python:
%PY% --version
echo.

echo [2/4] Creating virtual environment...
%PY% -m venv .venv
if errorlevel 1 goto venv_failed
echo.

echo [3/4] Installing packages, 1-2 minutes...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto pip_failed
echo.

echo [4/4] Preparing .env...
if exist .env goto env_exists
copy .env.example .env >nul
echo Created .env - open it and paste your OPENAI_API_KEY
goto done

:env_exists
echo .env already exists, leaving it alone
goto done

:venv_failed
echo ERROR: could not create .venv
goto end

:pip_failed
echo ERROR: could not install packages. Check internet connection.
goto end

:done
echo.
echo ====================================
echo   DONE
echo   Next: paste the key into .env,
echo   then run check.bat
echo ====================================

:end
echo.
pause
