"""Streamlink의 TikTok FLV 입력을 재인코딩 없이 TS 파이프로 전달한다."""
from __future__ import annotations

import threading
import subprocess

from streamlink.stream.ffmpegmux import FFMPEGMuxer

from app.core.config import get_settings
from app.engine.recording_errors import RecordingError
from app.engine.platform_auth import redact_media_error


def _closing_chunks(chunks, stopping):
    try:
        yield from chunks
    except Exception as error:
        if not stopping.is_set():
            raise OSError(str(error)) from error


class _ClosingReader:
    def __init__(self, reader, response, stopping=None):
        self.reader, self.response = reader, response
        self.closed = False
        self.lock = threading.Lock()
        self.stopping = stopping or threading.Event()

    def read(self, size=-1):
        return self.reader.read(size)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.stopping.set()
            try:
                # HTTPStream의 반복자 종료만으로는 소비 중인 응답 소켓이 바로 닫히지 않는다.
                self.response.close()
            finally:
                self.reader.close()


def open_flv_input(session, url):
    from streamlink.stream.http import HTTPStream
    responses = []
    stopping = threading.Event()
    request = session.http.request
    def remember(*args, **kwargs):
        response = request(*args, **kwargs)
        content = response.iter_content
        # 닫히는 소켓을 읽던 urllib3 반복자의 예외가 백그라운드 스레드에 남지 않게 한다.
        response.iter_content = lambda *a,**kw: _closing_chunks(content(*a,**kw),stopping)
        responses.append(response)
        return response
    session.http.request = remember
    try:
        reader = HTTPStream(session, url).open()
    finally:
        session.http.request = request
    return _ClosingReader(reader,responses[-1],stopping) if responses else reader


class FLVPacketReader:
    """완성된 FLV 태그만 전달해 연결 종료가 NAL 패킷 손상으로 번지지 않게 한다."""
    def __init__(self, source, observer=None):
        self.source = source
        self.observer = observer
        self.pending = bytearray()
        self.header_read = False
        self.eof = False
        self.stopping = False
        self.error = None

    def _exact(self, size, *, optional=False):
        data = bytearray()
        try:
            while len(data) < size:
                part = self.source.read(min(size-len(data), 65536))
                if not part:
                    self.eof = True
                    if not self.stopping and (data or not optional):
                        self.error = RecordingError('tiktok_stream_truncated',
                            'TikTok 원본 수신이 영상 패킷 도중 끊겼습니다. 저장된 구간을 보관하고 재연결합니다.', retryable=True)
                    return b''
                data.extend(part)
        except Exception as error:
            self.eof = True
            if not self.stopping:
                self.error = RecordingError('tiktok_connection',
                    'TikTok 원본 수신이 중단되었습니다. 재연결합니다. '+redact_media_error(error), retryable=True)
            return b''
        return bytes(data)

    def read(self, size=-1):
        if size == 0:
            return b''
        if not self.pending and not self.eof:
            if not self.header_read:
                header = self._exact(9)
                if not header:
                    return b''
                offset = int.from_bytes(header[5:9], 'big')
                if header[:4] != b'FLV\x01' or not 9 <= offset <= 4096:
                    self.error = RecordingError('tiktok_container', 'TikTok 원본이 정상 FLV 영상 형식이 아닙니다.')
                    self.eof = True
                    return b''
                tail = self._exact(offset-9+4)
                if not tail:
                    return b''
                self.pending.extend(header+tail)
                self.header_read = True
                if self.observer:
                    self.observer.feed(header+tail, header=True)
            else:
                header = self._exact(11, optional=True)
                if not header:
                    return b''
                length = int.from_bytes(header[1:4], 'big')
                packet = self._exact(length+4)
                if not packet:
                    return b''
                if int.from_bytes(packet[-4:], 'big') != length+11:
                    self.error = RecordingError('tiktok_container', 'TikTok FLV 패킷의 길이 정보가 맞지 않습니다.', retryable=True)
                    self.eof = True
                    return b''
                self.pending.extend(header+packet)
                if self.observer:
                    self.observer.feed(header+packet)
        count = len(self.pending) if size < 0 else min(size, len(self.pending))
        data = bytes(self.pending[:count])
        del self.pending[:count]
        return data

    def request_stop(self):
        self.stopping = True
        self.source.close()

    def close(self):
        self.request_stop()

    @property
    def closed(self):
        return self.stopping


class _TikTokMuxer(FFMPEGMuxer):
    def open(self):
        # 생성 실패 시 파이프 대기 스레드가 남지 않도록 프로세스를 먼저 만든다.
        self.process = subprocess.Popen(self._cmd, stdout=subprocess.PIPE,
            stdin=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self._stderr_tail = bytearray()
        def collect():
            while chunk := self.process.stderr.read(4096):
                self._stderr_tail.extend(chunk)
                del self._stderr_tail[:-8192]
        self._stderr_thread = threading.Thread(target=collect, daemon=True)
        self._stderr_thread.start()
        for thread in self.pipe_threads:
            thread.daemon = True
            thread.start()
        return self

    def diagnostics(self):
        self._stderr_thread.join(timeout=1)
        return redact_media_error(self._stderr_tail.decode('utf-8', errors='replace'))[-2000:]

    def close(self):
        try:
            super().close()
        finally:
            thread = getattr(self, '_stderr_thread', None)
            if thread:
                thread.join(timeout=2)
            if self.process and self.process.stderr:
                self.process.stderr.close()
            if self.process:
                from app.core.logger import logger
                logger.debug("TikTok FFmpeg 종료 · 종료코드=%s", self.process.returncode)


class TikTokFLVStream:
    def __init__(self, session, url, channel_id=None, capture=None):
        self.session, self.url = session, url
        self.channel_id = channel_id
        self.capture = capture

    def open(self):
        from app.engine.tiktok_preview import register_capture
        capture = self.capture
        source = None
        muxer = None
        try:
            raw = open_flv_input(self.session, self.url)
            capture = capture or (register_capture(self.channel_id) if self.channel_id else None)
            source = FLVPacketReader(raw, observer=capture)
            # FFmpeg에는 인증 URL 대신 Streamlink가 검증한 로컬 파이프만 전달한다.
            self.session.set_option('ffmpeg-ffmpeg', get_settings().resolve_ffmpeg_path())
            muxer = _TikTokMuxer(self.session, source, format='mpegts', loglevel='error',
                maps=['0:v:0?', '0:a:0?'], vcodec='copy', acodec='copy')
            return TikTokMuxedReader(muxer.open(), source, capture=capture)
        except BaseException:
            if source:
                source.close()
            if capture:
                capture.close()
            if muxer:
                for pipe in muxer.pipes:
                    pipe.close()
            raise


class TikTokMuxedReader:
    def __init__(self, muxer, source, capture=None):
        self.muxer, self.source = muxer, source
        self.capture = capture
        self.closed = False
        self.stopping = False
        self._close_lock = threading.Lock()

    def read(self, size=-1):
        data = self.muxer.read(size)
        if not data:
            code = self.muxer.process.wait(timeout=10)
            source_error = getattr(self.source, 'error', None)
            if isinstance(source_error, RecordingError) and not self.stopping:
                raise source_error
            if code != 0 and not self.stopping:
                detail = self.muxer.diagnostics() if isinstance(self.muxer, _TikTokMuxer) else ''
                raise RecordingError('tiktok_remux',
                    f'TikTok FLV 입력을 TS로 변환하지 못했습니다. FFmpeg 종료 코드: {code}. '+detail, retryable=True)
        return data

    def request_stop(self):
        # 입력을 먼저 닫고 stdout을 끝까지 읽어 FFmpeg가 받아 둔 패킷을 비운다.
        self.stopping = True
        self.source.close()

    def close(self):
        with self._close_lock:
            if self.closed:
                return
            self.closed = True
            try:
                self.muxer.close()
            finally:
                try:
                    if self.muxer.process:
                        self.muxer.process.wait(timeout=10)
                finally:
                    if self.capture:
                        self.capture.close()
