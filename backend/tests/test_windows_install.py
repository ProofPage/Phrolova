"""Run the actual Windows installer with isolated Python/npm dependencies."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Windows batch execution is verified on Windows CI')
@pytest.mark.parametrize('ci_code,build_code,expected', [(17, 0, ['ci --silent']),
    (0, 19, ['ci --silent', 'run build']), (0, 0, ['ci --silent', 'run build'])])
def test_installer_propagates_npm_failures(tmp_path, ci_code, build_code, expected):
    root = tmp_path / 'project with spaces'
    scripts = root / 'scripts'
    scripts.mkdir(parents=True)
    script = scripts / 'manage.bat'
    shutil.copyfile(Path(__file__).resolve().parents[2] / 'scripts/manage.bat', script)
    (root / 'frontend').mkdir()
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(root / 'backend/.venv')], check=True)
    stubs = tmp_path / 'stubs'
    (stubs / 'pip').mkdir(parents=True)
    (stubs / 'pip/__main__.py').write_text('raise SystemExit(0)\n')
    (stubs / 'npm.cmd').write_text(
        '@echo off\necho %*>>"%NPM_CALLS%"\n'
        f'if "%1"=="ci" exit /b {ci_code}\nexit /b {build_code}\n')
    calls = tmp_path / 'npm-calls.txt'
    env = {**os.environ, 'PYTHONPATH': str(stubs), 'PATH': str(stubs) + os.pathsep + os.environ['PATH'],
           'NPM_CALLS': str(calls)}
    result = subprocess.run([os.environ['COMSPEC'], '/d', '/c', str(script), 'install'], env=env,
                            capture_output=True, timeout=30)
    output = result.stdout.decode('utf-8', errors='replace')
    assert result.returncode == (1 if ci_code or build_code else 0), output
    assert calls.read_text().splitlines() == expected, output
    assert ('[완료]' in output) is not bool(ci_code or build_code), output


@pytest.mark.skipif(os.name != 'nt', reason='Windows batch execution is verified on Windows CI')
def test_installer_old_venv_backup_failure_preserves_original(tmp_path):
    root = tmp_path / 'proj_fail'
    scripts = root / 'scripts'
    scripts.mkdir(parents=True)
    script = scripts / 'manage.bat'
    shutil.copyfile(Path(__file__).resolve().parents[2] / 'scripts/manage.bat', script)
    (root / 'frontend').mkdir()

    venv = root / 'backend/.venv'
    venv_scripts = venv / 'Scripts'
    venv_scripts.mkdir(parents=True)
    marker = venv / 'marker.txt'
    marker.write_text('original-venv-data', encoding='utf-8')
    py_stub = venv_scripts / 'python.exe'
    py_stub.write_bytes(b'dummy-broken-python')

    # Hold a file open to lock the venv folder and force move failure
    with open(marker, 'r+b'):
        result = subprocess.run([os.environ['COMSPEC'], '/d', '/c', str(script), 'install'],
                                capture_output=True, timeout=30)

    output = result.stdout.decode('utf-8', errors='replace')
    assert result.returncode == 1, output
    assert venv.exists(), "Original venv must be preserved when backup move fails"
    assert marker.read_text(encoding='utf-8') == 'original-venv-data'
    assert '기존 가상환경 백업에 실패했습니다' in output or '보존하고 설치를 중단합니다' in output


@pytest.mark.skipif(os.name != 'nt', reason='Windows batch execution is verified on Windows CI')
@pytest.mark.parametrize('date_format', ['10/21/2026', '21/10/2026', 'Wed 10/21/2026'])
def test_installer_old_venv_successful_backup_and_locale_date(tmp_path, date_format):
    safe_name = date_format.replace('/', '_').replace(' ', '_')
    root = tmp_path / f'proj_{safe_name}'
    scripts = root / 'scripts'
    scripts.mkdir(parents=True)
    script = scripts / 'manage.bat'
    shutil.copyfile(Path(__file__).resolve().parents[2] / 'scripts/manage.bat', script)
    (root / 'frontend').mkdir()

    venv = root / 'backend/.venv'
    venv_scripts = venv / 'Scripts'
    venv_scripts.mkdir(parents=True)
    sentinel = venv / 'sentinel.txt'
    sentinel.write_text('old-env-sentinel', encoding='utf-8')
    (venv_scripts / 'python.exe').write_bytes(b'dummy-old-python')

    stubs = tmp_path / f'stubs_{safe_name}'
    stubs.mkdir(parents=True, exist_ok=True)
    (stubs / 'pip').mkdir(parents=True, exist_ok=True)
    (stubs / 'pip/__main__.py').write_text('raise SystemExit(0)\n', encoding='utf-8')
    sys_exe = str(Path(sys.executable).resolve())
    (stubs / 'python.cmd').write_text(
        '@echo off\n'
        'if "%1"=="-c" exit /b 0\n'
        'if "%1"=="-m" if "%2"=="venv" (\n'
        '    mkdir "%~3\\Scripts" 2>nul\n'
        f'    copy /y "{sys_exe}" "%~3\\Scripts\\python.exe" >nul\n'
        '    exit /b 0\n'
        ')\n'
        'exit /b 0\n',
        encoding='utf-8'
    )
    (stubs / 'npm.cmd').write_text('@echo off\nexit /b 0\n', encoding='utf-8')

    env = {
        **os.environ,
        'DATE': date_format,
        'PYTHONPATH': str(stubs),
        'PATH': str(stubs) + os.pathsep + os.environ.get('PATH', ''),
    }

    result = subprocess.run([os.environ['COMSPEC'], '/d', '/c', str(script), 'install'],
                            env=env, capture_output=True, timeout=30)
    output = result.stdout.decode('utf-8', errors='replace')
    assert result.returncode == 0, output

    backup_dir = root / 'backend/.venv-backups'
    assert backup_dir.is_dir(), output
    backups = list(backup_dir.glob('.venv-*'))
    assert len(backups) == 1, f"Expected exactly 1 backup directory, found: {backups}"
    assert (backups[0] / 'sentinel.txt').read_text(encoding='utf-8') == 'old-env-sentinel'
