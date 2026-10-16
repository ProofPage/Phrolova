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
