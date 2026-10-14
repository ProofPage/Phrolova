"""Streamlink의 TikTok FLV 입력을 재인코딩 없이 TS 파이프로 전달한다."""
from __future__ import annotations

import threading
import subprocess

from streamlink.stream.ffmpegmux import FFMPEGMuxer

from app.core.config import get_settings
from app.engine.recording_errors import RecordingError


class _TikTokMuxer(FFMPEGMuxer):
    def open(self):
        # 생성 실패 시 파이프 대기 스레드가 남지 않도록 프로세스를 먼저 만든다.
        self.process = subprocess.Popen(self._cmd, stdout=subprocess.PIPE,
            stdin=subprocess.DEVNULL, stderr=self.errorlog,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for thread in self.pipe_threads:
            thread.daemon = True
            thread.start()
        return self


class TikTokFLVStream:
    def __init__(self, session, url):
        self.session, self.url = session, url

    def open(self):
        from streamlink.stream.http import HTTPStream
        source = HTTPStream(self.session, self.url).open()
        muxer = None
        try:
            # FFmpeg에는 인증 URL 대신 Streamlink가 검증한 로컬 파이프만 전달한다.
            self.session.set_option('ffmpeg-ffmpeg', get_settings().resolve_ffmpeg_path())
            muxer = _TikTokMuxer(self.session, source, format='mpegts', loglevel='error',
                maps=['0:v:0?', '0:a:0?'], vcodec='copy', acodec='copy')
            return TikTokMuxedReader(muxer.open(), source)
        except BaseException:
            source.close()
            if muxer:
                for pipe in muxer.pipes:
                    pipe.close()
            raise


class TikTokMuxedReader:
    def __init__(self, muxer, source):
        self.muxer, self.source = muxer, source
        self.closed = False
        self.stopping = False
        self._close_lock = threading.Lock()

    def read(self, size=-1):
        data = self.muxer.read(size)
        if not data and self.muxer.process.wait(timeout=10) != 0:
            raise RecordingError('tiktok_remux', 'TikTok FLV 입력을 TS로 변환하지 못했습니다. 원본 코덱과 연결 상태를 확인하세요.', retryable=True)
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
                if self.muxer.process:
                    self.muxer.process.wait(timeout=10)
