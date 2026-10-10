"""
Phrolova: VOD Engine (yt-dlp 래퍼)
yt-dlp를 사용하여 여러 플랫폼의 영상과 오디오를 다운로드한다.
취소, 일시정지, 재개 기능을 지원한다.
"""

from __future__ import annotations

import asyncio
import math
import os
import subprocess
import tempfile
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional
from urllib.parse import urlsplit

from app.engine.chzzk_cdn import ChzzkCdnYoutubeDL, is_chzzk_media_url, is_chzzk_vod_url
from app.engine.vod_preparation import VodPreparation
from app.engine.media_inspection import InspectionError, probe_media
from app.core.vod_filename import build_vod_outtmpl
from app.core.config import get_settings
from app.core.logger import logger, get_media_logger
from app.engine.auth import AuthManager
from app.engine.youtube_channel import ChannelImports
from app.engine.youtube_support import (is_youtube_url, runtime_options, youtube_cookies,
                                       with_youtube_cookie_fallback, YouTubeAuthenticationError)

# ── yt-dlp DASH MPD 파서 멍키패치 ──────────────────────────────
# 치지직 VOD(ABR_HLS 방식) 다운로드 시 Initialization의 sourceURL 및 SegmentURL의 media 속성이
# 누락되어 발생하는 KeyError를 방지하기 위해 동적으로 속성을 보완한다.
try:
    import yt_dlp.extractor.common as common
    def _patch_mpd_parser(original):
        def patched(self, mpd_doc, *args, **kwargs):
            for elem in mpd_doc.iter():
                if not isinstance(elem.tag, str):
                    continue
                tag = elem.tag.rsplit('}', 1)[-1]
                if tag == 'Initialization':
                    elem.attrib.setdefault('sourceURL', '')
                elif tag == 'SegmentURL':
                    elem.attrib.setdefault('media', '')
            return original(self, mpd_doc, *args, **kwargs)
        patched._phrolova_mpd_patch = True
        return patched

    if not getattr(common.InfoExtractor._parse_mpd_periods, '_phrolova_mpd_patch', False):
        common.InfoExtractor._parse_mpd_periods = _patch_mpd_parser(common.InfoExtractor._parse_mpd_periods)
    logger.info("✅ yt-dlp DASH MPD 파서 멍키패치 적용 완료")
except Exception as e:
    logger.error(f"❌ yt-dlp DASH MPD 파서 멍키패치 적용 실패: {e}")

from app.services.notifications import NotificationKind
from app.store.repositories import VodRepository

if TYPE_CHECKING:
    from app.services.notifications import NotificationService


class DownloadCancelledError(Exception):
    """다운로드 취소 예외."""


class NonRetryableDownloadError(Exception):
    """다시 시도해도 결과가 같은 실패. 메시지는 그대로 사용자에게 보여준다.

    로그인 전용 영상처럼 권한 때문에 막힌 경우 재시도는 시간만 쓰고,
    yt-dlp의 엉뚱한 오류 문구만 세 번 남긴다.
    """


class VodDownloadState(str, Enum):
    """VOD 다운로드 상태."""

    IDLE = "idle"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLING = "cancelling"


@dataclass
class VodDownloadTask:
    """개별 다운로드 작업."""

    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    url: str = ""
    title: str = "Unknown"
    state: VodDownloadState = VodDownloadState.IDLE
    progress: float = 0.0
    quality: str = "best"
    cdn: str = "default"
    cdn_applied: bool = False
    warning_message: Optional[str] = None
    download_warning_message: Optional[str] = None
    media_duration: Optional[float] = None
    inspection_state: str = "pending"
    inspection_code: Optional[str] = None
    inspection_message: Optional[str] = None
    inspection_diagnostics: dict[str, Any] = field(default_factory=dict)
    inspected_at: Optional[datetime] = None
    file_size: Optional[int] = None
    retry_task_id: Optional[str] = None
    inspection_task: Optional[asyncio.Task] = field(default=None, repr=False)
    prepared: bool = False
    phase: str = "queued"
    metadata: dict[str, Any] = field(default_factory=dict)
    source_url: str = field(default="", init=False, repr=False)
    output_dir: str = ""
    output_path: Optional[str] = None
    expected_part_file: Optional[str] = None
    resolved_filename: Optional[str] = None
    filename_template: Optional[str] = None
    filename_started_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # 다운로드 통계
    download_speed: float = 0.0  # MB/s
    downloaded_bytes: int = 0  # 바이트
    total_bytes: int = 0  # 바이트
    eta_seconds: int = 0  # 예상 남은 시간 (초)

    # 재시도 관련
    retry_count: int = 0  # 현재까지 재시도 횟수
    max_retries: int = 3  # 첫 시도 포함 최대 시도 횟수

    # 제어 플래그 (각 작업별 독립)
    cancel_flag: bool = False
    pause_event: threading.Event = field(default_factory=threading.Event)
    download_task: Optional[asyncio.Task] = None
    process: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.pause_event.set()  # 초기 상태: 일시정지 아님
        self.source_url = self.url


class VodEngine(VodPreparation):
    """yt-dlp 기반 VOD/클립 다운로드 엔진.

    치지직, 유튜브 및 지원 사이트의 영상 주소를 처리한다.
    인증 쿠키를 통해 성인 인증 영상에도 접근 가능하다.
    취소, 일시정지, 재개 기능을 제공한다.

    다중 다운로드를 지원하며, task_id로 각 작업을 관리한다.
    """

    def __init__(
        self,
        auth: Optional[AuthManager] = None,
        notifier: Optional[NotificationService] = None,
        repo: Optional[VodRepository] = None,
    ) -> None:
        self._auth = auth or AuthManager()
        self._tasks: dict[str, VodDownloadTask] = {}
        self.channel_imports = ChannelImports(self._enqueue_channel_video)
        self._notifier = notifier
        self._shutting_down = False
        self._repo = repo or VodRepository()


        # 설정에서 동시 다운로드 개수 가져오기
        settings = get_settings()
        self._max_concurrent = settings.vod_max_concurrent
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

        self._metadata_semaphore = asyncio.Semaphore(2)
        self._metadata_tasks: set[asyncio.Task] = set()
        self._inspection_tasks: set[asyncio.Task] = set()
        self._load_history()

    def _notify(
        self,
        kind: NotificationKind,
        title: str,
        description: str = "",
        color: str = "green",
        fields: Optional[dict[str, str]] = None,
    ) -> None:
        """알림을 큐에 넣는다. 논블로킹이며 다운로드 흐름을 막지 않는다."""
        if self._notifier is None:
            return
        self._notifier.notify(
            kind=kind,
            title=title,
            description=description,
            color=color,
            fields=fields,
        )

    @property
    def state(self) -> VodDownloadState:
        """하위 호환성을 위한 속성. 첫 번째 작업의 상태 반환."""
        if not self._tasks:
            return VodDownloadState.IDLE
        first_task = next(iter(self._tasks.values()))
        return first_task.state

    @property
    def progress(self) -> float:
        """하위 호환성을 위한 속성. 첫 번째 작업의 진행률 반환."""
        if not self._tasks:
            return 0.0
        first_task = next(iter(self._tasks.values()))
        return first_task.progress

    def _task_logger(self, task_id: str):
        task = self._tasks.get(task_id)
        return get_media_logger(task.url) if task else logger

    @staticmethod
    def _terminate_process(process: asyncio.subprocess.Process) -> None:
        try:
            process.terminate()
        except ProcessLookupError:
            return
        def force_stop() -> None:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        asyncio.get_running_loop().call_later(10.0, force_stop)

    def _is_chzzk_url(self, url: str) -> bool:
        """치지직 URL인지 확인."""
        return is_chzzk_media_url(url)

    def _is_x_spaces_url(self, url: str) -> bool:
        """X Spaces / Periscope CDN URL인지 확인."""
        return "pscp.tv" in url or "video.pscp.tv" in url or "x.com/i/spaces" in url

    def _build_ytdlp_options(
        self,
        task: VodDownloadTask,
        progress_callback: Optional[Callable[[dict], None]] = None,
        cookie_file: Optional[str] = None,
    ) -> dict[str, Any]:
        """yt-dlp 옵션 딕셔너리를 구성한다.

        cookie_file은 빌려받은 임시 사본이어야 한다. yt-dlp가 끝날 때 이 파일을 다시 쓴다.
        """
        logger = get_media_logger(task.url)
        settings = get_settings()
        if not getattr(task, "filename_template", None):
            task.filename_template = settings.vod_filename_template
            task.filename_started_at = task.started_at or datetime.now()
        ffmpeg_path = settings.resolve_ffmpeg_path()
        ffmpeg_dir = str(Path(ffmpeg_path).parent)

        opts: dict[str, Any] = {
            # Keep app-managed cookie files/headers authoritative. A user's global
            # yt-dlp config may inject `--add-header Cookie`, which is deprecated
            # and can leak credentials to CDN hosts.
            "ignoreconfig": True,
            "logger": get_media_logger(task.url),
            "format": task.quality,
            # 제목이 같아도 다른 영상이면 기존 파일로 오인해 건너뛰지 않도록 구분한다.
            "outtmpl": str(
                Path(task.output_dir)
                / build_vod_outtmpl(task.filename_template, task.quality, task.filename_started_at)
            ),
            "merge_output_format": settings.vod_format,
            "ffmpeg_location": ffmpeg_dir,
            "no_warnings": True,
            "quiet": True,
            "no_color": True,
            # 긴 VOD와 느린 CDN 회선에서 기본값으로 너무 빨리 포기하지 않도록 한다.
            "socket_timeout": 60,
            "retries": 10,
            "fragment_retries": 10,
            "extractor_retries": 5,
            "file_access_retries": 5,
        }

        if is_chzzk_vod_url(task.source_url):
            # DASH exposes video/audio separately; plain "best" requires a muxed format.
            if task.quality == "best":
                opts["format"] = "bestvideo*+bestaudio/best"
            elif task.quality == "worst":
                opts["format"] = "worstvideo*+worstaudio/worst"

        if task.prepared and task.quality.endswith("p") and task.quality[:-1].isdigit():
            height = int(task.quality[:-1])
            opts["format"] = f"bestvideo*[height={height}]+bestaudio/best[height={height}]"
        opts["postprocessor_hooks"] = [lambda d: setattr(task, "phase", "merging") if d.get("status") == "started" else None]

        if is_youtube_url(task.url):
            opts.update(runtime_options())
            opts["noplaylist"] = True

        # 쿠키는 별도 Netscape jar에 두어 각 도메인에만 전송되게 한다.
        if self._is_chzzk_url(task.url):
            opts["http_headers"] = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            }

        if cookie_file:
            opts["cookiefile"] = cookie_file

        # X Spaces / Periscope CDN URL인 경우 오디오 전용 포맷 강제
        # pscp.tv는 오디오 전용 HLS — "best"로 요청하면 video+audio 조합 포맷을 찾다가
        # 빈 파일 반환. "bestaudio/best"로 오버라이드해야 정상 다운로드됨.
        if self._is_x_spaces_url(task.url):
            opts["format"] = "bestaudio/best"
            opts["merge_output_format"] = "m4a"
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]
            logger.debug(f"[{task.task_id}] X Spaces URL 감지 → format=bestaudio/best, m4a 오디오 전용 출력")

        # 진행률 콜백
        if progress_callback:
            opts["progress_hooks"] = [progress_callback]

        # 속도 제한 (MB/s → bytes/s)
        if settings.vod_max_speed > 0:
            opts["ratelimit"] = settings.vod_max_speed * 1024 * 1024  # MB/s to bytes/s

        return opts

    def _make_progress_callback(self, task: VodDownloadTask) -> Callable[[dict], None]:
        """task별 진행률 콜백 생성."""
        def _on_progress(d: dict) -> None:
            """yt-dlp 진행률 콜백 핸들러.

            이 콜백 내에서 취소/일시정지를 제어한다.
            yt-dlp가 주기적으로 이 콜백을 호출하므로, 여기서 blocking하면 일시정지 효과가 나타남.
            """
            # 취소 체크 — 즉시 예외로 yt-dlp를 중단
            if task.cancel_flag:
                raise DownloadCancelledError("다운로드가 취소되었습니다.")

            # 일시정지 체크 — event가 set될 때까지 blocking
            task.pause_event.wait()

            # 다시 취소 체크 (일시정지 해제 후 취소된 경우)
            if task.cancel_flag:
                raise DownloadCancelledError("다운로드가 취소되었습니다.")

            if d.get("status") == "downloading":
                task.phase = "downloading"
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                if total > 0:
                    task.progress = (downloaded / total) * 100

                # 다운로드 통계 업데이트
                task.downloaded_bytes = downloaded
                task.total_bytes = total

                # 속도 (bytes/s → MB/s)
                speed_bytes = d.get("speed", 0) or 0
                task.download_speed = speed_bytes / (1024 * 1024) if speed_bytes > 0 else 0.0

                # 예상 남은 시간 (초)
                task.eta_seconds = d.get("eta", 0) or 0

            elif d.get("status") == "finished":
                task.progress = 100.0

        return _on_progress

    @staticmethod
    def _validate_media_url(url: str) -> None:
        # 다운로드 URL이 파일/FFmpeg 로컬 프로토콜로 해석되지 않도록 제한한다.
        parsed = urlsplit(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise NonRetryableDownloadError("http/https 영상 URL을 입력해 주세요.")
        if parsed.username or parsed.password:
            raise NonRetryableDownloadError("인증 정보가 포함된 URL은 사용할 수 없습니다.")
        host = parsed.hostname.lower()
        if host == "twitcasting.tv" or host.endswith(".twitcasting.tv"):
            raise NonRetryableDownloadError("지원하지 않는 영상 플랫폼입니다.")

    async def get_video_info(self, url: str) -> dict:
        """VOD/클립의 메타데이터를 조회한다.

        Returns:
            title, duration, thumbnail, formats 등.
        """
        self._validate_media_url(url)
        if self._is_chzzk_url(url) and "/clips/" in urlsplit(url).path:
            from app.engine.vod_preparation import canonical_vod_url
            import httpx
            canonical = canonical_vod_url(url)
            clip_id = canonical.rsplit("/", 1)[-1]
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.get(f"https://api.chzzk.naver.com/service/v1/play-info/clip/{clip_id}", headers=self._auth.get_http_headers())
                response.raise_for_status()
                content = response.json().get("content") or {}
            video_id, in_key = content.get("videoId"), content.get("inKey")
            from urllib.parse import urlencode, quote
            playback = None
            if video_id and in_key:
                playback = f"https://apis.naver.com/neonplayer/vodplay/v1/playback/{quote(str(video_id), safe='')}?{urlencode({'key': in_key, 'env': 'real', 'lc': 'en_US', 'cpl': 'en_US'})}"
            else:
                import json
                for key in ("liveRewindPlaybackJson", "playbackJson"):
                    raw = content.get(key)
                    try:
                        data = json.loads(raw) if isinstance(raw, str) else raw or {}
                        playback = next((media.get("path") for media in data.get("media", []) if str(media.get("path", "")).startswith(("http://", "https://"))), None)
                    except (ValueError, TypeError, AttributeError):
                        continue
                    if playback:
                        break
            if not playback:
                raise ValueError("클립의 재생 정보를 가져오지 못했습니다.")
            info = await self.get_video_info(playback)
            channel = content.get("ownerChannel") or content.get("channel") or {}
            info.update(id=clip_id, title=content.get("contentTitle") or info.get("title"),
                        uploader=channel.get("channelName") or info.get("uploader"),
                        profile_image=channel.get("channelImageUrl") or "")
            return info
        opts: dict[str, Any] = {
            "ignoreconfig": True,
            "logger": get_media_logger(url),
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "socket_timeout": 15,
            "extractor_retries": 1,
            "noplaylist": True,
        }

        def _extract() -> dict[str, Any] | None:
            import yt_dlp
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)

        async def extract(cookie_file):
            opts.pop("cookiefile", None)
            if cookie_file:
                opts["cookiefile"] = cookie_file
            return await asyncio.to_thread(_extract)

        if is_youtube_url(url):
            info = await with_youtube_cookie_fallback(extract)
        else:
            with self._borrow_ytdlp_cookie_file(url) as cookie_file:
                info = await extract(cookie_file)

        if not info:
            raise ValueError(f"영상 정보를 가져올 수 없습니다: {url}")

        profile_image = info.get("channel_thumbnail") or ""
        channel_id = info.get("channel_id") or ""
        if is_chzzk_vod_url(url) and not profile_image and isinstance(channel_id, str) and len(channel_id) == 32 and all(c in "0123456789abcdef" for c in channel_id):
            import httpx
            try:
                async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
                    response = await client.get(f"https://api.chzzk.naver.com/service/v1/channels/{channel_id}", headers=self._auth.get_http_headers())
                    response.raise_for_status()
                    profile_image = (response.json().get("content") or {}).get("channelImageUrl") or ""
            except (httpx.HTTPError, ValueError, AttributeError):
                pass  # Optional profile artwork never prevents VOD preparation.

        formats = []
        for f in info.get("formats", []):
            formats.append({
                "format_id": f.get("format_id"),
                "ext": f.get("ext"),
                "resolution": f.get("resolution", "audio only"),
                "filesize": f.get("filesize"),
                "height": f.get("height"),
                "vcodec": f.get("vcodec"),
                "acodec": f.get("acodec"),
            })

        return {
            "title": info.get("title", "Unknown"),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail", ""),
            "uploader": info.get("channel") or info.get("uploader", ""),
            "id": info.get("id", ""),
            "upload_date": info.get("upload_date"),
            "profile_image": profile_image,
            "formats": formats,
            "url": url,
        }

    async def download(
        self,
        url: str,
        output_dir: Optional[str] = None,
        quality: str = "best",
        cdn: str = "default",
    ) -> str:
        """VOD/클립 다운로드를 시작한다.

        Args:
            url: 치지직 VOD/클립 URL 또는 유튜브 등 yt-dlp 지원 사이트 URL.
            output_dir: 저장 디렉토리.
            quality: 화질 ('best', 'worst', 또는 format_id).

        Returns:
            task_id (작업 추적용 UUID).
        """
        self._validate_media_url(url)
        if cdn not in ("default", "akamai"):
            raise ValueError("지원하지 않는 CDN입니다.")
        logger = get_media_logger(url)
        settings = get_settings()

        if output_dir is not None:
            # 명시적으로 경로가 주어진 경우 → 그대로 사용
            save_dir = output_dir
        else:
            save_dir = settings.effective_vod_download_dir(self._is_chzzk_url(url))

        Path(save_dir).mkdir(parents=True, exist_ok=True)

        # 새 작업 생성
        task = VodDownloadTask(
            url=url,
            quality=quality,
            cdn=cdn,
            output_dir=save_dir,
            state=VodDownloadState.IDLE,
            # 선택한 CDN 안에서만 제한된 재시도를 수행한다.
            max_retries=5 if self._is_chzzk_url(url) else 3,
        )

        # 새 작업을 맨 앞에 추가 (최신 항목이 위로)
        new_tasks = {task.task_id: task}
        new_tasks.update(self._tasks)
        self._tasks = new_tasks

        # 백그라운드에서 다운로드 시작
        self._save_history()
        task.download_task = asyncio.create_task(self._run_download(task.task_id))

        logger.info(f"[{task.task_id}] 다운로드 작업 추가: {url} (화질: {quality})")
        return task.task_id

    @staticmethod
    def is_youtube_channel_url(url: str) -> bool:
        """YouTube 채널 주소인지 확인한다."""
        try:
            parsed = urlsplit(url.strip())
        except ValueError:
            return False
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if host not in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
            return False
        path = parsed.path.rstrip("/")
        return (
            path.startswith("/@")
            or path.startswith("/channel/")
            or path.startswith("/c/")
            or path.startswith("/user/")
        )

    async def _enqueue_channel_video(self, entry, output_dir, quality) -> bool:
        url = entry["url"]
        if any(task.url == url and task.state != VodDownloadState.ERROR
               for task in self._tasks.values()):
            return False
        task_id = await self.download(url, output_dir, quality)
        self._tasks[task_id].title = entry.get("title") or url
        return True

    async def _run_download(self, task_id: str) -> None:
        """실제 다운로드 실행 (세마포어로 동시 실행 제어).

        슬롯은 한 번의 시도 동안만 쥐고, 재시도는 슬롯을 반납한 뒤에 다시 줄을 선다.
        asyncio.Semaphore는 재진입되지 않아서 슬롯을 쥔 채 또 얻으려 하면, 동시 개수가
        1일 때는 첫 재시도가 자기 자신을 기다리며 멈추고, 여러 작업이 한꺼번에 실패하면
        서로의 슬롯을 기다리며 교착된다.
        """
        logger = self._task_logger(task_id)
        try:
            await self._run_download_loop(task_id)
        finally:
            # 재시도 대기/슬롯 대기에서 취소되어도 CANCELLING 상태로 남기지 않는다.
            task = self._tasks.get(task_id)
            if task is not None and task.cancel_flag and task.state == VodDownloadState.CANCELLING:
                task.state = VodDownloadState.IDLE
                task.progress = 0.0
                self._save_history()

    async def _run_download_loop(self, task_id: str) -> None:
        logger = self._task_logger(task_id)
        while True:
            async with self._semaphore:  # 동시 다운로드 제한
                should_retry = await self._attempt_download(task_id)
            if not should_retry:
                return

            task = self._tasks[task_id]
            if task.cancel_flag:
                return
            # 갱신된 재생 정보와 이전 시도의 조각이 섞이지 않게 정리한다.
            # CDN 선택은 작업 생성 시 고정되어 재시도 중 바뀌지 않는다.
            if self._is_chzzk_url(task.url):
                if not await self._cleanup_partial_files(task):
                    task.state = VodDownloadState.ERROR
                    task.error_message = (
                        "이전 시도의 임시 조각 파일을 삭제하지 못해 안전한 재시도를 중단했습니다. "
                        "파일 잠금을 해제한 뒤 다시 시도해 주세요."
                    )
                    logger.error(f"[{task_id}] {task.error_message}")
                    self._save_history()
                    return
            # 일시적 오류일 가능성이 있으므로 잠시 대기 후 재시도.
            # 슬롯은 이미 반납했으니 기다리는 동안 대기 중인 다른 다운로드가 쓸 수 있다.
            await asyncio.sleep(3 * task.retry_count)  # 백오프: 3초, 6초, 9초...

            # 진행률 초기화 후 재시도
            task.progress = 0.0
            task.download_speed = 0.0
            task.downloaded_bytes = 0
            task.total_bytes = 0
            task.eta_seconds = 0

    async def _attempt_download(self, task_id: str) -> bool:
        """슬롯을 쥔 상태에서 한 번 시도한다. 다시 시도해야 하면 True를 돌려준다."""
        logger = self._task_logger(task_id)
        task = self._tasks.get(task_id)
        if not task:
            logger.error(f"[{task_id}] 작업을 찾을 수 없습니다.")
            return False

        if task.cancel_flag:
            task.state = VodDownloadState.IDLE
            task.progress = 0.0
            self._save_history()
            return False
        task.state = VodDownloadState.DOWNLOADING
        task.phase = "downloading"
        self._save_history()
        task.started_at = datetime.now()
        logger.info(f"[{task_id}] 다운로드 시작: {task.url}")

        try:
            if self._is_chzzk_url(task.url) and "/clips/" in task.url:
                await self._download_clip(task_id, task)
            elif self._is_x_spaces_url(task.url):
                await self._download_x_spaces_replay(task_id, task)
            else:
                await self._download_external(task_id, task)

        except DownloadCancelledError:
            task.state = VodDownloadState.IDLE
            task.progress = 0.0
            if not self._shutting_down and not get_settings().keep_download_parts:
                await self._cleanup_partial_files(task)
            logger.info(f"[{task_id}] 다운로드 취소됨: {task.url}")

        except asyncio.CancelledError:
            # 서버 종료(Ctrl+C) 등으로 태스크가 취소됨 → 재시도하지 않음
            task.state = VodDownloadState.IDLE
            task.progress = 0.0
            logger.info(f"[{task_id}] 다운로드 작업 취소됨 (서버 종료): {task.url}")
            raise  # CancelledError는 반드시 재전파

        except Exception as e:
            # FFmpeg 프로세스 실패 시 처리
            if task.cancel_flag:
                task.state = VodDownloadState.IDLE
                task.progress = 0.0
                if not self._shutting_down and not get_settings().keep_download_parts:
                    await self._cleanup_partial_files(task)
                logger.info(f"[{task_id}] 다운로드 취소됨 (예외 처리): {task.url}")
            else:
                import traceback
                tb_str = traceback.format_exc()
                error_msg = self._format_download_error(e)

                # 이벤트 루프가 종료 중이면 재시도하지 않음
                loop = asyncio.get_event_loop()
                if not loop.is_running():
                    logger.info(f"[{task_id}] 이벤트 루프 종료 중, 재시도 중단")
                    task.state = VodDownloadState.ERROR
                    task.error_message = error_msg
                    return False

                if isinstance(e, NonRetryableDownloadError):
                    logger.error(f"[{task_id}] 다운로드 불가: {e}")
                    task.error_message = error_msg
                    task.state = VodDownloadState.ERROR
                    if not self._shutting_down and not get_settings().keep_download_parts:
                        await self._cleanup_partial_files(task)
                    self._save_history()
                    return False

                task.retry_count += 1

                # 재시도 가능 여부 확인
                if task.retry_count < task.max_retries:
                    logger.warning(
                        f"[{task_id}] 다운로드 실패 (재시도 {task.retry_count}/{task.max_retries}): {error_msg}"
                    )
                    task.error_message = f"재시도 중... ({task.retry_count}/{task.max_retries}): {error_msg}"
                    return True
                else:
                    # 최대 재시도 횟수 초과
                    logger.error(f"[{task_id}] 최대 재시도 횟수 초과: {error_msg}")
                    logger.error(f"[{task_id}] 상세 트레이스:\n{traceback.format_exc()}")

                    task.error_message = f"재시도 {task.max_retries}회 실패: {error_msg}"
                    task.state = VodDownloadState.ERROR
                    if not self._shutting_down and not get_settings().keep_download_parts:
                        await self._cleanup_partial_files(task)
                    # 에러 발생 시 이력 저장
                    self._save_history()

        if task.cancel_flag:
            self._save_history()
        return False

    async def _download_clip(self, task_id: str, task: VodDownloadTask) -> None:
        """치지직 클립 전용 다운로드.

        yt-dlp chzzk:video 익스트랙터는 숫자 ID만 지원하므로, 클립 play-info API에서
        직접 재생 URL을 추출해 yt-dlp에 전달한다.

        시도 순서:
        1. ABR_HLS: videoId(해시) + inKey → MPD URL → yt-dlp
        2. HLS: liveRewindPlaybackJson → HLS path → yt-dlp
        """
        logger = get_media_logger(task.url)
        import re
        import json as _json
        import httpx

        match = re.search(r"/clips/([^/?#]+)", task.url)
        if not match:
            raise RuntimeError(f"클립 URL 파싱 실패: {task.url}")

        clip_id = match.group(1)
        api_url = f"https://api.chzzk.naver.com/service/v1/play-info/clip/{clip_id}"
        headers = self._auth.get_http_headers()

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for attempt in range(3):
                try:
                    resp = await client.get(api_url, headers=headers, timeout=30.0)
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    retryable = status_code in (408, 425, 429) or status_code >= 500
                    if not retryable:
                        raise NonRetryableDownloadError(
                            f"CHZZK 클립 정보를 가져올 수 없습니다 (HTTP {status_code})."
                        ) from None
                    if attempt == 2:
                        raise RuntimeError(
                            f"CHZZK 클립 정보 요청이 재시도 후 실패했습니다 (HTTP {status_code})."
                        ) from None
                except (httpx.HTTPError, ValueError) as exc:
                    if attempt == 2:
                        raise RuntimeError(
                            f"CHZZK 클립 정보 요청이 재시도 후 실패했습니다 ({type(exc).__name__})."
                        ) from None
                await asyncio.sleep(attempt + 1)

        content = data.get("content") or {}

        # 클립 제목 · 채널명 추출
        clip_title = content.get("contentTitle") or "Unknown Clip"
        owner = content.get("ownerChannel") or {}
        channel_name = owner.get("channelName") or "Unknown"

        # 파일명에 쓸 수 없는 문자 제거
        def _sanitize(s: str) -> str:
            return re.sub(r'[\\/:*?"<>|]', "_", s).strip()

        safe_title = _sanitize(clip_title)
        safe_channel = _sanitize(channel_name)
        task.title = f"[{safe_channel}] {safe_title}"
        logger.info(f"[{task_id}] 클립 메타: channel={channel_name!r}, title={clip_title!r}")

        # 방법 1: ABR_HLS (videoId 해시 + inKey → MPD URL)
        video_id = content.get("videoId")
        in_key = content.get("inKey")
        if video_id and in_key:
            playback_url = (
                f"https://apis.naver.com/neonplayer/vodplay/v1/playback/{video_id}"
                f"?key={in_key}&env=real&lc=en_US&cpl=en_US"
            )
            logger.info(f"[{task_id}] 클립 ABR_HLS 재생 URL 사용: {playback_url[:80]}...")
            source_url = task.url
            task.url = playback_url
            try:
                await self._download_external(task_id, task)
            finally:
                task.url = source_url
            # _download_external이 task.title을 yt-dlp 메타로 덮어쓰므로 복원
            self._rename_clip_output(task_id, task, safe_channel, safe_title)
            if task.state == VodDownloadState.COMPLETED and task.output_path:
                await self._inspect_chzzk_download(task, task.metadata, task.output_path)
            return

        # 방법 2: HLS (liveRewindPlaybackJson 또는 playbackJson)
        for json_key in ("liveRewindPlaybackJson", "playbackJson"):
            raw = content.get(json_key)
            if not raw:
                continue
            try:
                playback = _json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                continue
            for media in (playback.get("media") or []):
                hls_path = media.get("path") or ""
                if hls_path.startswith("http"):
                    logger.info(f"[{task_id}] 클립 HLS URL 사용 ({json_key}): {hls_path[:80]}...")
                    source_url = task.url
                    task.url = hls_path
                    try:
                        await self._download_external(task_id, task)
                    finally:
                        task.url = source_url
                    self._rename_clip_output(task_id, task, safe_channel, safe_title)
                    if task.state == VodDownloadState.COMPLETED and task.output_path:
                        await self._inspect_chzzk_download(task, task.metadata, task.output_path)
                    return

        raise RuntimeError(
            f"클립 재생 URL을 추출할 수 없습니다. "
            f"content 키: {list(content.keys())}"
        )

    def _rename_clip_output(
        self, task_id: str, task: VodDownloadTask, channel: str, title: str
    ) -> None:
        """_download_external이 덮어쓴 task.title·output_path를 클립 메타 기반으로 복원한다."""
        logger = get_media_logger(task.url)
        proper_title = f"[{channel}] {title}"
        task.title = proper_title

        if not task.output_path:
            return
        src = Path(task.output_path)
        if not src.exists():
            return
        import yt_dlp
        template = str(src.parent / build_vod_outtmpl(task.filename_template or get_settings().vod_filename_template, task.quality, task.filename_started_at or task.started_at))
        with yt_dlp.YoutubeDL({"outtmpl": template, "quiet": True}) as ydl:
            dst = Path(ydl.prepare_filename({"title": title, "uploader": channel, "channel": channel,
                "id": task.url.rstrip("/").split("/")[-1].split("?")[0],
                "extractor_key": "CHZZKClip", "ext": src.suffix.lstrip(".")}))
        if dst == src:
            return
        if dst.exists():
            logger.warning(f"[{task_id}] 같은 이름의 클립 파일이 있어 기존 파일명을 유지합니다.")
            return
        try:
            src.rename(dst)
            task.output_path = str(dst)
            logger.info(f"[{task_id}] 클립 파일명 변경: {src.name} → {dst.name}")
        except Exception as e:
            logger.warning(f"[{task_id}] 클립 파일명 변경 실패: {e}")

    async def _download_x_spaces_replay(self, task_id: str, task: VodDownloadTask) -> None:
        """pscp.tv master_playlist.m3u8을 ffmpeg로 직접 다운로드한다.

        yt-dlp 대신 Colab 방식(playlist 파싱 → chunk URL 절대경로 재작성 → ffmpeg)을 사용.
        pscp.tv CDN의 상대경로 chunk URL 구조 때문에 yt-dlp generic HLS extractor가 실패하는 문제 해결.
        """
        logger = get_media_logger(task.url)
        import re
        import httpx
        from urllib.parse import urlparse

        settings = get_settings()
        ffmpeg_path = settings.resolve_ffmpeg_path()
        master_url = task.url

        # 1. master_playlist.m3u8 파싱 → sub-playlist URL 추출
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(master_url)
            resp.raise_for_status()
            master_text = resp.text

        parsed = urlparse(master_url)
        playlist_path = None
        for line in master_text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                playlist_path = stripped
                break

        if not playlist_path:
            raise RuntimeError("master_playlist.m3u8에서 sub-playlist URL을 찾을 수 없습니다.")

        from urllib.parse import urljoin
        playlist_url = urljoin(master_url, playlist_path)

        # 2. sub-playlist 가져오기 → chunk URL 절대경로로 재작성
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(playlist_url)
            resp.raise_for_status()
            playlist_text = resp.text

        def _abs(line: str) -> str:
            stripped = line.strip()
            if not stripped:
                return line
            if stripped.startswith('#'):
                # 암호화 키와 초기화 조각의 URI도 로컬 임시 파일이 아닌 원격 경로 기준이다.
                return re.sub(r'URI="([^"]+)"', lambda match: 'URI="' + urljoin(playlist_url, match.group(1)) + '"', line)
            return urljoin(playlist_url, stripped)

        playlist_abs = '\n'.join(_abs(line) for line in playlist_text.splitlines())
        if task.cancel_flag:
            raise DownloadCancelledError("다운로드가 취소되었습니다.")

        # 3. 임시 .m3u8 파일 저장
        tmp_m3u8 = Path(task.output_dir) / f"_tmp_{task_id}.m3u8"
        tmp_m3u8.write_text(playlist_abs, encoding='utf-8')

        # 4. 출력 파일명
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(task.output_dir) / f"[XSpaces] {timestamp} {task_id}.m4a"
        task.resolved_filename = str(output_path)
        task.expected_part_file = str(output_path)
        task.title = f"[X Spaces] {timestamp}"
        logger.info(f"[{task_id}] X Spaces ffmpeg 다운로드 시작: {output_path.name}")

        try:
            cmd = [
                ffmpeg_path, "-y",
                "-protocol_whitelist", "file,https,tls,tcp,crypto",
                "-i", str(tmp_m3u8),
                "-c", "copy",
                "-vn",
                str(output_path),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            task.process = proc
            try:
                _, stderr_data = await proc.communicate()
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.communicate()
                task.process = None
            if task.cancel_flag:
                raise DownloadCancelledError("다운로드가 취소되었습니다.")

            if proc.returncode != 0:
                err = stderr_data.decode(errors='replace')[-500:]
                raise RuntimeError(f"ffmpeg 오류 (code={proc.returncode}): {err}")

            if not output_path.exists() or output_path.stat().st_size == 0:
                raise RuntimeError("다운로드 완료 후 파일이 없거나 비어 있습니다.")

            task.state = VodDownloadState.COMPLETED
            task.completed_at = datetime.now()
            task.output_path = str(output_path)
            task.progress = 100.0
            logger.info(f"[{task_id}] X Spaces 다운로드 완료: {output_path.name}")
            self._save_history()

            try:
                file_size = output_path.stat().st_size / (1024 * 1024)
            except OSError:
                file_size = 0.0
            duration = (
                (task.completed_at - task.started_at).total_seconds()
                if task.started_at
                else 0
            )
            self._notify(
                NotificationKind.VOD_COMPLETED,
                title="📥 X Spaces 다운로드 완료",
                description=f"파일: **{output_path.name}**",
                color="green",
                fields={
                    "파일 크기": f"{file_size:.1f} MB",
                    "다운로드 시간": f"{duration // 60:.0f}분 {duration % 60:.0f}초",
                    "저장 경로": str(output_path),
                },
            )
        finally:
            try:
                tmp_m3u8.unlink(missing_ok=True)
            except Exception:
                pass

    async def _download_external(self, task_id: str, task: VodDownloadTask) -> None:
        """yt-dlp를 사용한 외부 URL(유튜브 등) 다운로드."""
        self._validate_media_url(task.url)
        if is_youtube_url(task.url):
            try:
                await with_youtube_cookie_fallback(
                    lambda cookie_file: self._download_with_ytdlp(task_id, task, cookie_file)
                )
            except YouTubeAuthenticationError as error:
                raise NonRetryableDownloadError(str(error)) from None
            return
        # 메타데이터 추출부터 실제 다운로드까지 같은 쿠키 사본을 쓰고, 끝나면 지운다.
        with self._borrow_ytdlp_cookie_file(task.url) as cookie_file:
            await self._download_with_ytdlp(task_id, task, cookie_file)

    @contextmanager
    def _borrow_ytdlp_cookie_file(self, url: str):
        """Provide a domain-scoped cookie file for yt-dlp instead of a global Cookie header."""
        if self._is_chzzk_url(url):
            cookies = self._auth.get_cookies()
            if cookies:
                fd, cookie_path = tempfile.mkstemp(prefix="chzzk_ytdlp_cookie_", suffix=".txt")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as cookie_file:
                        cookie_file.write("# Netscape HTTP Cookie File\n")
                        for name, value in cookies.to_dict().items():
                            cookie_file.write(
                                f".naver.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n"
                            )
                    yield cookie_path
                finally:
                    Path(cookie_path).unlink(missing_ok=True)
                return

        if is_youtube_url(url):
            with youtube_cookies() as cookie_file:
                yield cookie_file
            return

        yield None

    async def _download_with_ytdlp(
        self, task_id: str, task: VodDownloadTask, cookie_file: Optional[str]
    ) -> None:
        logger = get_media_logger(task.url)
        import yt_dlp

        # Capture origin once; clip extraction temporarily changes task.url.
        chzzk_source = is_chzzk_vod_url(task.source_url)
        selected_cdn = task.cdn if chzzk_source else "default"
        def make_ydl(options):
            if selected_cdn == "akamai":
                return ChzzkCdnYoutubeDL(options, cdn=selected_cdn)
            return yt_dlp.YoutubeDL(options)
        task.warning_message = None
        task.download_warning_message = None
        task.cdn_applied = False
        task.media_duration = None

        # 1. 메타데이터 추출
        opts_info = self._build_ytdlp_options(task, progress_callback=None, cookie_file=cookie_file)
        if chzzk_source:
            opts_info["hls_prefer_native"] = True
            opts_info["skip_unavailable_fragments"] = False

        def _extract_info() -> dict[str, Any] | None:
            with make_ydl(opts_info) as ydl:
                try:
                    return ydl.extract_info(task.url, download=False)
                finally:
                    if selected_cdn == "akamai":
                        task.cdn_applied |= ydl.cdn_applied

        info: dict[str, Any] | None = await asyncio.to_thread(lambda: _extract_info())  # type: ignore[arg-type]
        if task.cancel_flag:
            raise DownloadCancelledError("다운로드가 취소되었습니다.")

        if not info:
            raise RuntimeError("영상 정보를 가져올 수 없습니다.")

        vod_title = info.get("title", "Unknown")
        uploader = info.get("uploader") or info.get("channel") or "Unknown Channel"
        task.title = f"[{uploader}] {vod_title}"
        is_clip = "/clips/" in urlsplit(task.source_url).path
        task.metadata.update({key: info.get(key) for key in ("id", "duration", "thumbnail", "uploader", "upload_date", "is_live", "live_status")
                              if not is_clip or task.metadata.get(key) is None})
        if is_clip:
            task.metadata["id"] = urlsplit(task.source_url).path.rstrip("/").rsplit("/", 1)[-1]
        logger.info(f"[{task_id}] 미디어 정보: {task.title}")

        # 예상 파일명 저장
        with yt_dlp.YoutubeDL(opts_info) as ydl:
            expected_file = ydl.prepare_filename(info)
            task.expected_part_file = expected_file + ".part"

        # Reserve the final path on the event loop before downloading so concurrent
        # tasks cannot reuse a filename, even when their start times share a second.
        if task.resolved_filename:
            expected_file = task.resolved_filename
        else:
            candidate = Path(expected_file)
            reserved = {
                other.resolved_filename.casefold()
                for other in self._tasks.values()
                if other is not task and other.resolved_filename
            }
            index = 1
            while (candidate.exists() or Path(str(candidate) + ".part").exists()
                   or candidate.with_suffix("." + get_settings().vod_format).exists()
                   or str(candidate).casefold() in reserved
                   or str(candidate.with_suffix("." + get_settings().vod_format)).casefold() in reserved):
                candidate = Path(expected_file).with_name(
                    f"{Path(expected_file).stem} ({index}){Path(expected_file).suffix}"
                )
                index += 1
            expected_file = str(candidate)
            task.resolved_filename = expected_file
        task.expected_part_file = expected_file + ".part"

        # 2. 실제 다운로드
        opts = self._build_ytdlp_options(
            task,
            progress_callback=self._make_progress_callback(task),
            cookie_file=cookie_file,
        )

        opts["outtmpl"] = expected_file.replace("%", "%%")

        if chzzk_source:
            opts["hls_prefer_native"] = True
            opts["skip_unavailable_fragments"] = False
            logger.info(f"[{task_id}] CHZZK VOD CDN 선택: {task.cdn}")

        inspection_info: dict[str, Any] = {}

        def _download() -> str | None:
            with make_ydl(opts) as ydl:
                try:
                    result = ydl.process_ie_result(info, download=True)
                    # Merging/remuxing may change the extension. Use yt-dlp's
                    # final result rather than treating the pre-merge name as final.
                    for item in result.get("requested_downloads") or [result]:
                        inspection_info.update(item)
                        final_path = item.get("filepath")
                        if final_path and Path(final_path).is_file():
                            return final_path
                    return expected_file
                finally:
                    if selected_cdn == "akamai":
                        task.cdn_applied |= ydl.cdn_applied
                    if selected_cdn == "akamai" and (ydl.cdn_unsupported or not task.cdn_applied):
                        task.warning_message = "이 스트림의 CDN URL은 안전하게 변환할 수 없어 원래 주소를 사용했습니다."
                        task.download_warning_message = task.warning_message

        filepath: str | None = await asyncio.to_thread(lambda: _download())  # type: ignore[arg-type]
        task.metadata["expected_streams"] = [kind for kind, codec in (("video", "vcodec"), ("audio", "acodec"))
            if any(fmt.get(codec) not in (None, "none") for fmt in (inspection_info.get("requested_formats") or [inspection_info or info]))]

        if task.cancel_flag:
            raise DownloadCancelledError("다운로드가 취소되었습니다.")

        if filepath:
            filepath = str(Path(filepath).expanduser().resolve())
            if not Path(filepath).is_file():
                raise RuntimeError("yt-dlp가 완료했지만 출력 파일이 없습니다.")

            if chzzk_source:
                task.phase = "verifying"
                task.output_path = str(Path(filepath).absolute())
                task.state = VodDownloadState.COMPLETED
                task.completed_at = datetime.now()
                task.progress = 100.0
                await self._inspect_chzzk_download(task, inspection_info or info, filepath)
            if task.cancel_flag:
                raise DownloadCancelledError("다운로드가 취소되었습니다.")

            task.state = VodDownloadState.COMPLETED
            task.completed_at = task.completed_at or datetime.now()
            task.output_path = filepath
            task.resolved_filename = filepath
            task.progress = 100.0
            logger.info(f"[{task_id}] 다운로드 완료: {filepath}")
            self._save_history()

            try:
                file_size = Path(filepath).stat().st_size / (1024 * 1024)
            except OSError:
                file_size = 0.0
            duration = (
                (task.completed_at - task.started_at).total_seconds()
                if task.started_at and task.completed_at
                else 0
            )
            self._notify(
                NotificationKind.VOD_COMPLETED,
                title="📥 미디어 다운로드 완료",
                description=f"제목: **{task.title}**",
                color="green",
                fields={
                    "화질": task.quality,
                    "파일 크기": f"{file_size:.1f} MB",
                    "다운로드 시간": (
                        f"{duration // 60:.0f}분 {duration % 60:.0f}초"
                        if duration > 0
                        else "N/A"
                    ),
                    "저장 경로": filepath,
                },
            )
        else:
            task.state = VodDownloadState.ERROR
            task.error_message = "다운로드 결과를 확인할 수 없습니다."
            logger.error(f"[{task_id}] {task.error_message}")
            self._save_history()
            self._notify(
                NotificationKind.VOD_FAILED,
                title="❌ 미디어 다운로드 실패",
                description=f"제목: **{task.title or task.url}**",
                color="red",
                fields={"오류": task.error_message},
            )

    @staticmethod
    def _format_download_error(exc: Exception) -> str:
        """Keep yt-dlp failures useful when its exception has an empty message."""
        message = str(exc).strip()
        if message:
            return message
        return f"{type(exc).__name__}: 다운로드 도구가 상세 오류를 반환하지 않았습니다."

    @staticmethod
    async def _cleanup_partial_files(task: VodDownloadTask) -> bool:
        """Remove partial files before retrying, including transient Windows locks."""
        logger = get_media_logger(task.url)
        if not task.expected_part_file:
            return True
        expected_part = Path(task.expected_part_file)
        try:
            candidates = [expected_part]
            if expected_part.parent.is_dir():
                candidates.extend(
                    candidate
                    for candidate in expected_part.parent.iterdir()
                    if candidate.name.startswith(expected_part.name + "-Frag")
                    or candidate.name.startswith(expected_part.name + ".")
                )
        except OSError as exc:
            logger.warning(f"[{task.task_id}] 임시 다운로드 조각 파일 정리 실패: {exc}")
            return False

        cleanup_succeeded = True
        for candidate in set(candidates):
            if not candidate.is_file():
                continue
            for attempt in range(10):
                try:
                    await asyncio.to_thread(candidate.unlink, missing_ok=True)
                    break
                except PermissionError as exc:
                    if attempt == 9:
                        cleanup_succeeded = False
                        logger.warning(
                            f"[{task.task_id}] 임시 다운로드 조각 파일 정리 실패 "
                            f"(파일 잠금이 해제되지 않음): {exc}"
                        )
                    else:
                        await asyncio.sleep(min(0.25 * (2 ** attempt), 1.5))
                except OSError as exc:
                    cleanup_succeeded = False
                    logger.warning(f"[{task.task_id}] 임시 다운로드 조각 파일 정리 실패: {exc}")
                    break
        return cleanup_succeeded

    async def _inspect_chzzk_download(self, task: VodDownloadTask, info: dict, filepath: str) -> None:
        """Non-destructive checks: warnings do not turn a valid download into failure."""
        warnings = []
        task.inspection_state = "running"
        task.inspection_message = "파일 정보를 확인하고 있습니다."
        task.inspection_code = None
        task.inspection_diagnostics = {}
        self._save_history()
        try:
            try:
                task.file_size = await asyncio.to_thread(lambda: Path(filepath).stat().st_size)
            except OSError:
                task.file_size = None
            media = await asyncio.to_thread(self._probe_media_info, filepath)
            task.media_duration = media["duration"]
            task.file_size = media.get("size", task.file_size)
            task.inspection_diagnostics = media.get("diagnostics", {})
            task.inspection_diagnostics.update(format_name=media["format_name"], duration=media["duration"],
                                               streams=sorted(kind for kind in media["streams"] if isinstance(kind, str)),
                                               tracks=media.get("tracks", []))
            if task.inspection_diagnostics.get("stderr", "").strip():
                warnings.append("파일 검사 중 오류가 보고되었습니다. 상세 정보를 확인하세요.")
                get_media_logger(task.source_url).warning(f"[{task.task_id}] FFprobe stderr: {task.inspection_diagnostics['stderr']}")
            streams = media["streams"]
            if not media["format_name"] or not streams.intersection({"video", "audio"}):
                warnings.append("다운로드 파일의 미디어 컨테이너 또는 트랙을 확인하지 못했습니다.")
            formats = info.get("requested_formats") or (
                [info] if "vcodec" in info or "acodec" in info else info.get("formats") or [info]
            )
            for kind in ("video", "audio"):
                codec = "vcodec" if kind == "video" else "acodec"
                expected = kind in info.get("expected_streams", []) or any(fmt.get(codec) not in (None, "none") for fmt in formats)
                if expected and kind not in streams:
                    warnings.append(f"다운로드 파일에서 {'영상' if kind == 'video' else '음성'} 정보를 찾지 못했습니다.")
            try:
                expected_duration = float(info.get("duration") or 0)
            except (TypeError, ValueError):
                expected_duration = 0
            # Live/in-progress metadata is not a reliable comparison target.
            if (math.isfinite(expected_duration) and expected_duration > 0
                    and not info.get("is_live")
                    and info.get("live_status") not in ("is_live", "is_upcoming", "post_live")):
                tolerance = max(10.0, expected_duration * 0.02)
                if media["duration"] is not None and abs(media["duration"] - expected_duration) > tolerance:
                    warnings.append("다운로드한 영상의 재생 시간이 비정상적일 수 있습니다. Akamai CDN으로 다시 다운로드해 보세요.")
            if media["duration"] is None:
                warnings.append("파일의 재생 시간을 확인하지 못했습니다.")
            task.inspection_state = "attention" if warnings else "passed"
            task.inspection_code = "media_warning" if warnings else None
            task.inspection_message = " ".join(warnings) if warnings else "파일 검사 완료"
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            task.inspection_state = "failed"
            task.inspection_code = exc.code if isinstance(exc, InspectionError) else "probe_failed"
            task.inspection_message = str(exc) if isinstance(exc, InspectionError) else "파일 정보를 확인하지 못했습니다."
            task.inspection_diagnostics = exc.diagnostics if isinstance(exc, InspectionError) else {"detail": repr(exc)}
            warnings.append(task.inspection_message)
            get_media_logger(task.source_url).warning(f"[{task.task_id}] FFprobe inspection: {task.inspection_diagnostics}")
        finally:
            task.inspected_at = datetime.now()
        task.warning_message = " ".join(filter(None, [task.download_warning_message, *warnings])) or None
        self._save_history()
        if task.warning_message:
            get_media_logger(task.source_url).warning(f"[{task.task_id}] {task.warning_message}")

    @staticmethod
    def _probe_media_info(filepath: str) -> dict[str, Any]:
        """Compatibility entry point; callers run this in a worker thread."""
        return probe_media(filepath)

    @staticmethod
    def _probe_media_duration(filepath: str) -> float:
        return VodEngine._probe_media_info(filepath)["duration"]

    def reinspect_download(self, task_id: str) -> dict[str, Any]:
        """Schedule one inspection; status polling remains responsive during FFprobe."""
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError("작업을 찾을 수 없습니다.")
        if task.state != VodDownloadState.COMPLETED or not task.output_path:
            raise ValueError("다운로드가 완료된 파일만 검사할 수 있습니다.")
        if task.inspection_state == "running":
            raise ValueError("이미 파일을 검사하고 있습니다.")
        if task.download_task is not None and not task.download_task.done():
            raise ValueError("다운로드 작업 종료를 기다려 주세요.")
        if self._shutting_down:
            raise ValueError("서버가 종료 중입니다.")
        task.inspection_state = "running"
        task.inspection_message = "파일 정보를 확인하고 있습니다."
        future = asyncio.create_task(self._inspect_chzzk_download(task, task.metadata, task.output_path))
        task.inspection_task = future
        self._inspection_tasks.add(future)
        future.add_done_callback(self._inspection_tasks.discard)
        self._save_history()
        return self.get_task_status(task_id)

    def _clean_filename(self, name: str) -> str:
        """파일명에서 사용할 수 없는 특수문자를 제거한다."""
        from app.core.utils import clean_filename
        return clean_filename(name, max_length=100)

    def cancel_download(self, task_id: str) -> dict[str, Any]:
        """특정 다운로드를 취소한다."""
        logger = self._task_logger(task_id)
        task = self._tasks.get(task_id)
        if not task:
            return {"error": "작업을 찾을 수 없습니다.", "task_id": task_id}

        if task.state not in (VodDownloadState.DOWNLOADING, VodDownloadState.PAUSED):
            return {
                "error": "취소할 다운로드가 없습니다.",
                "state": task.state.value,
                "task_id": task_id,
            }

        logger.info(f"[{task_id}] 다운로드 취소 요청...")
        task.cancel_flag = True
        if task.process is not None and task.process.returncode is None:
            self._terminate_process(task.process)
        task.state = VodDownloadState.CANCELLING
        # 일시정지 중이면 해제해서 취소가 진행되도록
        task.pause_event.set()
        return {
            "message": "다운로드 취소 요청됨.",
            "state": task.state.value,
            "task_id": task_id,
        }

    def pause_download(self, task_id: str) -> dict[str, Any]:
        """특정 다운로드를 일시정지한다."""
        logger = self._task_logger(task_id)
        task = self._tasks.get(task_id)
        if not task:
            return {"error": "작업을 찾을 수 없습니다.", "task_id": task_id}

        if task.state != VodDownloadState.DOWNLOADING:
            return {
                "error": "일시정지할 다운로드가 없습니다.",
                "state": task.state.value,
                "task_id": task_id,
            }

        logger.info(f"[{task_id}] 다운로드 일시정지 요청...")
        task.pause_event.clear()  # progress callback에서 blocking
        task.state = VodDownloadState.PAUSED
        return {
            "message": "다운로드가 일시정지되었습니다.",
            "state": task.state.value,
            "task_id": task_id,
        }

    def resume_download(self, task_id: str) -> dict[str, Any]:
        """일시정지된 다운로드를 재개한다."""
        logger = self._task_logger(task_id)
        task = self._tasks.get(task_id)
        if not task:
            return {"error": "작업을 찾을 수 없습니다.", "task_id": task_id}

        if task.state != VodDownloadState.PAUSED:
            return {
                "error": "재개할 다운로드가 없습니다.",
                "state": task.state.value,
                "task_id": task_id,
            }

        logger.info(f"[{task_id}] 다운로드 재개 요청...")
        task.pause_event.set()  # progress callback 해제
        task.state = VodDownloadState.DOWNLOADING
        return {
            "message": "다운로드가 재개되었습니다.",
            "state": task.state.value,
            "task_id": task_id,
        }


    async def retry_download(self, task_id: str, cdn: str = "default") -> str:
        """완료/에러 상태의 작업을 재다운로드한다."""
        logger = self._task_logger(task_id)
        old_task = self._tasks.get(task_id)
        if not old_task:
            raise ValueError("작업을 찾을 수 없습니다.")

        previous_retry = self._tasks.get(old_task.retry_task_id or "")
        if previous_retry and (previous_retry.state in (VodDownloadState.IDLE, VodDownloadState.DOWNLOADING, VodDownloadState.PAUSED, VodDownloadState.CANCELLING)) and not previous_retry.cancel_flag:
            raise ValueError("이미 다시 다운로드하고 있습니다.")
        if old_task.inspection_state == "running":
            raise ValueError("파일 검사 종료를 기다려 주세요.")

        if old_task.state not in (VodDownloadState.COMPLETED, VodDownloadState.ERROR) and not (old_task.prepared and old_task.cancel_flag and old_task.state == VodDownloadState.IDLE):
            raise ValueError(f"재다운로드는 완료 또는 에러 상태에서만 가능합니다. 현재 상태: {old_task.state.value}")

        logger.info(f"[{task_id}] 재다운로드 요청 - URL: {old_task.url}, 화질: {old_task.quality}")

        # 기존 작업 정보를 기반으로 새 다운로드 시작
        new_task_id = await self.download(
            url=old_task.url,
            output_dir=old_task.output_dir,
            quality=old_task.quality,
            cdn=cdn,
        )
        old_task.retry_task_id = new_task_id
        self._save_history()

        if old_task.prepared and new_task_id in self._tasks:
            new_task = self._tasks[new_task_id]
            new_task.prepared = True
            new_task.metadata = dict(old_task.metadata)
            new_task.phase = "queued"
            self._save_history()

        logger.info(f"[{task_id}] → 새 작업 생성: {new_task_id}")
        return new_task_id

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        """특정 작업의 상태를 반환한다."""
        task = self._tasks.get(task_id)
        if not task:
            return {"error": "작업을 찾을 수 없습니다.", "task_id": task_id}

        return {
            "task_id": task.task_id,
            "url": task.url,
            "title": task.title,
            "state": task.state.value,
            "progress": round(task.progress, 1),
            "quality": task.quality,
            "prepared": task.prepared,
            "phase": "cancelled" if task.cancel_flag and task.state == VodDownloadState.IDLE else task.phase,
            "metadata": task.metadata,
            "cdn": task.cdn,
            "cdn_applied": task.cdn_applied,
            "warning_message": task.warning_message,
            "download_warning_message": task.download_warning_message,
            "inspection_state": task.inspection_state,
            "inspection_code": task.inspection_code,
            "inspection_message": task.inspection_message,
            "inspection_diagnostics": task.inspection_diagnostics,
            "inspected_at": task.inspected_at.isoformat() if task.inspected_at else None,
            "file_size": task.file_size,
            "retry_task_id": task.retry_task_id,
            "media_duration": task.media_duration,
            "output_path": task.output_path,
            "error_message": task.error_message,
            "created_at": task.created_at.isoformat(),
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            # 다운로드 통계
            "download_speed": round(task.download_speed, 2),  # MB/s
            "downloaded_bytes": task.downloaded_bytes,
            "total_bytes": task.total_bytes,
            "eta_seconds": task.eta_seconds,
        }

    def list_all_tasks(self) -> list[dict[str, Any]]:
        """모든 작업 목록을 반환한다."""
        return [self.get_task_status(tid) for tid in self._tasks.keys()]

    def reorder_tasks(self, task_ids: list[str]) -> dict[str, Any]:
        """작업 순서를 재정렬한다.

        Args:
            task_ids: 새로운 순서대로 정렬된 task_id 리스트

        Returns:
            성공 메시지 또는 에러
        """
        # 중복 ID는 dict 구성 중 다른 작업을 조용히 버리므로 변경 전에 거부한다.
        if len(set(task_ids)) != len(task_ids):
            return {"error": "작업 ID를 중복해서 지정할 수 없습니다."}
        # 모든 task_id가 유효한지 확인
        for tid in task_ids:
            if tid not in self._tasks:
                return {"error": f"존재하지 않는 작업 ID: {tid}"}

        # 제공된 task_ids와 현재 tasks의 개수가 일치하는지 확인
        if len(task_ids) != len(self._tasks):
            return {
                "error": f"작업 개수 불일치: 제공={len(task_ids)}, 현재={len(self._tasks)}"
            }

        # 새로운 순서로 재정렬
        new_tasks: dict[str, VodDownloadTask] = {}
        for tid in task_ids:
            new_tasks[tid] = self._tasks[tid]

        self._tasks = new_tasks
        self._save_history()
        logger.info(f"작업 순서 재정렬 완료: {len(task_ids)}개")

        return {"message": "작업 순서가 변경되었습니다.", "count": len(task_ids)}

    def clear_completed_tasks(self, completed_only: bool = False) -> dict[str, Any]:
        """대기, 완료, 에러 상태의 작업을 삭제하고 다운로드 중 작업은 보존한다.

        Returns:
            삭제된 작업 개수 및 메시지
        """
        clearable_states = {
            VodDownloadState.IDLE,
            VodDownloadState.COMPLETED,
            VodDownloadState.ERROR,
        }
        if completed_only:
            clearable_states = {VodDownloadState.COMPLETED}
        removed_tasks = [
            task for task in self._tasks.values() if task.state in clearable_states
            and task.inspection_state != "running"
            and (task.download_task is None or task.download_task.done() or task.started_at is None)
        ]

        for task in removed_tasks:
            if task.state == VodDownloadState.IDLE and task.started_at is None:
                # IDLE tasks are queued behind the concurrency semaphore. Cancel
                # their waiter so removing them also removes their queued coroutine.
                task.cancel_flag = True
                task.pause_event.set()
                if task.download_task is not None and not task.download_task.done():
                    task.download_task.cancel()

        removed_ids = {task.task_id for task in removed_tasks}
        self._tasks = {tid: task for tid, task in self._tasks.items() if tid not in removed_ids}

        deleted_count = len(removed_tasks)
        # Persist the removal as well as updating the UI's in-memory task list.
        self._save_history()

        logger.info(f"다운로드 작업 정리: {deleted_count}개 삭제됨")

        return {
            "message": f"{deleted_count}개의 대기/완료/오류 작업이 삭제되었습니다.",
            "deleted_count": deleted_count,
            "remaining_count": len(self._tasks),
        }

    async def shutdown(self) -> None:
        """Stop producing work and drain downloads before the database closes.

        yt-dlp threads cannot be killed safely. Signal their progress hooks and
        wait for them; network timeout/retry settings may delay shutdown.
        """
        self._shutting_down = True
        await asyncio.gather(*list(self._inspection_tasks), return_exceptions=True)
        await asyncio.gather(*list(self._metadata_tasks), return_exceptions=True)
        imports = list(self.channel_imports.tasks.values())
        for job_id in list(self.channel_imports.tasks):
            self.channel_imports.cancel(job_id)
        await asyncio.gather(*imports, return_exceptions=True)
        pending = []
        for task in self._tasks.values():
            if task.download_task is None or task.download_task.done():
                continue
            if task.state == VodDownloadState.COMPLETED:
                pending.append(task.download_task)
                continue
            task.cancel_flag = True
            task.pause_event.set()
            if task.process is not None and task.process.returncode is None:
                self._terminate_process(task.process)
            pending.append(task.download_task)
        await asyncio.gather(*pending, return_exceptions=True)
        for task in self._tasks.values():
            if task.prepared and task.cancel_flag and task.state == VodDownloadState.IDLE and (task.download_task is None or task.download_task.done()):
                continue  # Already cancelled by the user, not interrupted by shutdown.
            if task.cancel_flag and task.state not in (VodDownloadState.COMPLETED, VodDownloadState.ERROR):
                task.state = VodDownloadState.ERROR
                task.error_message = "서버 종료로 중단되었습니다. 다시 시도해 주세요."
        self._save_history()

    def open_file_location(self, task_id: str) -> dict[str, Any]:
        """작업의 출력 파일 위치를 탐색기로 엽니다.

        Args:
            task_id: 작업 ID

        Returns:
            성공/실패 메시지
        """
        logger = self._task_logger(task_id)
        task = self._tasks.get(task_id)
        if not task:
            return {"error": "작업을 찾을 수 없습니다."}

        if not task.output_path:
            return {"error": "출력 파일 경로가 없습니다."}

        output_file = Path(task.output_path)
        if not output_file.exists():
            return {"error": "파일이 존재하지 않습니다."}

        # OS별로 파일 탐색기 열기
        import platform
        import subprocess

        try:
            system = platform.system()
            if system == "Windows":
                # Windows: explorer /select,"파일경로"
                subprocess.run(["explorer", "/select,", str(output_file)], check=False)
            elif system == "Darwin":  # macOS
                # macOS: open -R "파일경로"
                subprocess.run(["open", "-R", str(output_file)], check=False)
            else:  # Linux / Termux / headless
                import os
                if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
                    return {"message": "헤드리스 서버에서는 표시된 저장 경로를 사용하세요.", "path": str(output_file)}
                result = subprocess.run(["xdg-open", str(output_file.parent)], check=False, timeout=10)
                if result.returncode:
                    return {"error": "파일 관리자를 열지 못했습니다.", "path": str(output_file)}

            logger.info(f"[{task_id}] 파일 위치 열기: {output_file}")
            return {"message": "파일 위치를 열었습니다.", "path": str(output_file)}

        except Exception as e:
            logger.error(f"[{task_id}] 파일 위치 열기 실패: {e}")
            return {"error": f"파일 위치를 열 수 없습니다: {str(e)}"}

    def get_status(self) -> dict[str, Any]:
        """하위 호환성을 위한 메서드. 첫 번째 작업의 상태 반환."""
        if not self._tasks:
            return {
                "state": VodDownloadState.IDLE.value,
                "progress": 0.0,
                "title": None,
            }

        first_task = next(iter(self._tasks.values()))
        return {
            "state": first_task.state.value,
            "progress": round(first_task.progress, 1),
            "title": first_task.title,
        }

    @staticmethod
    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        """ISO 문자열을 datetime으로 되돌린다. 깨져 있으면 None."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    def _load_history(self) -> None:
        """저장소에서 완료/에러 상태의 작업을 복원한다."""
        try:
            records = self._repo.list_all()
        except Exception as e:
            logger.warning(f"다운로드 이력 로드 실패: {e}")
            return

        restored = 0
        for record in records:
            prepared_idle = record.get("prepared") and record.get("state") == "idle" and record.get("phase") in {"ready", "metadata", "metadata_error", "cancelled"}
            interrupted = not prepared_idle and record.get("state") in {"idle", "downloading", "paused", "cancelling"}
            if record.get("state") not in ("completed", "error") and not interrupted and not prepared_idle:
                continue
            try:
                task = VodDownloadTask(
                    task_id=record["task_id"],
                    url=record["url"],
                    title=record.get("title"),
                    state=VodDownloadState.ERROR if interrupted else VodDownloadState(record["state"]),
                    progress=record.get("progress") or 0.0,
                    quality=record.get("quality") or "best",
                    prepared=bool(record.get("prepared", False)),
                    phase="metadata_error" if record.get("phase") == "metadata" else record.get("phase") or "queued",
                    metadata=record.get("metadata") or {},
                    cancel_flag=record.get("phase") == "cancelled",
                    cdn=record.get("cdn") if record.get("cdn") in ("default", "akamai") else "default",
                    cdn_applied=bool(record.get("cdn_applied", False)),
                    warning_message=record.get("warning_message"),
                    download_warning_message=record.get("download_warning_message"),
                    inspection_state=("pending" if record.get("inspection_state") == "running" else record.get("inspection_state") or ("attention" if record.get("warning_message") else "pending")),
                    inspection_code=record.get("inspection_code"),
                    inspection_message=record.get("inspection_message") if record.get("inspection_state") != "running" else "파일 검사가 중단되었습니다. 다시 검사를 시도할 수 있습니다.",
                    inspection_diagnostics=record.get("inspection_diagnostics") or {},
                    inspected_at=self._parse_dt(record.get("inspected_at")),
                    file_size=record.get("file_size"),
                    retry_task_id=record.get("retry_task_id"),
                    media_duration=record.get("media_duration"),
                    output_dir=record.get("output_dir") or "",
                    output_path=record.get("output_path"),
                    error_message="서버가 중단된 작업입니다. 다시 시도해 주세요." if interrupted else record.get("error_message"),
                    created_at=self._parse_dt(record.get("created_at")) or datetime.now(),
                    started_at=self._parse_dt(record.get("started_at")),
                    completed_at=self._parse_dt(record.get("completed_at")),
                )
            except Exception as e:
                # 한 건이 깨져도 나머지 이력은 살린다.
                logger.warning(f"다운로드 이력 항목 복원 실패 ({record.get('task_id')}): {e}")
                continue
            self._tasks[task.task_id] = task
            restored += 1

        if restored:
            logger.info(f"다운로드 이력 로드 완료: {restored}개")

    def _save_history(self) -> None:
        """완료/에러 상태의 작업을 저장소에 반영한다."""
        try:
            records = {
                task.task_id: {
                    "url": task.url,
                    "title": task.title,
                    "state": task.state.value,
                    "progress": task.progress,
                    "quality": task.quality,
                    "prepared": task.prepared,
                    "phase": "cancelled" if task.cancel_flag and task.state == VodDownloadState.IDLE else task.phase,
                    "metadata": task.metadata,
                    "cdn": task.cdn,
                    "cdn_applied": task.cdn_applied,
                    "warning_message": task.warning_message,
                    "download_warning_message": task.download_warning_message,
                    "inspection_state": task.inspection_state,
                    "inspection_code": task.inspection_code,
                    "inspection_message": task.inspection_message,
                    "inspection_diagnostics": task.inspection_diagnostics,
                    "inspected_at": task.inspected_at.isoformat() if task.inspected_at else None,
                    "file_size": task.file_size,
                    "retry_task_id": task.retry_task_id,
                    "media_duration": task.media_duration,
                    "output_dir": task.output_dir,
                    "output_path": task.output_path,
                    "error_message": task.error_message,
                    "created_at": task.created_at.isoformat(),
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                }
                for task in self._tasks.values()
            }
            # 취소/삭제된 작업까지 반영해야 하므로 전체 교체한다.
            # 완료 작업은 보통 수십 건 수준이라 비용이 문제되지 않는다.
            self._repo.replace_all(records)
            logger.debug(f"다운로드 이력 저장 완료: {len(records)}개")
        except Exception as e:
            logger.warning(f"다운로드 이력 저장 실패: {e}")
