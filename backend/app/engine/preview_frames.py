"""Coalesced, bounded FFmpeg JPEG previews independent of live recordings."""
from __future__ import annotations
import asyncio
import time
import re
from app.engine.preview_transport import decode_preview
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

class PreviewError(RuntimeError):
    def __init__(self, code, message, status=502, retryable=True, retry_after=5):
        super().__init__(message)
        self.code, self.status, self.retryable, self.retry_after = code, status, retryable, retry_after


def preview_error(error):
    text = str(error).lower()
    if 'certificate' in text or 'ssl' in text or 'tls' in text:
        return PreviewError('tls_certificate', '미리보기 TLS 인증서 검증에 실패했습니다. 시스템 시간과 CA 인증서 설정을 확인하세요.', retry_after=30)
    if isinstance(error, FileNotFoundError):
        return PreviewError('tool_missing', '미리보기 생성에 필요한 FFmpeg를 찾을 수 없습니다.', retryable=False)
    if '401' in text or '403' in text or '로그인' in text or '쿠키' in text or '권한' in text:
        return PreviewError('authentication', '미리보기 인증 또는 시청 권한을 확인하세요.', status=403, retry_after=30)
    if '429' in text:
        return PreviewError('rate_limited', '미리보기 요청이 제한되었습니다. 잠시 후 다시 연결합니다.', status=429, retry_after=30)
    if '404' in text:
        return PreviewError('stream_expired', '미리보기 스트림 주소가 만료되었습니다. 다시 조회합니다.', retry_after=5)
    if '오프라인' in text or '종료' in text:
        return PreviewError('offline', '방송이 종료되었습니다.', status=409, retryable=False)
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)) or 'timeout' in text or 'timed out' in text:
        return PreviewError('timeout', '미리보기 연결 시간이 초과되었습니다. 다시 연결합니다.', retry_after=10)
    if re.search(r'\b5\d\d\b', text):
        return PreviewError('upstream_error', '미리보기 CDN에 일시적인 오류가 발생했습니다.', retry_after=10)
    return PreviewError('connection', '미리보기 연결에 실패했습니다. 다시 연결합니다.', retry_after=5)


class FramePreviewService:
    def __init__(self):
        self._cache = {}
        self._locks = {}
        self._failures = {}
        self._inflight = {}
        self._semaphore = asyncio.Semaphore(2)

    def invalidate(self, key):
        self._cache.pop(key, None)
        self._failures.pop(key, None)
        task = self._inflight.get(key)
        if task and not task.done(): task.cancel()

    async def get_frame(self, key, platform, channel_id, engine, *, force=False):
        now = time.monotonic()
        for old in list(self._cache):
            if now - self._cache[old][0] > 15: self._cache.pop(old, None)
        # Completed idle channel entries cannot accumulate for the lifetime of the server.
        for old, lock in list(self._locks.items()):
            if old != key and not lock.locked() and not getattr(lock, '_waiters', None):
                self._locks.pop(old, None)
        async with self._locks.setdefault(key, asyncio.Lock()):
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < 5: return cached[1:]
            failed = self._failures.get(key)
            if failed:
                error, until, count = failed
                if time.monotonic() < until and not (force and time.monotonic() >= until - error.retry_after + 2):
                    raise error
            try:
                async with self._semaphore:
                    generation = asyncio.create_task(self._generate(platform, channel_id, engine))
                    self._inflight[key] = generation
                    try:
                        result = await asyncio.wait_for(generation, timeout=30)
                    finally:
                        self._inflight.pop(key, None)
                self._failures.pop(key, None)
                data, width, height = result
                while self._cache and (len(self._cache) >= 16 or sum(len(v[1]) for v in self._cache.values()) + len(data) > 32 * 1024 * 1024):
                    self._cache.pop(next(iter(self._cache)))
                self._cache[key] = (time.monotonic(), data, width, height)
                return result
            except asyncio.CancelledError:
                raise
            except Exception as cause:
                error = cause if isinstance(cause, PreviewError) else preview_error(cause)
                count = failed[2] + 1 if failed else 1
                error.retry_after = min(60, error.retry_after * (2 ** min(count - 1, 3)))
                self._failures[key] = (error, time.monotonic() + error.retry_after, count)
                while len(self._failures) > 128: self._failures.pop(next(iter(self._failures)))
                # Coalesced failures do not spawn processes or repeatedly log raw URLs.
                logger.warning(f'[{key}] preview error_code={error.code} retryable={error.retryable} count={count}: {error}')
                if error.code in ('authentication', 'stream_expired'):
                    for attr in ('_metadata_cache', '_cache'):
                        cache = getattr(engine, attr, None)
                        if isinstance(cache, dict): cache.pop(channel_id, None)
                raise error from None

    async def _generate(self, platform, channel_id, engine):
        qualities = await engine.get_qualities(channel_id)
        known = [q for q in qualities if q.get('height')]
        full_hd = [q for q in known if q['height'] == 1080]
        selected = max(full_hd or known, key=lambda q: (q['height'], q.get('fps') or 0, q.get('bitrate') or 0)) if known else {'value': 'best'}
        if platform == 'cime':
            spec = await engine.resolve_stream_spec(channel_id, selected['value'])
            url, headers, cookies = spec.get('preview_url') or spec['url'], spec['headers'], spec.get('cookies')
        else:
            url, headers, cookies = await engine.resolve_stream(channel_id, selected['value'])
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise PreviewError('unsupported', '미리보기 스트림 주소가 올바르지 않습니다.', retryable=False)
        safe_headers = {k:v for k,v in headers.items() if k.lower() not in ('cookie','authorization') and '\r' not in str(v) and '\n' not in str(v)}
        # FFmpeg only decodes stdin. Streamlink verifies every HTTPS playlist, segment and redirect.
        cmd = [get_settings().resolve_ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-i', 'pipe:0',
               '-map', '0:v:0', '-an', '-frames:v', '1', '-vf', "scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease",
               '-q:v', '3', '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1']
        data, stderr, code = await decode_preview(cmd, url, safe_headers, platform, bool(cookies))
        if code or not data:
            raise preview_error(redact_media_error(stderr.decode(errors='replace')))
        width, height = jpeg_dimensions(data)
        return data, width, height

frame_previews = FramePreviewService()
