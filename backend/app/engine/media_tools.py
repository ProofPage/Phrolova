"""Executable health checks independent of discovery; never download at inspection time."""
import subprocess
from app.core.config import get_settings

def check_media_tool(tool: str) -> dict:
    if tool not in ('ffmpeg', 'ffprobe'):
        raise ValueError('Unsupported tool')
    try:
        binary = getattr(get_settings(), f'resolve_{tool}_path')()
        result = subprocess.run([binary, '-version'], capture_output=True, timeout=5,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or tool not in result.stdout.decode(errors='replace').lower():
            return {'available': False, 'code': 'tool_failed', 'message': f'{tool} 실행 확인에 실패했습니다.'}
        return {'available': True, 'path': binary, 'version': result.stdout.decode(errors='replace').splitlines()[0]}
    except FileNotFoundError:
        return {'available': False, 'code': 'tool_missing', 'message': f'{tool}를 찾을 수 없습니다.'}
    except (OSError, subprocess.TimeoutExpired):
        return {'available': False, 'code': 'tool_failed', 'message': f'{tool}를 실행하지 못했습니다.'}
