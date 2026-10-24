@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

REM ===========================================================
REM  Phrolova - 통합 관리 스크립트 (Windows)
REM
REM    scripts\manage.bat install    의존성 설치 + 프론트엔드 빌드
REM    scripts\manage.bat start      서버 실행
REM    scripts\manage.bat dev        개발 모드 (백엔드/프론트 창 분리)
REM    scripts\manage.bat update     최신 코드로 갱신 후 재설치
REM    scripts\manage.bat status     상태 확인
REM ===========================================================

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


:help
echo.
echo   Phrolova 관리 명령
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


:install
echo.
echo ^> Python 가상환경
if exist "%VENV%" (
    set "VENV_OK=0"
    if exist "%PY%" (
        "%PY%" -c "import sys; assert sys.version_info >= (3, 14, 8) and getattr(sys, '_is_gil_enabled', lambda: True)()" >nul 2>&1
        if not errorlevel 1 set "VENV_OK=1"
    )
    if "!VENV_OK!"=="0" (
        echo   [주의] 기존 가상환경이 Python 3.14.8 기준과 호환되지 않아 보존합니다.
        set "BACKUP_DIR=%ROOT%\backend\.venv-backups"
        if not exist "!BACKUP_DIR!" mkdir "!BACKUP_DIR!"
        set "BACKUP_NAME=!BACKUP_DIR!\.venv-!RANDOM!-!RANDOM!"
        if exist "!BACKUP_NAME!" set "BACKUP_NAME=!BACKUP_DIR!\.venv-!RANDOM!-!RANDOM!"
        if exist "!BACKUP_NAME!" set "BACKUP_NAME=!BACKUP_DIR!\.venv-!RANDOM!-!RANDOM!-!RANDOM!"
        if exist "!BACKUP_NAME!" (
            echo [X] 백업 대상 경로가 이미 존재하여 원본을 보존하고 설치를 중단합니다.
            (goto) 2>nul & exit /b 1
        )
        move "%VENV%" "!BACKUP_NAME!" >nul 2>&1
        if errorlevel 1 (
            echo [X] 기존 가상환경 백업에 실패했습니다. 원본을 보존하고 설치를 중단합니다.
            (goto) 2>nul & exit /b 1
        )
        if exist "%VENV%" (
            echo [X] 기존 가상환경이 남아 있어 원본을 보존하고 설치를 중단합니다.
            (goto) 2>nul & exit /b 1
        )
    )
)

if not exist "%VENV%" (
    set "BOOTSTRAP_PY="
    call py -3.14 -c "import sys; assert sys.version_info >= (3, 14, 8) and getattr(sys, '_is_gil_enabled', lambda: True)()" >nul 2>&1
    if not errorlevel 1 set "BOOTSTRAP_PY=py -3.14"
    if not defined BOOTSTRAP_PY (
        call python3.14 -c "import sys; assert sys.version_info >= (3, 14, 8) and getattr(sys, '_is_gil_enabled', lambda: True)()" >nul 2>&1
        if not errorlevel 1 set "BOOTSTRAP_PY=python3.14"
    )
    if not defined BOOTSTRAP_PY (
        call python -c "import sys; assert sys.version_info >= (3, 14, 8) and getattr(sys, '_is_gil_enabled', lambda: True)()" >nul 2>&1
        if not errorlevel 1 set "BOOTSTRAP_PY=python"
    )
    if not defined BOOTSTRAP_PY (
        call py -3 -c "import sys; assert sys.version_info >= (3, 14, 8) and getattr(sys, '_is_gil_enabled', lambda: True)()" >nul 2>&1
        if not errorlevel 1 set "BOOTSTRAP_PY=py -3"
    )
    if not defined BOOTSTRAP_PY (
        echo [X] Python 3.14.8 이상 ^(표준 GIL^)을 찾을 수 없습니다. Python 3.14.8을 설치하세요.
        (goto) 2>nul & exit /b 1
    )
    call !BOOTSTRAP_PY! -m venv "%VENV%"
    if errorlevel 1 (
        echo [X] Python 가상환경 생성 실패. Python 3.14.8 이상이 설치되어 있는지 확인하세요.
        (goto) 2>nul & exit /b 1
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
    echo [X] npm을 찾을 수 없습니다. Node.js 22 이상을 설치하세요: https://nodejs.org
    exit /b 1
)
pushd "%ROOT%\frontend"
call npm ci --silent
if errorlevel 1 (
    popd
    echo [X] 프론트엔드 의존성 설치 실패
    exit /b 1
)
call npm run build
if errorlevel 1 (
    popd
    echo [X] 프론트엔드 빌드 실패
    exit /b 1
)
popd
echo   [+] 빌드 완료

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
start "Phrolova - Backend"  cmd /k ""%PY%" -m uvicorn app.main:app --reload --app-dir backend"
start "Phrolova - Frontend" cmd /k "cd /d "%ROOT%\frontend" && npm run dev"
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
