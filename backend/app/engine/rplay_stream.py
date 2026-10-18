"""Renew server-authorized IVS playlists without restarting HLS sequence tracking."""
import asyncio

from streamlink.exceptions import StreamError
from streamlink.stream.hls import HLSStream

from app.engine.recording_errors import RecordingError, classify_recording_error
from app.engine.rplay_live import RplayLiveEngine, media_allowed


class RplayWorker(HLSStream.__reader__.__worker__):
    def _fetch_playlist(self):
        def fetch():
            response = self.session.http.get(
                self.stream.url, exception=StreamError, retries=1,
                **self.reader.request_params)
            response.encoding = "utf-8"
            return response

        try:
            return fetch()
        except StreamError as error:
            if classify_recording_error(error).code != "authentication":
                raise
        # Obtain a new grant, not a guessed unsigned URL or another account.
        url, _, _ = asyncio.run(
            RplayLiveEngine().resolve_stream(self.stream.channel_id, self.stream.quality))
        if not media_allowed(url):
            raise RecordingError("rplay_stream", "알플레이 갱신 재생 주소가 허용되지 않습니다.")
        self.stream.args["url"] = url
        try:
            return fetch()
        except StreamError as error:
            if classify_recording_error(error).code == "authentication":
                raise RecordingError("rplay_authentication", "알플레이에서 갱신된 재생 주소를 거부했습니다. 계정의 시청 권한을 확인하세요.") from None
            raise


class RplayReader(HLSStream.__reader__):
    __worker__ = RplayWorker
    # Segment futures must fail the reader, not turn failed media into a silent
    # skipped segment while the UI keeps reporting an active recording.
    class __writer__(HLSStream.__reader__.__writer__):
        def _fetch(self, url, **request_params):
            if self.closed:
                return None
            try:
                return self.session.http.get(
                    url, timeout=self.timeout, retries=1, exception=StreamError,
                    **request_params)
            except StreamError:
                raise RecordingError(
                    "rplay_segment_connection",
                    "알플레이 영상 조각 수신이 실패했습니다. 새 재생 주소로 재연결합니다.",
                    retryable=True) from None

        def fetch(self, segment):
            return self._fetch(
                segment.uri, stream=self.stream_data,
                **self.create_request_params(segment.num, segment, False))

        def fetch_map(self, segment):
            return self._fetch(
                segment.map.uri, stream=False,
                **self.create_request_params(segment.num, segment.map, True))

        def _write_plain(self, segment, response):
            # Propagate mid-response disconnects to the guarded writer as well.
            self._write_into_buffer(self.iter_segment_content(segment, response))
            return True


class RplayHLSStream(HLSStream):
    __reader__ = RplayReader

    def __init__(self, session, url, channel_id, quality, **kwargs):
        super().__init__(session, url, **kwargs)
        self.channel_id = channel_id
        self.quality = quality
