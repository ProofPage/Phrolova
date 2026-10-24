"""Executable health checks independent of discovery; never download at inspection time."""
import subprocess
import re
from app.core.config import get_settings

def check_media_tool(tool: str) -> dict:
    if tool == 'streamlink':
        # 녹화 엔진과 같은 Python 패키지를 검사해 별도 CLI 설치와 혼동하지 않는다.
        try:
            import streamlink
            session = streamlink.Streamlink()
            session.http.close()
            return {'available': True, 'path': streamlink.__file__, 'version': streamlink.__version__}
        except ImportError:
            return {'available': False, 'code': 'tool_missing', 'message': 'Streamlink를 찾을 수 없습니다.'}
        except Exception:
            return {'available': False, 'code': 'tool_failed', 'message': 'Streamlink 실행 확인에 실패했습니다.'}
    if tool == 'N_m3u8DL-RE':
        binary = get_settings().resolve_nm3u8dl_path()
        if not binary:
            return {'available': False, 'code': 'tool_missing', 'message': 'N_m3u8DL-RE를 찾을 수 없습니다. (선택 사항)'}
        try:
            result = subprocess.run([binary, '--version'], capture_output=True, timeout=5,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            output = result.stdout.decode(errors='replace').strip() or result.stderr.decode(errors='replace').strip()
            version = output.splitlines()[0] if output else '확인됨'
            return {'available': True, 'path': binary, 'version': version}
        except Exception as error:
            return {'available': False, 'code': 'tool_failed', 'path': binary, 'message': f'N_m3u8DL-RE 확인 실패: {error}'}
    if tool not in ('ffmpeg', 'ffprobe', 'yt-dlp', 'N_m3u8DL-RE'):
        raise ValueError('Unsupported tool')
    binary = None
    try:
        binary = get_settings().resolve_ytdlp_path(auto_download=False) if tool == 'yt-dlp' else getattr(get_settings(), f'resolve_{tool}_path')()
        result = subprocess.run([binary, '--version' if tool == 'yt-dlp' else '-version'], capture_output=True, timeout=5,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        output = result.stdout.decode(errors='replace').strip()
        version = output.splitlines()[0] if output else ''
        # yt-dlp는 도구 이름 없이 날짜 기반 버전만 출력한다. 다른 실행 파일의 응답과 구분한다.
        valid = bool(re.fullmatch(r'\d{4}\.\d{1,2}\.\d{1,2}[\w.+-]*', version, re.ASCII)) if tool == 'yt-dlp' else tool in output.lower()
        if result.returncode or not valid:
            detail = (result.stderr or result.stdout).decode(errors='replace').strip()[:500]
            return {'available': False, 'code': 'tool_failed', 'path': binary,
                    'message': f'{tool} 실행 확인 실패 · 종료 코드 {result.returncode} · {detail or "버전 응답 없음"}'}
        return {'available': True, 'path': binary, 'version': version}
    except FileNotFoundError:
        if tool == 'yt-dlp':
            try:
                import yt_dlp
                v = getattr(yt_dlp, '__version__', '')
                if v:
                    return {'available': True, 'path': getattr(yt_dlp, '__file__', 'python-module'), 'version': str(v)}
            except Exception:
                pass
        return {'available': False, 'code': 'tool_missing', 'message': f'{tool}를 찾을 수 없습니다.', **({'path': binary} if binary else {})}
    except subprocess.TimeoutExpired:
        return {'available': False, 'code': 'tool_failed', 'message': f'{tool} 실행 확인 시간(5초)을 초과했습니다. 실행 파일과 보안 프로그램을 확인하세요.', **({'path': binary} if binary else {})}
    except OSError as error:
        return {'available': False, 'code': 'tool_failed', 'message': f'{tool} 실행 실패 · {type(error).__name__}: {error}', **({'path': binary} if binary else {})}
