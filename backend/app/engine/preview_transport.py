"""Isolated, verified HLS snapshot input for FFmpeg builds without nested TLS CA propagation."""
from __future__ import annotations
import asyncio
import os
import ssl
import tempfile
import logging
from functools import lru_cache
from pathlib import Path
import certifi
from streamlink import Streamlink
from streamlink.stream.hls import HLSStream
from app.core.config import resolve_data_dir
from app.core.logger import logger
from app.engine.platform_auth import platform_cookie_jar, redact_media_error

class SafeMediaLogFilter(logging.Filter):
    def filter(self, record):
        record.msg = redact_media_error(record.getMessage())
        record.args = ()
        return True

# Streamlink workers report failed requests separately from their byte reader.
# Remove signed URLs at that reporting boundary, including requests exceptions.
_stream_logger = logging.getLogger('streamlink.stream.hls')
if not any(isinstance(item, SafeMediaLogFilter) for item in _stream_logger.filters):
    _stream_logger.addFilter(SafeMediaLogFilter())

@lru_cache(maxsize=1)
def preview_ca_bundle() -> str:
    # Respect configured trust and combine Mozilla roots with the OS store.
    configured = os.environ.get('SSL_CERT_FILE')
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=configured if configured and Path(configured).is_file() else certifi.where())
    certificates = context.get_ca_certs(binary_form=True)
    destination = resolve_data_dir() / 'preview-ca.pem'
    fd, temporary = tempfile.mkstemp(prefix='preview-ca-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as output:
            for certificate in certificates:
                output.write(ssl.DER_cert_to_PEM_cert(certificate))
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return str(destination)

async def decode_preview(cmd: list[str], url: str, headers: dict, platform: str, authenticated: bool) -> tuple[bytes, bytes, int]:
    session = Streamlink()
    from app.engine.cime import CimeUhdAuth
    from app.engine.streamlink_support import configure_streamlink_session, guarded_hls_stream
    if platform == "cime":
        session.http.auth = CimeUhdAuth.for_url(url, "https://ci.me/")
    configure_streamlink_session(session, platform, url)
    session.set_option('http-timeout', 5)
    session.set_option('stream-timeout', 8)
    session.set_option('hls-live-edge', 1)
    session.set_option('hls-playlist-reload-attempts', 2)
    session.set_option('stream-segment-attempts', 2)
    session.set_option('stream-segment-threads', 1)
    session.http.verify = preview_ca_bundle()
    session.http.headers.update(headers)
    transport_errors = []
    request = session.http.request
    def checked_request(*args, **kwargs):
        try:
            return request(*args, **kwargs)
        except Exception as error:
            transport_errors.append(error)
            del transport_errors[:-4]
            raise
    session.http.request = checked_request
    if authenticated:
        # CookieJar scopes every playlist/segment/redirect to its actual domain.
        session.http.cookies.update(platform_cookie_jar(platform))
    if platform == 'tiktok':
        from app.engine.tiktok_transport import FLVPacketReader, open_flv_input
        session.http.cookies.update(platform_cookie_jar('tiktok'))
        from types import SimpleNamespace
        source = SimpleNamespace(open=lambda:open_flv_input(session,url))
    else:
        source = guarded_hls_stream(HLSStream)(session, url)
    opening = asyncio.create_task(asyncio.to_thread(source.open))
    reader = None
    process = None
    tasks = []
    try:
        # Shield ensures a cancelled open still closes its reader when the thread returns.
        reader = await asyncio.shield(opening)
        if platform == 'tiktok':
            reader = FLVPacketReader(reader)
        process = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0))
        async def feed():
            try:
                while process.returncode is None:
                    data = await asyncio.to_thread(reader.read, 64 * 1024)
                    if not data: break
                    process.stdin.write(data)
                    await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()
        async def bounded(pipe, limit):
            output = bytearray()
            while data := await pipe.read(65536):
                output.extend(data)
                if len(output) > limit:
                    raise RuntimeError('미리보기 출력 크기 제한을 초과했습니다.')
            return bytes(output)
        tasks = [asyncio.create_task(feed()), asyncio.create_task(bounded(process.stdout, 8 * 1024 * 1024)),
                 asyncio.create_task(bounded(process.stderr, 65536))]
        done, _ = await asyncio.wait([tasks[0], tasks[1]], return_when=asyncio.FIRST_COMPLETED)
        # Propagate transport failures instead of replacing them with decoder EOF errors.
        for task in done:
            if task.exception(): raise task.exception()
        await process.wait()
        if process.returncode and transport_errors:
            raise transport_errors[-1]
        output, stderr = await tasks[1], await tasks[2]
        source_error = getattr(reader, 'error', None)
        if not output and isinstance(source_error, Exception):
            raise source_error
        return output, stderr, process.returncode
    finally:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        if process:
            if process.stdin:
                process.stdin.close()
                try:
                    await asyncio.wait_for(process.stdin.wait_closed(), 1)
                except (AttributeError, asyncio.TimeoutError, BrokenPipeError, ConnectionResetError):
                    pass
            logger.debug("미리보기 FFmpeg 종료 · 종료코드=%s", process.returncode)
        if reader:
            await asyncio.to_thread(reader.close)
        elif not opening.done():
            def close_late(task):
                try: task.result().close()
                except BaseException: pass
            opening.add_done_callback(close_late)
        else:
            try: opening.result().close()
            except BaseException: pass
        for task in tasks:
            if not task.done(): task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        session.http.close()


async def decode_preview_bytes(cmd, data):
    process = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        creationflags=getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0))
    try:
        output, stderr = await asyncio.wait_for(process.communicate(data), timeout=12)
        if len(output) > 8 * 1024 * 1024:
            raise RuntimeError('미리보기 출력 크기 제한을 초과했습니다.')
        return output, stderr[-65536:], process.returncode
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
