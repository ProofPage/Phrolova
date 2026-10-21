"""Session-scoped transport options and guarded HLS threads, without global patches."""
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from requests.auth import AuthBase
from streamlink.exceptions import StreamError

from app.core.config import get_settings
from app.core.streamlink_settings import StreamlinkPlatformOptions
from app.engine.platform_auth import redact_media_error


QUERY_MEDIA_DOMAINS = {
    "chzzk": ("navercdn.com", "pstatic.net", "akamaized.net"),
    "youtube": ("googlevideo.com",),
    "cime": ("ci.me", "live-video.net"),
    "kick": ("live-video.net", "cloudfront.net"),
    "twitch": ("ttvnw.net", "live-video.net"),
    "tiktok": ("tiktokcdn.com", "byteoversea.com", "ibytedtos.com", "tiktokv.com"),
    "bilibili": ("bilivideo.com", "bilivideo.cn", "biliapi.net"),
}


class StreamQueryAuth(AuthBase):
    def __init__(self, platform, media_url, parameters, delegate=None):
        self.platform = platform
        self.hosts = {urlsplit(media_url).hostname} if media_url else set()
        parts = urlsplit(media_url or "")
        self.origin = (parts.scheme, parts.hostname, parts.port)
        self.parameters = parameters
        self.delegate = delegate

    def __call__(self, request):
        from app.engine.preview_proxy import PreviewProxy
        parts = urlsplit(request.url)
        same_origin = (parts.scheme, parts.hostname, parts.port) == self.origin
        host = parts.hostname or ""
        trusted_cdn = (
            PreviewProxy.allowed(request.url, self.hosts, self.platform)
            if self.platform in ("rplay", "pandalive", "popkontv") else
            PreviewProxy.valid(request.url) and any(
                host == domain or host.endswith("." + domain)
                for domain in QUERY_MEDIA_DOMAINS.get(self.platform, ())
            )
        )
        if (same_origin and parts.scheme in ("http", "https") and not parts.username and not parts.password
                or trusted_cdn):
            query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                     if key not in self.parameters]
            query.extend(self.parameters.items())
            request.url = urlunsplit(parts._replace(query=urlencode(query)))
        return self.delegate(request) if self.delegate is not None else request


def configure_streamlink_session(session, platform, media_url=None, loss_report=None):
    options = StreamlinkPlatformOptions.model_validate(
        get_settings().streamlink_platform_options.get(platform, {})
    )
    if options.playlist_reload_seconds:
        session.set_option("hls-playlist-reload-time", options.playlist_reload_seconds)
    if options.query_parameters:
        session.http.auth = StreamQueryAuth(platform, media_url, options.query_parameters, session.http.auth)
    session._phrolova_loss_report = loss_report
    session._phrolova_platform = platform


def _thread_failure(thread, error):
    reader = thread.reader
    from app.engine.recording_errors import RecordingError
    reader._phrolova_error = (error if isinstance(error, RecordingError) else
                             StreamError(f"{type(error).__name__}: {redact_media_error(error)}"))
    report = reader.session._phrolova_loss_report
    if report is not None:
        report.error()
    reader.worker.close()
    reader.buffer.close()
    thread.close()


@lru_cache(maxsize=16)
def guarded_hls_stream(stream_type):
    base_reader = stream_type.__reader__

    class Worker(base_reader.__worker__):
        def check_sequence_gap(self, segment):
            if type(segment.num) is not int or not 0 <= segment.num < 2**64:
                raise StreamError("Invalid HLS media sequence number")
            from streamlink.stream.segmented import SegmentedStreamWorker
            if base_reader.__worker__.check_sequence_gap is SegmentedStreamWorker.check_sequence_gap:
                size = segment.num - self.sequence
                if size > 0:
                    from app.core.logger import get_platform_logger
                    get_platform_logger(getattr(self.session, "_phrolova_platform", None), "capture").warning(
                        "[%s] HLS sequence gap · track=%s · first=%s · last=%s · segments=%s; "
                        "수신 조각 번호가 불연속적입니다. 파일 검사와 별도로 확인하세요.",
                        getattr(self.stream, "channel_id", "unknown"),
                        getattr(self.stream, "_phrolova_track_id", "0"),
                        self.sequence, segment.num - 1, size)
                return
            return super().check_sequence_gap(segment)

        def run(self):
            try:
                super().run()
            except Exception as error:
                _thread_failure(self, error)
                self.writer.close()

    class Writer(base_reader.__writer__):
        def _write_plain(self, segment, response):
            if not super()._write_plain(segment, response):
                from app.engine.recording_errors import RecordingError
                raise RecordingError("segment_write", "영상 조각을 끝까지 기록하지 못했습니다.", retryable=True)
            return True

        def _write_decrypt(self, segment, response, key):
            if not super()._write_decrypt(segment, response, key):
                from app.engine.recording_errors import RecordingError
                raise RecordingError("segment_decrypt", "암호화 영상 조각을 정상적으로 기록하지 못했습니다.", retryable=True)
            return True

        def write(self, segment, result, *data):
            super().write(segment, result, *data)
            report = self.session._phrolova_loss_report
            if report is not None and not (data and data[0]) and not self.should_filter_segment(segment):
                report.segment(getattr(self.stream, "_phrolova_track_id", "0"), segment.num)

        def run(self):
            try:
                super().run()
            except Exception as error:
                _thread_failure(self, error)

    class Reader(base_reader):
        __worker__ = Worker
        __writer__ = Writer

        def __init__(self, *args, **kwargs):
            self._phrolova_error = None
            super().__init__(*args, **kwargs)

        def read(self, size=-1):
            data = super().read(size)
            if not data and self._phrolova_error is not None:
                raise self._phrolova_error
            return data

    class Stream(stream_type):
        __reader__ = Reader

    return Stream
