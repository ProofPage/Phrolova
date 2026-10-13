"""네이티브 설치와 종료는 격리된 경로·프로세스·패키지 명령으로 검증한다."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest

from app.core import file_browser, process_control as control
from tests.test_rebranding import BASH, ROOT, shell


def record(root, pid=123456, **changes):
    value = {'pid': pid, 'root': str(root.resolve()), 'started': 'stable start',
             'signature': 'same command', 'token': 'owner'}
    value.update(changes)
    path = root / 'backend/data/server.pid'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return value


@pytest.mark.parametrize('change', [{'started': 'reused PID'}, {'signature': 'other app'}, None])
def test_stop_never_signals_reused_or_unknown_process(tmp_path, monkeypatch, change):
    before = record(tmp_path)
    monkeypatch.setattr(control, 'identity', lambda pid: change)
    kill = Mock()
    monkeypatch.setattr(control.os, 'kill', kill)
    assert control.stop(tmp_path, 0) == 0
    kill.assert_not_called()
    assert control.read_record(tmp_path) == before


def test_stop_waits_for_matching_process_only(tmp_path, monkeypatch):
    current = record(tmp_path)
    active = True
    def identity(pid):
        return {'started': current['started'], 'signature': current['signature']} if active else None
    def kill(pid, sig):
        nonlocal active
        assert pid == current['pid'] and sig == control.signal.SIGTERM
        active = False
    monkeypatch.setattr(control, 'identity', identity)
    monkeypatch.setattr(control.os, 'kill', kill)
    assert control.stop(tmp_path, 1) == 0
    assert control.read_record(tmp_path) is None


def test_slow_shutdown_blocks_restart_without_forced_kill(tmp_path, monkeypatch):
    current = record(tmp_path)
    monkeypatch.setattr(control, 'identity', lambda pid: {'started': current['started'], 'signature': current['signature']})
    kill = Mock()
    monkeypatch.setattr(control.os, 'kill', kill)
    assert control.stop(tmp_path, 0) == 1
    kill.assert_called_once_with(current['pid'], control.signal.SIGTERM)
    assert control.read_record(tmp_path) == current


def test_registration_is_atomic_and_retains_data_on_error(tmp_path, monkeypatch):
    data = tmp_path / 'backend/data/media.db'
    data.parent.mkdir(parents=True)
    data.write_bytes(b'user data')
    monkeypatch.setattr(control, 'identity', lambda pid: {'started': 'start', 'signature': 'command'})
    monkeypatch.setattr(control, '_server_lock', lambda path: nullcontext())
    with pytest.raises(ValueError):
        with control.registered_server(tmp_path):
            assert control.read_record(tmp_path)['pid'] == os.getpid()
            with pytest.raises(RuntimeError, match='already running'):
                with control.registered_server(tmp_path):
                    pytest.fail('Duplicate registration')
            raise ValueError('Startup failure')
    assert control.read_record(tmp_path) is None
    assert data.read_bytes() == b'user data'


@pytest.mark.skipif(os.name == 'nt', reason='Native flock/ps integration runs in Linux/macOS CI')
def test_real_child_owns_lock_and_shuts_down_cleanly(tmp_path):
    script = tmp_path / 'run.py'
    script.write_text(f'''import signal,sys,time
from pathlib import Path
sys.path.insert(0,{str(ROOT / 'backend')!r})
from app.core.process_control import registered_server
def stop(*args): raise SystemExit(0)
with registered_server(Path({str(tmp_path)!r})):
    signal.signal(signal.SIGTERM, stop)
    Path({str(tmp_path / 'ready')!r}).touch()
    while True: time.sleep(.05)
''', encoding='utf-8')
    child = subprocess.Popen([sys.executable, str(script)], cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not (tmp_path / 'ready').exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(.05)
        assert (tmp_path / 'ready').exists(), child.communicate(timeout=1)
        owner = control.read_record(tmp_path)
        duplicate = subprocess.run([sys.executable, str(script)], cwd=tmp_path, capture_output=True, timeout=5)
        assert duplicate.returncode != 0 and b'owns this installation' in duplicate.stderr
        assert control.read_record(tmp_path) == owner
        assert control.stop(tmp_path, 5) == 0
        assert child.wait(timeout=5) == 0
        assert control.read_record(tmp_path) is None
    finally:
        if child.poll() is None:
            child.terminate()
        child.communicate(timeout=5)


@pytest.mark.parametrize('select_file', [False, True])
def test_macos_reveals_paths_and_checks_exit_status(tmp_path, monkeypatch, select_file):
    monkeypatch.setattr(file_browser.sys, 'platform', 'darwin')
    monkeypatch.setattr(file_browser.shutil, 'which', lambda name: '/usr/bin/open' if name == 'open' else None)
    execute = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(file_browser.subprocess, 'run', execute)
    path = tmp_path / '한글 폴더 with spaces'
    assert file_browser.reveal(path, select_file=select_file)
    assert execute.call_args.args[0] == ['/usr/bin/open', *(['-R'] if select_file else []), str(path.resolve())]
    execute.return_value.returncode = 1
    assert not file_browser.reveal(path, select_file=select_file)
    execute.side_effect = subprocess.TimeoutExpired('open', 10)
    assert not file_browser.reveal(path, select_file=select_file)


@pytest.mark.parametrize('native', [False, True])
def test_headless_and_native_android_do_not_launch_file_manager(tmp_path, monkeypatch, native):
    monkeypatch.setattr(file_browser.sys, 'platform', 'linux')
    monkeypatch.delenv('DISPLAY', raising=False)
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    monkeypatch.delenv('PREFIX', raising=False)
    monkeypatch.delenv('TERMUX_VERSION', raising=False)
    if native:
        monkeypatch.setenv('TERMUX_VERSION', 'test')
        monkeypatch.setenv('DISPLAY', ':0')
    execute = Mock()
    monkeypatch.setattr(file_browser.subprocess, 'run', execute)
    assert not file_browser.reveal(tmp_path)
    execute.assert_not_called()


@pytest.mark.skipif(BASH is None, reason='Bash unavailable')
def test_bsd_path_resolution_and_custom_install_symlink(tmp_path):
    repo = tmp_path / 'My 앱'
    (repo / 'scripts').mkdir(parents=True)
    (repo / 'backend').mkdir()
    (repo / 'frontend').mkdir()
    (repo / '.git').touch()
    (repo / 'scripts/manage.sh').write_bytes((ROOT / 'scripts/manage.sh').read_bytes())
    shell(tmp_path, '''
readlink() { [ "${1:-}" != -f ] || return 99; command readlink "$@"; }
mkdir -p "$HOME/bin"
ln -s '../My 앱/scripts/manage.sh' "$HOME/bin/phrolova"
ln -s phrolova "$HOME/bin/alias"
source "$HOME/bin/alias"
unset INSTALL_DIR
resolve_install_dir
[ "$INSTALL_DIR" = "$HOME/My 앱" ]
is_installed
''')


@pytest.mark.parametrize('manager,packages', [('pacman','nodejs npm'),('apk','nodejs npm'),('pkg','nodejs-lts')])
@pytest.mark.skipif(BASH is None, reason='Bash unavailable')
def test_native_node_install_never_uses_wrong_distribution_setup(tmp_path, manager, packages):
    shell(tmp_path, f'''
PKG_MANAGER={manager}; ready=0
activate_runtime_path() {{ :; }}
has_cmd() {{ case "$1" in node|npm) [ "$ready" = 1 ] ;; *) command -v "$1" >/dev/null ;; esac; }}
node() {{ if [ "$1" = -e ]; then printf 24; else printf 'v24.0.0\\n'; fi; }}
pkg_install() {{ printf '%s\\n' "$*" >> "$HOME/packages"; ready=1; }}
curl() {{ echo 'Unexpected NodeSource download' >&2; return 99; }}
ensure_node
[ "$(cat "$HOME/packages")" = '{packages}' ]
''')


@pytest.mark.skipif(BASH is None, reason='Bash unavailable')
def test_termux_installer_preserves_settings_and_uses_current_dependencies(tmp_path):
    repo = tmp_path / 'app'
    for folder in ('scripts', 'backend/data', 'frontend', 'prefix/bin'):
        (repo / folder).mkdir(parents=True, exist_ok=True)
    for name in ('manage.sh', 'install-termux.sh'):
        (repo / 'scripts' / name).write_bytes((ROOT / 'scripts' / name).read_bytes())
    (repo / '.env').write_text('DOWNLOAD_DIR=/keep/media\n', encoding='utf-8')
    (repo / 'backend/data/phrolova.db').write_bytes(b'preserve this database')
    bin_dir = repo / 'prefix/bin'
    python = '''#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$HOME/python-calls"
case "$*" in *chzzkpy*) exit 99 ;; esac
if [ "${1:-}" = -m ] && [ "${2:-}" = venv ]; then
  mkdir -p "$3/bin"; cp "$0" "$3/bin/python"; chmod +x "$3/bin/python"
elif [ "${1:-}" = --version ]; then echo 'Python 3.14.0'; fi
'''
    scripts = {'python3.12': python, 'python': python, 'pkg': '#!/usr/bin/env bash\nexit 0\n',
               'npm': '#!/usr/bin/env bash\nexit 0\n',
               'node': '#!/usr/bin/env bash\nif [ "$1" = -e ]; then printf 24; else echo v24.0.0; fi\n',
               'ffmpeg': '#!/usr/bin/env bash\necho "ffmpeg version 6.1.1"\n',
               'ffprobe': '#!/usr/bin/env bash\necho "ffprobe version 6.1.1"\n'}
    for name, text in scripts.items():
        path = bin_dir / name
        path.write_text(text, encoding='utf-8', newline='\n')
        path.chmod(0o755)
    shell(tmp_path, '''
export TERMUX_VERSION=test PREFIX="$HOME/app/prefix" PATH="$HOME/app/prefix/bin:$PATH"
bash "$HOME/app/scripts/install-termux.sh"
bash "$HOME/app/scripts/install-termux.sh"
grep -q 'requirements-termux.txt' "$HOME/python-calls"
! grep -q -- '--upgrade pip' "$HOME/python-calls"
[ -L "$PREFIX/bin/phrolova" ]
''')
    assert (repo / '.env').read_text() == 'DOWNLOAD_DIR=/keep/media\n'
    assert (repo / 'backend/data/phrolova.db').read_bytes() == b'preserve this database'


@pytest.mark.skipif(BASH is None, reason='Bash unavailable')
def test_homebrew_keg_runtime_and_python_are_resolved(tmp_path):
    shell(tmp_path, '''
mkdir -p "$HOME/brew/node/bin" "$HOME/brew/python/bin"
printf '#!/usr/bin/env bash\nprintf 24\n' > "$HOME/brew/node/bin/node"
printf '#!/usr/bin/env bash\nexit 0\n' > "$HOME/brew/node/bin/npm"
printf '#!/usr/bin/env bash\nexit 0\n' > "$HOME/brew/python/bin/python3.12"
chmod +x "$HOME/brew/node/bin/"* "$HOME/brew/python/bin/"*
uname() { echo Darwin; }
brew() { case "$*" in '--prefix node@22') echo "$HOME/brew/node" ;; '--prefix python@3.12') echo "$HOME/brew/python" ;; *) return 99 ;; esac; }
PKG_MANAGER=brew
has_cmd() { case "$1" in python|python3|python3.12|python3.13|python3.14) return 1 ;; *) command -v "$1" >/dev/null ;; esac; }
activate_runtime_path
[ "$(command -v node)" = "$HOME/brew/node/bin/node" ]
ensure_node
ensure_python
[ "$PYTHON_CMD" = "$HOME/brew/python/bin/python3.12" ]
''')


@pytest.mark.skipif(BASH is None, reason='Bash unavailable')
def test_invalid_venv_is_backed_up_without_touching_user_files(tmp_path):
    shell(tmp_path, '''
INSTALL_DIR="$HOME/app"; mkdir -p "$INSTALL_DIR/.venv/bin" "$INSTALL_DIR/backend/data"
printf 'old environment' > "$INSTALL_DIR/.venv/marker"
printf '#!/usr/bin/env bash\nexit 1\n' > "$INSTALL_DIR/.venv/bin/python"
chmod +x "$INSTALL_DIR/.venv/bin/python"
printf 'keep settings' > "$INSTALL_DIR/.env"
printf 'keep database' > "$INSTALL_DIR/backend/data/phrolova.db"
bootstrap() {
  [ "$1 $2" = '-m venv' ]; mkdir -p "$3/bin"
  printf '#!/usr/bin/env bash\nexit 0\n' > "$3/bin/python"; chmod +x "$3/bin/python"
}
PYTHON_CMD=bootstrap
setup_python_env
[ "$(cat "$INSTALL_DIR/.env")" = 'keep settings' ]
[ "$(cat "$INSTALL_DIR/backend/data/phrolova.db")" = 'keep database' ]
[ "$(cat "$INSTALL_DIR/.venv-backups/"*/marker)" = 'old environment' ]
"$INSTALL_DIR/.venv/bin/python" -c 'import pip'
''')


@pytest.mark.parametrize('platform', ['linux', 'darwin'])
def test_runtime_fallback_rejects_non_executable_files(tmp_path, monkeypatch, platform):
    from app.engine import youtube_support
    monkeypatch.setattr(youtube_support.sys, 'platform', platform)
    monkeypatch.setattr(youtube_support.shutil, 'which', lambda name: None)
    monkeypatch.setattr(youtube_support.os, 'access', lambda path, mode: False)
    monkeypatch.setattr(youtube_support.Path, 'is_file', lambda path: True)
    assert youtube_support.runtime_options() == {}


def test_linux_desktop_reveals_containing_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(file_browser.sys, 'platform', 'linux')
    monkeypatch.setenv('WAYLAND_DISPLAY', 'wayland-0')
    monkeypatch.delenv('TERMUX_VERSION', raising=False)
    monkeypatch.delenv('PREFIX', raising=False)
    monkeypatch.setattr(file_browser.shutil, 'which', lambda name: '/usr/bin/xdg-open')
    execute = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(file_browser.subprocess, 'run', execute)
    assert file_browser.reveal(tmp_path / 'file.mkv', select_file=True)
    assert execute.call_args.args[0] == ['/usr/bin/xdg-open', str(tmp_path.resolve())]
