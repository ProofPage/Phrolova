"""Per-instance checks before yt-dlp joins CHZZK native HLS/DASH fragments."""
from yt_dlp.downloader.hls import HlsFD
from yt_dlp.downloader.dash import DashSegmentsFD
from yt_dlp.utils import DownloadError
from concurrent.futures import ThreadPoolExecutor
from collections import deque
import math

from app.engine.chzzk_continuity import validate_media, Unavailable


class VerifiedFragment:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fatal_error = None

    def report_retry(self, error, count, retries, frag_index=None, fatal=True):
        if fatal and count > retries:
            self._fatal_error = error
        return super().report_retry(error, count, retries, frag_index, fatal)

    def download_and_append_fragments(self, ctx, fragments, info_dict, **kwargs):
        workers = math.ceil(self.params.get('concurrent_fragment_downloads', 1) / ctx.get('max_progress', 1))
        if workers > 1:
            pool = kwargs.get('tpe')
            kwargs['tpe'] = BoundedMap(pool, workers) if pool else BoundedExecutor(max_workers=workers)
        try:
            return super().download_and_append_fragments(ctx, fragments, info_dict, **kwargs)
        except (ValueError, OSError):
            # Another native worker can close the output before an earlier
            # completed fragment is appended. Surface its HTTP failure, not
            # the secondary "write to closed file" exception.
            if self._fatal_error is not None:
                from app.engine.platform_auth import redact_media_error
                raise DownloadError(redact_media_error(self._fatal_error)) from None
            raise

    def _append_fragment(self, ctx, frag_content):
        try:
            initialization = len(frag_content) >= 8 and frag_content[4:8] == b'ftyp'
            validate_media(frag_content, initialization)
        except Unavailable:
            ctx['dest_stream'].close()
            raise DownloadError('미디어 세그먼트가 잘렸거나 손상되었습니다. 원본 조각을 확인하고 다시 다운로드하세요.') from None
        return super()._append_fragment(ctx, frag_content)


class VerifiedHlsFD(VerifiedFragment, HlsFD):
    pass


class VerifiedDashFD(VerifiedFragment, DashSegmentsFD):
    pass


class BoundedMap:
    """Do not submit the entire manifest to an executor before seeing errors."""
    def __init__(self, pool, window):
        self.pool, self.window = pool, window

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def map(self, function, iterable):
        items, pending = iter(iterable), deque()
        try:
            for _ in range(self.window):
                item = next(items, None)
                if item is None:
                    break
                pending.append(self.pool.submit(function, item))
            while pending:
                yield pending.popleft().result()
                item = next(items, None)
                if item is not None:
                    pending.append(self.pool.submit(function, item))
        finally:
            for future in pending:
                future.cancel()


class BoundedExecutor(ThreadPoolExecutor):
    def map(self, function, iterable):
        return BoundedMap(self, self._max_workers).map(function, iterable)
