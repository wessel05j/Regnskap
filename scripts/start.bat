@echo off
setlocal

cd /d "%~dp0\.."

set "PY_BOOTSTRAP="
where py >nul 2>nul
if not errorlevel 1 (
    py -3.11 --version >nul 2>nul
    if not errorlevel 1 set "PY_BOOTSTRAP=py -3.11"
    if not defined PY_BOOTSTRAP (
        py -3 --version >nul 2>nul
        if not errorlevel 1 set "PY_BOOTSTRAP=py -3"
    )
)
if not defined PY_BOOTSTRAP (
    where python >nul 2>nul
    if not errorlevel 1 set "PY_BOOTSTRAP=python"
)
if not defined PY_BOOTSTRAP goto :python_missing

if not exist ".venv\Scripts\python.exe" (
    echo Oppretter virtuelt miljo ^(.venv^)...
    %PY_BOOTSTRAP% -m venv .venv
    if errorlevel 1 goto :venv_failed
)

set "VENV_PYTHON=.venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" goto :venv_failed

%VENV_PYTHON% -c "import fastapi,uvicorn,jinja2,pydantic,reportlab,multipart" >nul 2>nul
if errorlevel 1 (
    echo Installerer avhengigheter...
    %VENV_PYTHON% -m pip install --upgrade pip
    %VENV_PYTHON% -m pip install -r requirements.txt
    if errorlevel 1 goto :deps_failed
)

start "" "http://127.0.0.1:8000"
echo Starter server pa http://127.0.0.1:8000 ...
%VENV_PYTHON% -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
if errorlevel 1 goto :run_failed

endlocal
exit /b 0

:python_missing
echo Fant ikke Python. Installer Python 3.11+ og prover igjen.
pause
exit /b 1

:venv_failed
echo Klarte ikke opprette/finne virtuelt miljo (.venv).
pause
exit /b 1

:deps_failed
echo Klarte ikke installere avhengigheter.
pause
exit /b 1

:run_failed
echo Serveren stoppet med feil. Se meldinger over.
pause
exit /b 1
