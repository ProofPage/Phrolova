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
        self.stream.url = url
        try:
            return fetch()
        except StreamError as error:
            if classify_recording_error(error).code == "authentication":
                raise RecordingError("rplay_authentication", "알플레이에서 갱신된 재생 주소를 거부했습니다. 계정의 시청 권한을 확인하세요.") from None
            raise


class RplayReader(HLSStream.__reader__):
    __worker__ = RplayWorker


class RplayHLSStream(HLSStream):
    __reader__ = RplayReader

    def __init__(self, session, url, channel_id, quality, **kwargs):
        super().__init__(session, url, **kwargs)
        self.channel_id = channel_id
        self.quality = quality
