@echo off
REM DOM 한글패치 웹 툴 시작/멈춤 스크립트 (Windows)
setlocal enabledelayedexpansion

set "DIR=%~dp0"
set "PID_FILE=%DIR%.server.pid"
set "LOG_FILE=%DIR%server.log"
set "ERR_LOG_FILE=%DIR%server.err.log"
if "%PORT%"=="" set "PORT=4000"

where python >nul 2>&1
if not errorlevel 1 (
  set "PY_CMD=python"
) else (
  where py >nul 2>&1
  if not errorlevel 1 (
    set "PY_CMD=py"
  ) else (
    echo Python이 설치되어 있지 않습니다. https://www.python.org/downloads/ 에서 설치 후 다시 실행하세요.
    exit /b 1
  )
)

if /i "%~1"=="start" goto start
if /i "%~1"=="stop" goto stop
if /i "%~1"=="restart" goto restart
if /i "%~1"=="status" goto status
goto usage

:ensure_deps
%PY_CMD% -c "import flask, PIL" >nul 2>&1
if errorlevel 1 (
  echo 필요한 파이썬 패키지를 설치합니다...
  %PY_CMD% -m pip install -r "%DIR%requirements.txt"
)
exit /b 0

:is_running
if not exist "%PID_FILE%" exit /b 1
set "CHECK_PID="
for /f "usebackq" %%P in ("%PID_FILE%") do set "CHECK_PID=%%P"
if "%CHECK_PID%"=="" exit /b 1
tasklist /FI "PID eq %CHECK_PID%" 2>nul | find "%CHECK_PID%" >nul
if errorlevel 1 exit /b 1
exit /b 0

:start
call :is_running
if not errorlevel 1 (
  set /p RUNPID=<"%PID_FILE%"
  echo 이미 실행 중입니다. PID !RUNPID!, http://localhost:%PORT%
  exit /b 0
)
call :ensure_deps
cd /d "%DIR%"
powershell -NoProfile -Command "$p = Start-Process -FilePath '%PY_CMD%' -ArgumentList 'server_py\app.py' -WorkingDirectory '%DIR%' -WindowStyle Hidden -RedirectStandardOutput '%LOG_FILE%' -RedirectStandardError '%ERR_LOG_FILE%' -PassThru; $p.Id | Out-File -Encoding ascii '%PID_FILE%'"
timeout /t 1 /nobreak >nul
call :is_running
if errorlevel 1 (
  echo 서버 시작 실패. 로그:
  type "%LOG_FILE%" 2>nul
  type "%ERR_LOG_FILE%" 2>nul
  del "%PID_FILE%" 2>nul
  exit /b 1
) else (
  set /p RUNPID=<"%PID_FILE%"
  echo 서버 시작됨. PID !RUNPID!, http://localhost:%PORT%
)
goto :eof

:stop
call :is_running
if errorlevel 1 (
  echo 실행 중이 아닙니다
  del "%PID_FILE%" 2>nul
  exit /b 0
)
set /p RUNPID=<"%PID_FILE%"
taskkill /PID %RUNPID% /T /F >nul 2>&1
del "%PID_FILE%" 2>nul
echo 서버 종료됨
goto :eof

:restart
call :stop
call :start
goto :eof

:status
call :is_running
if errorlevel 1 (
  echo 중지됨
) else (
  set /p RUNPID=<"%PID_FILE%"
  echo 실행 중. PID !RUNPID!, http://localhost:%PORT%
)
goto :eof

:usage
echo 사용법: %~nx0 {start^|stop^|restart^|status}
exit /b 1
