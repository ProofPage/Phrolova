"""Brand migration tests use only isolated databases and mocked Linux services."""
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from app.store.db import DB_FILENAME, Database, _resolve_db_path

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('name', ['rookery.db', 'signal_recorder.db'])
def test_all_legacy_tables_preserved(tmp_path, name):
    original = Database(tmp_path / name)
    conn = original.connect()
    conn.execute("INSERT INTO meta(key,value) VALUES ('test','preserved')")
    conn.execute("INSERT INTO channels(composite_key,platform,channel_id) VALUES ('chzzk:test','chzzk','test')")
    conn.execute("INSERT INTO tags(name) VALUES ('preserved')")
    conn.execute("INSERT INTO live_history(composite_key,platform,channel_id,ended_at) VALUES ('chzzk:test','chzzk','test','2026-10-09')")
    conn.execute("INSERT INTO vod_tasks(task_id,url,state,payload) VALUES ('task','https://chzzk.naver.com/video/1','completed','{\"quality\":\"720p\"}')")
    conn.execute("INSERT INTO pending_notifications(id,kind,title,created_at) VALUES ('notice','test','preserved',1)")
    tables = ['channels', 'tags', 'live_history', 'vod_tasks', 'pending_notifications']
    expected = {name: [tuple(row) for row in conn.execute(f'SELECT * FROM {name}')] for name in tables}
    schema = conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    original.close()
    migrated = _resolve_db_path(tmp_path)
    assert migrated.name == DB_FILENAME
    with sqlite3.connect(migrated) as conn:
        for table in tables:
            assert conn.execute(f'SELECT * FROM {table}').fetchall() == expected[table]
        assert conn.execute("SELECT value FROM meta WHERE key='test'").fetchone() == ('preserved',)
        assert [tuple(row) for row in schema] == conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    assert (tmp_path / name).exists()
    assert _resolve_db_path(tmp_path) == migrated


def test_migration_failure_and_restart(tmp_path, monkeypatch):
    original = tmp_path / 'rookery.db'
    with sqlite3.connect(original) as conn:
        conn.execute('CREATE TABLE sample(value)')
        conn.execute("INSERT INTO sample VALUES ('keep')")
    real_link = os.link
    def fail(*args):
        raise PermissionError('simulated publication failure')
    monkeypatch.setattr(os, 'link', fail)
    assert _resolve_db_path(tmp_path) == original
    assert not (tmp_path / DB_FILENAME).exists()
    assert not list(tmp_path.glob('.phrolova-migration-*'))
    # A crash can leave an unpublished temporary file: never trust it.
    (tmp_path / '.phrolova-migration-interrupted').write_bytes(b'incomplete')
    monkeypatch.setattr(os, 'link', real_link)
    result = _resolve_db_path(tmp_path)
    with sqlite3.connect(result) as conn:
        assert conn.execute('SELECT value FROM sample').fetchone() == ('keep',)


def test_invalid_legacy_never_creates_empty_new_db(tmp_path):
    original = tmp_path / 'rookery.db'
    original.write_bytes(b'corrupt database')
    assert _resolve_db_path(tmp_path) == original
    assert not (tmp_path / DB_FILENAME).exists()


def shell(tmp_path, body):
    # Source function definitions without invoking the command entry point.
    source = (ROOT / 'scripts/manage.sh').read_text().rsplit('main "$@"', 1)[0]
    script = tmp_path / 'functions.sh'
    script.write_text(source + '\n' + body)
    result = subprocess.run(['bash', str(script)], capture_output=True, text=True, env={**os.environ, 'HOME': str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_install_dir_priority_and_legacy(tmp_path):
    (tmp_path / 'rookery/.git').mkdir(parents=True)
    # The sourced script lives outside a repository so path resolution is isolated.
    shell(tmp_path, '''
resolve_install_dir
[ "$INSTALL_DIR" = "$HOME/rookery" ]
INSTALL_DIR="$HOME/custom"; resolve_install_dir
[ "$INSTALL_DIR" = "$HOME/custom" ]
''')
    (tmp_path / 'rookery/.git').rmdir()
    shell(tmp_path, 'unset INSTALL_DIR; resolve_install_dir; [ "$INSTALL_DIR" = "$HOME/Phrolova" ]')


def test_command_links_safe_transition(tmp_path):
    shell(tmp_path, '''
SYSTEM_BINDIR="$HOME/bin"; USER_BINDIR="$HOME/userbin"; INSTALL_DIR="$HOME/install"
mkdir -p "$SYSTEM_BINDIR" "$INSTALL_DIR/scripts"
printf '#!/bin/sh\\n' > "$INSTALL_DIR/scripts/manage.sh"
ln -s "$INSTALL_DIR/scripts/manage.sh" "$SYSTEM_BINDIR/rookery"
link_self
[ -L "$SYSTEM_BINDIR/phrolova" ] && [ ! -L "$SYSTEM_BINDIR/rookery" ]
printf 'unrelated' > "$SYSTEM_BINDIR/rookery"
remove_legacy_commands
[ "$(cat "$SYSTEM_BINDIR/rookery")" = unrelated ]
''')


@pytest.mark.parametrize('failure', [False, True])
def test_service_transition_and_rollback(tmp_path, failure):
    shell(tmp_path, '''
INSTALL_DIR="$HOME/install"; SYSTEMD_RUNTIME_DIR="$HOME/runtime"; SYSTEMD_UNIT_DIR="$HOME/units"
mkdir -p "$SYSTEMD_RUNTIME_DIR" "$SYSTEMD_UNIT_DIR"
printf 'legacy unit' > "$SYSTEMD_UNIT_DIR/rookery.service"
active_old=1; enabled_old=1; active_new=0; enabled_new=0
has_cmd() { return 0; }
wait_for_health() { return 0; }
SUDO=""
systemctl() {
  case "$1 ${2:-}" in
    'cat rookery.service') return 0 ;;
    cat*) return 1 ;;
    'is-active --quiet') [ "$3" = rookery ] && [ "$active_old" = 1 ] ;;
    'is-enabled --quiet') [ "$3" = rookery ] && [ "$enabled_old" = 1 ] ;;
    'disable --now')
      if [ "$3" = rookery ]; then active_old=0; enabled_old=0; else active_new=0; enabled_new=0; fi ;;
    'enable --now')
      [ "$active_old" = 0 ] || return 8
      ''' + ('return 9' if failure else 'active_new=1; enabled_new=1') + ''' ;;
    'enable rookery') enabled_old=1 ;;
    'start rookery') active_old=1 ;;
    'daemon-reload ') return 0 ;;
    *) return 7 ;;
  esac
}
rc=0; service_install || rc=$?
''' + ('''
[ "$rc" = 1 ] && [ "$active_old" = 1 ] && [ "$enabled_old" = 1 ]
[ ! -f "$SYSTEMD_UNIT_DIR/phrolova.service" ]
''' if failure else '''
[ "$rc" = 0 ] && [ "$active_old" = 0 ] && [ "$active_new" = 1 ]
grep -q 'Description=Phrolova - Live Stream Recorder' "$SYSTEMD_UNIT_DIR/phrolova.service"
''') + '''
[ "$(cat "$SYSTEMD_UNIT_DIR/rookery.service")" = 'legacy unit' ]
''')


def test_management_commands_and_update_restart(tmp_path):
    shell(tmp_path, '''
INSTALL_DIR="$HOME/install"; SYSTEMD_UNIT_DIR="$HOME/units"; SUDO=""
mkdir -p "$INSTALL_DIR" "$SYSTEMD_UNIT_DIR"
require_install() { return 0; }
service_exists() { return 0; }
legacy_service_exists() { return 1; }
legacy_service_active() { return 1; }
wait_for_health() { return 0; }
current_port() { echo 8000; }
app_version() { echo 2.0.51; }
systemctl() { echo "$*" >> "$HOME/calls"; }
journalctl() { echo "$*" >> "$HOME/calls"; }
cmd_start; cmd_stop; cmd_restart; cmd_logs
sync_repo() { return 0; }
detect_os() { :; }; ensure_node() { :; }; build_frontend() { :; }; link_self() { :; }
venv_pip() { echo true; }
cmd_update
printf 'new unit' > "$SYSTEMD_UNIT_DIR/phrolova.service"
service_remove
[ ! -f "$SYSTEMD_UNIT_DIR/phrolova.service" ]
grep -q '^start phrolova$' "$HOME/calls"
grep -q '^stop phrolova$' "$HOME/calls"
[ "$(grep -c '^restart phrolova$' "$HOME/calls")" = 2 ]
grep -q '^-u phrolova -f -n 200$' "$HOME/calls"
grep -q '^disable --now phrolova$' "$HOME/calls"
''')
