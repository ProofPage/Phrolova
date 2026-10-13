"""서버 운영체제의 파일 관리자를 열고 헤드리스 환경에서는 경로만 제공한다."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def reveal(path: Path, *, select_file: bool = False) -> bool:
    path = path.resolve()
    if sys.platform == 'win32':
        if select_file:
            subprocess.run(['explorer', '/select,', str(path)], check=False)
        else:
            os.startfile(str(path))
        return True
    if sys.platform == 'darwin':
        command = shutil.which('open')
        args = [command, '-R', str(path)] if select_file else [command, str(path)]
    else:
        # Native Android에는 Linux 파일 관리자를 실행하지 않는다.
        native_termux = (os.environ.get('PHROLOVA_ENVIRONMENT') != 'termux-proot'
                        and (bool(os.environ.get('TERMUX_VERSION')) or os.environ.get('PREFIX', '').startswith('/data/data/')))
        if native_termux or not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
            return False
        command = shutil.which('xdg-open')
        args = [command, str(path.parent if select_file else path)]
    if not command:
        return False
    try:
        result = subprocess.run(args, check=False, timeout=10,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
