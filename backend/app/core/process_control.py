"""POSIX 서버만 식별하여 종료한다. PID가 재사용되어도 다른 앱에는 신호를 보내지 않는다."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]


def identity(pid: int) -> dict[str, str] | None:
    if pid <= 1:
        return None
    values = []
    for field in ('lstart=', 'command='):
        try:
            result = subprocess.run(['ps', '-ww', '-p', str(pid), '-o', field], capture_output=True,
                                    text=True, timeout=3, env={**os.environ, 'LC_ALL': 'C', 'TZ': 'UTC'})
        except (OSError, subprocess.TimeoutExpired):
            return None
        value = result.stdout.strip()
        if result.returncode or not value:
            return None
        values.append(value)
    return {'started': values[0], 'signature': hashlib.sha256(values[1].encode()).hexdigest()}


def read_record(root: Path) -> dict | None:
    path = root / 'backend/data/server.pid'
    try:
        text = path.read_text(encoding='utf-8').strip()
        if text.isdecimal():
            return {'pid': int(text), 'legacy': True}
        value = json.loads(text)
        if isinstance(value, dict) and type(value.get('pid')) is int and value['pid'] > 1:
            return value
    except (OSError, ValueError):
        pass
    return None


def matches(record: dict, root: Path) -> bool:
    pid = record.get('pid', 0)
    if type(pid) is not int or pid <= 1:
        return False
    if record.get('legacy'):
        # 옛 Linux PID 파일은 /proc의 실제 작업 경로와 실행 인자를 모두 확인한다.
        proc = Path('/proc') / str(pid)
        try:
            args = proc.joinpath('cmdline').read_bytes().split(b'\0')
            return (proc.joinpath('cwd').resolve() == (root / 'backend').resolve()
                    and len(args) >= 2 and Path(os.fsdecode(args[1])).name == 'run.py'
                    and Path(os.fsdecode(args[0])).resolve() == Path(sys.executable).resolve())
        except (OSError, ValueError):
            return False
    current = identity(pid)
    return (record.get('root') == str(root.resolve()) and current is not None
            and current.get('started') == record.get('started')
            and current.get('signature') == record.get('signature'))


@contextmanager
def _server_lock(path: Path):
    import fcntl
    with path.open('a') as lock:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Another Phrolova server owns this installation.') from error
        yield


@contextmanager
def registered_server(root: Path = ROOT):
    root = root.resolve()
    path = root / 'backend/data/server.pid'
    path.parent.mkdir(parents=True, exist_ok=True)
    # PID 파일 교체와 중복 기동을 같은 설치본의 POSIX 잠금으로 묶는다.
    with _server_lock(path.with_suffix('.lock')):
        with _registered_server(root, path):
            yield


@contextmanager
def _registered_server(root: Path, path: Path):
    previous = read_record(root)
    if previous and matches(previous, root):
        raise RuntimeError(f"Phrolova is already running (PID {previous['pid']}).")
    current = identity(os.getpid())
    if current is None:
        raise RuntimeError('Cannot identify this process. Install ps/procps before starting Phrolova.')
    record = {**current, 'pid': os.getpid(), 'root': str(root), 'token': uuid.uuid4().hex}
    temp = path.with_name(f'.server-{record["token"]}.pid')
    try:
        with temp.open('x', encoding='utf-8') as stream:
            os.chmod(temp, 0o600)
            json.dump(record, stream)
        # 시작 중단으로 부분 JSON이 남지 않도록 완성된 임시 파일로 교체한다.
        temp.replace(path)
        yield
    finally:
        temp.unlink(missing_ok=True)
        if (read_record(root) or {}).get('token') == record['token']:
            path.unlink(missing_ok=True)


def stop(root: Path, timeout: float = 60) -> int:
    record = read_record(root)
    if not record or not matches(record, root):
        print('No matching Phrolova server is running.')
        return 0
    if record['pid'] == os.getpid():
        raise RuntimeError('Refusing to stop the management process itself.')
    try:
        os.kill(record['pid'], signal.SIGTERM)
    except ProcessLookupError:
        return 0
    deadline = time.monotonic() + timeout
    while matches(record, root):
        if time.monotonic() >= deadline:
            print('Shutdown is still in progress. Check the logs before restarting.', file=sys.stderr)
            return 1
        time.sleep(0.5)
    if read_record(root) == record:
        (root / 'backend/data/server.pid').unlink(missing_ok=True)
    print('Phrolova stopped.')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('stop', 'status'))
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--timeout', type=float, default=60)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'stop':
        return stop(root, max(0, args.timeout))
    record = read_record(root)
    active = record is not None and matches(record, root)
    print(f"Running (PID {record['pid']})" if active else 'Stopped')
    return 0 if active else 1


if __name__ == '__main__':
    raise SystemExit(main())
