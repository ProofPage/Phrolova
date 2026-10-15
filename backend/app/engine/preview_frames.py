"""Coalesced, bounded FFmpeg JPEG previews independent of live recordings."""
from __future__ import annotations
import asyncio
import time
import re
from app.engine.preview_transport import decode_preview, decode_preview_bytes
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
    text = redact_media_error(error).lower()
    response = getattr(error, 'response', None)
    status = getattr(response, 'status_code', None)
    def http_status(*codes):
        return status in codes or bool(re.search(
            r'\b(?:http(?:/\d(?:\.\d)?)?(?:\s+(?:error|status|code))?\s*[:=]?\s*(?:'+
            '|'.join(map(str,codes))+r')|(?:'+ '|'.join(map(str,codes))+r')\s+(?:client error|forbidden|unauthorized|not found|too many requests))\b', text))
    if 'certificate' in text or 'ssl' in text or 'tls' in text:
        return PreviewError('tls_certificate', '미리보기 TLS 인증서 검증에 실패했습니다. 시스템 시간과 CA 인증서 설정을 확인하세요.', retry_after=30)
    if isinstance(error, FileNotFoundError):
        return PreviewError('tool_missing', '미리보기 생성에 필요한 FFmpeg를 찾을 수 없습니다.', retryable=False)
    if http_status(401,403) or '로그인' in text or '쿠키' in text or '권한' in text:
        return PreviewError('authentication', '미리보기 인증 또는 시청 권한을 확인하세요.', status=403, retry_after=30)
    if http_status(429):
        return PreviewError('rate_limited', '미리보기 요청이 제한되었습니다. 잠시 후 다시 연결합니다.', status=429, retry_after=30)
    if http_status(404):
        return PreviewError('stream_expired', '미리보기 스트림 주소가 만료되었습니다. 다시 조회합니다.', retry_after=5)
    if '오프라인' in text or '종료' in text:
        return PreviewError('offline', '방송이 종료되었습니다.', status=409, retryable=False)
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)) or 'timeout' in text or 'timed out' in text:
        return PreviewError('timeout', '미리보기 연결 시간이 초과되었습니다. 다시 연결합니다.', retry_after=10)
    if http_status(*range(500,600)):
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

    async def finish_current_frame(self, key):
        task = self._inflight.get(key)
        if task and not task.done():
            try:
                # 이전 미리보기의 취소가 새 녹화 시작의 취소로 전파되지 않게 한다.
                settled = asyncio.gather(task, return_exceptions=True)
                await asyncio.wait_for(asyncio.shield(settled), timeout=20)
            except asyncio.CancelledError:
                raise
            except Exception:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        self.invalidate(key)

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
                if error.code in ('authentication', 'stream_expired') or platform == 'tiktok' and error.retryable:
                    for attr in ('_metadata_cache', '_cache', '_stream_cache'):
                        cache = getattr(engine, attr, None)
                        if isinstance(cache, dict): cache.pop(channel_id, None)
                raise error from None

    async def _generate(self, platform, channel_id, engine):
        buffered = None
        if platform == 'tiktok':
            from app.engine.tiktok_preview import capture_snapshot
            active, buffered = capture_snapshot(channel_id)
            if active:
                if buffered is None:
                    raise PreviewError('connecting', '녹화 원본에서 미리보기 화면을 준비하고 있습니다.', retry_after=2)
                url, headers, cookies = None, {}, None
            else:
                url, headers, cookies = await engine.resolve_preview_stream(channel_id)
        else:
            qualities = await engine.get_qualities(channel_id)
            known = [q for q in qualities if q.get('height')]
            full_hd = [q for q in known if q['height'] == 1080]
            selected = max(full_hd or known, key=lambda q: (q['height'], q.get('fps') or 0, q.get('bitrate') or 0)) if known else {'value': 'best'}
        if platform == 'cime':
            spec = await engine.resolve_stream_spec(channel_id, selected['value'])
            url, headers, cookies = spec.get('preview_url') or spec['url'], spec['headers'], spec.get('cookies')
        elif platform != 'tiktok':
            url, headers, cookies = await engine.resolve_stream(channel_id, selected['value'])
        if buffered is None:
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                raise PreviewError('unsupported', '미리보기 스트림 주소가 올바르지 않습니다.', retryable=False)
        safe_headers = {k:v for k,v in headers.items() if k.lower() not in ('cookie','authorization') and '\r' not in str(v) and '\n' not in str(v)}
        # FFmpeg only decodes stdin. Streamlink verifies every HTTPS playlist, segment and redirect.
        cmd = [get_settings().resolve_ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-i', 'pipe:0',
               '-map', '0:v:0', '-an', '-frames:v', '1', '-vf', "scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease",
               '-q:v', '3', '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1']
        if platform == 'tiktok':
            # FLV 헤더에 코덱 정보가 있으므로 기본 긴 탐색 때문에 라이브 입력이 끊기지 않게 한다.
            index = cmd.index('-i')
            cmd[index:index] = ['-f', 'flv', '-analyzeduration', '1000000', '-probesize', '2097152']
        if buffered is not None:
            data, stderr, code = await decode_preview_bytes(cmd, buffered)
        else:
            data, stderr, code = await decode_preview(cmd, url, safe_headers, platform, bool(cookies))
        if code or not data:
            raise preview_error(redact_media_error(stderr.decode(errors='replace')))
        width, height = jpeg_dimensions(data)
        return data, width, height

frame_previews = FramePreviewService()
