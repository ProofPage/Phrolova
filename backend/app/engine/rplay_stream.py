"""Renew server-authorized IVS playlists without restarting HLS sequence tracking."""
import asyncio
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from streamlink.exceptions import StreamError
from streamlink.stream.hls import HLSStream

from app.engine.recording_errors import RecordingError, classify_recording_error
from app.engine.rplay_live import RplayLiveEngine, media_allowed


class RplayWorker(HLSStream.__reader__.__worker__):
    def _fetch_playlist(self):
        attempts = max(1, int(getattr(self, "reload_attempts", 1)))
        def fetch():
            response = self.session.http.get(
                self.stream.url, exception=StreamError, retries=attempts,
                **self.reader.request_params)
            response.encoding = "utf-8"
            return response

        try:
            return fetch()
        except StreamError as error:
            err_text = str(error)
            is_5xx = any(code in err_text for code in ("500", "502", "503", "504"))
            if classify_recording_error(error).code != "authentication" and not is_5xx:
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
            stream_obj = getattr(getattr(self, "reader", None), "stream", None)
            base_url = getattr(stream_obj, "url", "")
            base_query = parse_qsl(urlsplit(base_url).query)
            if base_query:
                parts = urlsplit(url)
                current_query = dict(parse_qsl(parts.query))
                for k, v in base_query:
                    if k not in current_query:
                        current_query[k] = v
                url = urlunsplit(parts._replace(query=urlencode(current_query)))
            attempts = (
                int(self.session.options.get("stream-segment-attempts") or 3)
                if hasattr(self.session, "options")
                else 1
            )
            try:
                return self.session.http.get(
                    url, timeout=self.timeout, retries=attempts, exception=StreamError,
                    **request_params)
            except StreamError as err:
                if stream_obj and getattr(stream_obj, "channel_id", None):
                    try:
                        new_url, _, _ = asyncio.run(
                            RplayLiveEngine().resolve_stream(stream_obj.channel_id, stream_obj.quality)
                        )
                        if media_allowed(new_url):
                            stream_obj.args["url"] = new_url
                            new_query = dict(parse_qsl(urlsplit(new_url).query))
                            parts = urlsplit(url)
                            current_query = dict(parse_qsl(parts.query))
                            current_query.update(new_query)
                            retry_url = urlunsplit(parts._replace(query=urlencode(current_query)))
                            return self.session.http.get(
                                retry_url, timeout=self.timeout, retries=attempts, exception=StreamError,
                                **request_params)
                    except Exception:
                        pass
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
