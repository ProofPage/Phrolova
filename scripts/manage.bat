@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

REM ═══════════════════════════════════════════════════════════
REM  Rookery — 통합 관리 스크립트 (Windows)
REM
REM    scripts\manage.bat install    의존성 설치 + 프론트엔드 빌드
REM    scripts\manage.bat start      서버 실행
REM    scripts\manage.bat dev        개발 모드 (백엔드/프론트 창 분리)
REM    scripts\manage.bat update     최신 코드로 갱신 후 재설치
REM    scripts\manage.bat status     상태 확인
REM ═══════════════════════════════════════════════════════════

cd /d "%~dp0\.."
set "ROOT=%CD%"
set "VENV=%ROOT%\backend\.venv"
set "PY=%VENV%\Scripts\python.exe"

set "CMD=%~1"
if "%CMD%"=="" goto :help
if /i "%CMD%"=="help"      goto :help
if /i "%CMD%"=="--help"    goto :help
if /i "%CMD%"=="install"   goto :install
if /i "%CMD%"=="start"     goto :start
if /i "%CMD%"=="dev"       goto :dev
if /i "%CMD%"=="update"    goto :update
if /i "%CMD%"=="status"    goto :status

echo [!] 알 수 없는 명령: %CMD%
echo.
goto :help


:install
echo.
echo ^> Python 가상환경
if not exist "%VENV%" (
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo [X] Python 가상환경 생성 실패. Python 3.10 이상이 설치되어 있는지 확인하세요.
        exit /b 1
    )
    echo   [+] 생성 완료
) else (
    echo   [+] 이미 존재함
)

echo.
echo ^> Python 의존성
"%PY%" -m pip install --upgrade pip -q
"%PY%" -m pip install -r "%ROOT%\backend\requirements.txt" -q
if errorlevel 1 (
    echo [X] 의존성 설치 실패
    exit /b 1
)
echo   [+] 설치 완료

echo.
echo ^> 프론트엔드 빌드
where npm >nul 2>&1
if errorlevel 1 (
    echo   [!] npm을 찾을 수 없어 빌드를 건너뜁니다.
    echo       Node.js 20 이상을 설치하면 웹 UI를 빌드할 수 있습니다: https://nodejs.org
) else (
    pushd "%ROOT%\frontend"
    call npm ci --silent
    call npm run build
    popd
    echo   [+] 빌드 완료
)

echo.
echo [완료] 실행: scripts\manage.bat start
echo.
goto :eof


:start
if not exist "%PY%" (
    echo [X] 가상환경이 없습니다. 먼저 실행하세요: scripts\manage.bat install
    exit /b 1
)
echo [INFO] 서버를 시작합니다. 종료하려면 Ctrl+C 를 누르세요.
echo [INFO] 접속: http://localhost:8000
echo.
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend
goto :eof


:dev
if not exist "%PY%" (
    echo [X] 가상환경이 없습니다. 먼저 실행하세요: scripts\manage.bat install
    exit /b 1
)
echo [INFO] 개발 서버를 시작합니다 (백엔드 / 프론트엔드 창이 각각 열립니다).
start "Rookery — Backend"  cmd /k ""%PY%" -m uvicorn app.main:app --reload --app-dir backend"
start "Rookery — Frontend" cmd /k "cd /d "%ROOT%\frontend" && npm run dev"
echo [INFO] 두 창이 열렸습니다.
goto :eof


:update
where git >nul 2>&1
if errorlevel 1 (
    echo [X] git을 찾을 수 없습니다. https://git-scm.com 에서 설치하세요.
    exit /b 1
)
echo.
echo ^> 최신 코드 가져오기
git -C "%ROOT%" pull --ff-only
if errorlevel 1 (
    echo [X] 업데이트 실패. 로컬 변경사항이 있는지 확인하세요.
    exit /b 1
)
echo   [+] 완료
call "%~f0" install
goto :eof


:status
echo.
if exist "%ROOT%\backend\app\version.py" (
    for /f "tokens=2 delims==" %%v in ('findstr /r "^__version__" "%ROOT%\backend\app\version.py"') do (
        set "VER=%%v"
        set "VER=!VER: =!"
        set "VER=!VER:"=!"
        echo   버전   !VER!
    )
)
echo   경로   %ROOT%
if exist "%PY%" (echo   환경   구성됨) else (echo   환경   미구성 - manage.bat install 필요)

curl -sf http://localhost:8000/health >nul 2>&1
if errorlevel 1 (echo   서버   응답 없음) else (echo   서버   응답 정상)
echo.
goto :eof


:help
echo.
echo   Rookery 관리 명령
echo.
echo     scripts\manage.bat install    의존성 설치 + 프론트엔드 빌드
echo     scripts\manage.bat start      서버 실행
echo     scripts\manage.bat dev        개발 모드 (백엔드/프론트 창 분리)
echo     scripts\manage.bat update     최신 코드로 갱신 후 재설치
echo     scripts\manage.bat status     상태 확인
echo.
echo   Linux / macOS 에서는 scripts/manage.sh 를 사용하세요.
echo.
goto :eof
