"""Coalesced, bounded FFmpeg JPEG previews independent of live recordings."""
from __future__ import annotations
import asyncio
import time
from urllib.parse import urlsplit
from app.core.config import get_settings
from app.engine.platform_auth import platform_cookie_jar, redact_media_error
from app.core.logger import logger

def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    if not data.startswith(b'\xff\xd8'): raise ValueError('미리보기 이미지 형식이 올바르지 않습니다.')
    offset = 2
    while offset + 4 < len(data):
        if data[offset] != 255: raise ValueError('미리보기 이미지 정보를 읽지 못했습니다.')
        marker = data[offset + 1]
        offset += 2
        if marker in (0xD8, 0xD9): continue
        length = int.from_bytes(data[offset:offset+2], 'big')
        if length < 2 or offset + length > len(data): break
        if marker in (0xC0, 0xC1, 0xC2):
            height = int.from_bytes(data[offset+3:offset+5], 'big')
            width = int.from_bytes(data[offset+5:offset+7], 'big')
            if width and height: return width, height
        offset += length
    raise ValueError('미리보기 해상도를 읽지 못했습니다.')

class FramePreviewService:
    def __init__(self):
        self._cache: dict[str, tuple[float, bytes, int, int]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._semaphore = asyncio.Semaphore(2)

    async def get_frame(self, key: str, platform: str, channel_id: str, engine) -> tuple[bytes, int, int]:
        now = time.monotonic()
        for old in list(self._cache):
            if now - self._cache[old][0] > 15: self._cache.pop(old, None)
        async with self._locks.setdefault(key, asyncio.Lock()):
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < 5: return cached[1:]
            async with self._semaphore:
                qualities = await engine.get_qualities(channel_id)
                known = [q for q in qualities if q.get('height')]
                full_hd = [q for q in known if q['height'] == 1080]
                selected = max(full_hd or known, key=lambda q: (q['height'], q.get('fps') or 0, q.get('bitrate') or 0)) if known else {'value': 'best'}
                video_index = None
                if platform == 'cime':
                    spec = await engine.resolve_stream_spec(channel_id, selected['value'])
                    url, headers = spec['url'], spec['headers']
                    authenticated = bool(spec.get('cookies'))
                    video_index = spec.get('video_index')
                else:
                    url, headers, stream_cookies = await engine.resolve_stream(channel_id, selected['value'])
                    authenticated = bool(stream_cookies)
                parsed = urlsplit(url)
                if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError('미리보기 스트림 주소가 올바르지 않습니다.')
                cmd = [get_settings().resolve_ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-rw_timeout', '15000000']
                safe_headers = {k:v for k,v in headers.items() if k.lower() not in ('cookie','authorization') and '\r' not in str(v) and '\n' not in str(v)}
                if safe_headers: cmd += ['-headers', ''.join(f'{k}: {v}\r\n' for k,v in safe_headers.items())]
                cookies = [c for c in platform_cookie_jar(platform) if authenticated and (parsed.hostname == c.domain.lstrip('.') or parsed.hostname.endswith('.' + c.domain.lstrip('.')))]
                if cookies:
                    cmd += ['-cookies', '\n'.join(f'{c.name}={c.value}; path={c.path}; domain={c.domain};' for c in cookies)]
                cmd += ['-i', url, '-map', f'0:v:{video_index or 0}', '-an', '-frames:v', '1', '-vf', "scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease", '-q:v', '3', '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1']
                process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                try:
                    data, stderr = await asyncio.wait_for(process.communicate(), timeout=25)
                except BaseException:
                    if process.returncode is None: process.kill()
                    await process.communicate()
                    raise
                if process.returncode or not data or len(data) > 8 * 1024 * 1024:
                    logger.warning(f'[{key}] 미리보기 프레임 생성 실패 (code={process.returncode}): {redact_media_error(stderr.decode(errors="replace"))}')
                    raise RuntimeError('미리보기 프레임을 만들지 못했습니다.')
                width, height = jpeg_dimensions(data)
                while self._cache and (len(self._cache) >= 16 or sum(len(v[1]) for v in self._cache.values()) + len(data) > 32 * 1024 * 1024):
                    self._cache.pop(next(iter(self._cache)))
                self._cache[key] = (time.monotonic(), data, width, height)
                return data, width, height

frame_previews = FramePreviewService()
