@echo off
REM
REM Lanceur Windows (Batch) pour l'application BOAMP.
REM - Crée/active un venv, installe les deps si nécessaire, démarre le serveur,
REM   et ouvre le navigateur sur http://localhost:8000
REM
REM One-click launcher for Windows (double-clickable .bat)
REM - Creates a virtualenv if missing
REM - Installs dependencies
REM - Starts the Flask server
REM - Opens the browser to http://localhost:8000

setlocal ENABLEDELAYEDEXPANSION
cd /d "%~dp0"

REM Detect python
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  set PY=py -3
) else (
  where python >nul 2>nul
  if %ERRORLEVEL%==0 (
    set PY=python
  ) else (
    echo Python non trouve. Installez Python 3 depuis https://www.python.org/downloads/
    pause
    exit /b 1
  )
)

REM Create venv if needed
if not exist .venv (
  %PY% -m venv .venv
)

REM Activate venv
call .venv\Scripts\activate

REM Install requirements only if needed
set "REQ=%CD%\Back-end\requirements.txt"
set "STAMP=%CD%\.venv\.requirements.sha256"

for /f "usebackq delims=" %%H in (`%PY% -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "%REQ%"`) do set REQHASH=%%H
set NEEDINSTALL=0
if exist "%STAMP%" (
  set /p CURHASH=<"%STAMP%"
) else (
  set CURHASH=
)

REM Check if modules are available in current venv
%PY% -m pip show flask >nul 2>nul
if NOT %ERRORLEVEL%==0 set NEEDINSTALL=1
%PY% -m pip show certifi >nul 2>nul
if NOT %ERRORLEVEL%==0 set NEEDINSTALL=1
if NOT "%REQHASH%"=="%CURHASH%" set NEEDINSTALL=1

if %NEEDINSTALL%==1 (
  python -m pip install --upgrade pip >nul
  python -m pip install -r Back-end\requirements.txt
  >"%STAMP%" echo %REQHASH%
)

REM If a local CA is present, set env so app trusts it
if exist Back-end\local_ca.pem (
  set "LOCAL_CA_FILE=%CD%\Back-end\local_ca.pem"
  set "SSL_CERT_FILE=%CD%\Back-end\local_ca.pem"
)

REM Prefer Explore v2.1 by default
set PREFER_EXPLORE=1

REM Open browser shortly after server starts
start "" http://localhost:8000

REM Run server
python Back-end\app.py

echo.
echo Serveur arrete. Fermez cette fenetre ou appuyez sur une touche…
pause >nul
