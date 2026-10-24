"""Renew server-authorized IVS playlists without restarting HLS sequence tracking."""
import asyncio
import re
import threading
from dataclasses import replace
from itertools import chain
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from streamlink.exceptions import StreamError
from streamlink.stream.hls import HLSStream

from app.engine.recording_errors import RecordingError, classify_recording_error
from app.engine.rplay_live import RplayLiveEngine, media_allowed
from app.engine.capture_boundaries import CaptureBoundaryStream, CaptureBoundaryWriter


def segment_url(url, playlist, *, renew=False):
    """Never copy a viewer grant to another origin or an untrusted segment."""
    if not media_allowed(url):
        raise RecordingError("rplay_stream", "알플레이 영상 조각 주소가 허용되지 않습니다.")
    target, source = urlsplit(url), urlsplit(playlist)
    if (target.scheme, target.netloc) != (source.scheme, source.netloc):
        return url
    query = dict(parse_qsl(target.query, keep_blank_values=True))
    for key, value in parse_qsl(source.query, keep_blank_values=True):
        if renew or key not in query:
            query[key] = value
    return urlunsplit(target._replace(query=urlencode(query)))


class RplayWorker(HLSStream.__reader__.__worker__):
    def _fetch_playlist(self):
        attempts = max(1, int(getattr(self, "reload_attempts", 1)))
        revision = self.stream.renewal_revision
        def fetch():
            response = self.session.http.get(
                self.stream.url, exception=StreamError, retries=attempts,
                **self.reader.request_params)
            response.encoding = "utf-8"
            return response

        try:
            return fetch()
        except StreamError as error:
            if not refreshable_playlist_failure(error):
                raise
        # Obtain a new grant, not a guessed unsigned URL or another account.
        self.stream.renew(revision)
        try:
            return fetch()
        except StreamError as error:
            if not re.search(r"(?<!\d)(?:401|403)(?!\d)", str(error)):
                raise
            raise RecordingError("rplay_authentication", "알플레이에서 갱신된 재생 주소를 거부했습니다. 계정의 시청 권한을 확인하세요.") from None


def refreshable_playlist_failure(error):
    """A playlist can fetch yet no longer serve this stream, not only refuse it.

    Retired BytePlus playlists answer 404, 403 or a body without segments after
    a download-affecting error such as a disk failure. Refreshing the grant
    restarts the download on the current broadcast instead of reusing the
    address the previous session was given.
    """
    return bool(re.search(r"(?<!\d)(?:401|403|404|410|500|502|503|504)(?!\d)", str(error)))


class RplayReader(HLSStream.__reader__):
    __worker__ = RplayWorker

    # Segment futures must fail the reader, not turn failed media into a silent
    # skipped segment while the UI keeps reporting an active recording.
    class __writer__(CaptureBoundaryWriter, HLSStream.__reader__.__writer__):
        def write(self, segment, result, *data):
            if not self.should_filter_segment(segment):
                resumed = self.reader.is_paused() and self.reader.buffer.written_once
                if segment.discontinuity or resumed:
                    stream = self.stream
                    if stream._capture_boundary_sequence != segment.num:
                        stream._capture_boundary_sequence = segment.num
                        if stream._written:
                            with stream._boundary_lock:
                                stream._boundaries.append((stream._written, "stream_discontinuity"))
                    if segment.discontinuity:
                        segment = replace(segment, discontinuity=False)
                    if self.reader.is_paused():
                        self.reader.resume()
            return super().write(segment, result, *data)

        def _fetch(self, url, **request_params):
            if self.closed:
                return None
            stream_obj = getattr(getattr(self, "reader", None), "stream", None)
            base_url = getattr(stream_obj, "url", "")
            revision = stream_obj.renewal_revision if stream_obj is not None else 0
            url = segment_url(url, base_url)
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
                        new_url = stream_obj.renew(revision)
                        if urlsplit(new_url).netloc != urlsplit(base_url).netloc:
                            raise RecordingError(
                                "rplay_segment_connection",
                                "알플레이 CDN이 변경되어 새 재생 목록으로 재연결합니다.",
                                retryable=True)
                        retry_url = segment_url(url, new_url, renew=True)
                        return self.session.http.get(
                            retry_url, timeout=self.timeout, retries=attempts, exception=StreamError,
                            **request_params)
                    except RecordingError:
                        raise
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
            content = iter(self.iter_segment_content(segment, response))
            first = next((chunk for chunk in content if chunk), None)
            if first is None:
                raise RecordingError(
                    "rplay_segment_connection",
                    "알플레이 영상 조각이 비어 있습니다. 새 재생 주소로 재연결합니다.",
                    retryable=True)
            self._write_into_buffer(chain((first,), content))
            return True


class RplayHLSStream(CaptureBoundaryStream, HLSStream):
    __reader__ = RplayReader

    def __init__(self, session, url, channel_id, quality, **kwargs):
        super().__init__(session, url, **kwargs)
        self.channel_id = channel_id
        self.quality = quality
        self._capture_boundary_sequence = None
        self.renewal_revision = 0
        self._renewal_lock = threading.Lock()

    def renew(self, revision):
        """Share one validated grant across concurrent requests of one revision."""
        with self._renewal_lock:
            if revision == self.renewal_revision:
                url, _, _ = asyncio.run(
                    RplayLiveEngine().resolve_stream(self.channel_id, self.quality, force_refresh=True))
                if not media_allowed(url):
                    raise RecordingError("rplay_stream", "알플레이 갱신 재생 주소가 허용되지 않습니다.")
                self.args["url"] = url
                self.renewal_revision += 1
            return self.url
