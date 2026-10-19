"""Resolve live HLS and write Streamlink packets directly; remux only after closing."""

from __future__ import annotations

import asyncio
import os
import asyncio.subprocess
import mimetypes
import re
import tempfile
import uuid
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Awaitable
from urllib.parse import urlsplit, urlunsplit

from app.core.config import get_settings
from app.core.logger import logger, get_media_logger
from app.engine.chzzk_time_machine import (
    resolve_time_machine_stream,
    resolve_live_cdn_stream,
)
from app.engine.youtube_support import is_youtube_url, require_runtime_cli_options, youtube_extractor_command

from app.engine.pipeline.state import RecordingState
from app.engine.recording_errors import RecordingError, classify_recording_error


class YtdlpLivePipeline:
    """Resolve live URLs, receive native Streamlink media and close writers.

    Container conversion belongs exclusively to RecordingFinalizer.
    """

    # quality 문자열 → yt-dlp format 문자열 매핑
    STOP_COOPERATIVE_SECONDS = 15
    STOP_FORCE_SECONDS = 5
    STOP_DRAIN_SECONDS = 10
    _QUALITY_MAP: dict[str, str] = {
        "best": "best",
        "1080p": "best[height<=1080]/best",
        "720p": "best[height<=720]/best",
        "480p": "best[height<=480]/best",
    }

    def __init__(self, channel_id: str) -> None:
        self._channel_id = channel_id
        self._logger = logger.getChild("recording")
        self._state = RecordingState.IDLE
        self._process: Optional[asyncio.subprocess.Process] = None
        self._streamlink_fd: Optional[object] = None
        self._streamlink_session: Optional[object] = None
        self._feeder_task: Optional[asyncio.Task[None]] = None
        self._output_path: Optional[str] = None
        self._start_time: Optional[datetime] = None
        self._intentional_stop = False
        self._force_stop = threading.Event()
        self._stop_task = None
        self.output_errors = []
        self.continuity_buffer = None
        self._source_resolver = None
        self._dash_source = None
        self._dash_resume = {}
        self._dash_received = set()
        self._dash_duration_base = 0.0
        self.recording_resolution = None
        self._source_page_url = ""
        self._cookie_str = None
        self._closed = True
        self._ended_at = None
        self._readers = []
        self._source_files = []
        self._sequential_sources = False
        self._resume_args = None
        self._quality = "best"
        self.end_reason = None
        self.session_id = uuid.uuid4().hex
        self.retryable = True
        self.error_code = None
        self.error_message = None
        self._capture_ready = None
        self._last_data_at = None
        self._media_duration = None
        self._pcr_last = None
        self._ts_tail = b""
        self.capture_format = "ts"
        self.cdn = None
        self.warning_message = None
        self.continuity_resume = None
        self.continuity_source = {}
        self.continuity_events = []
        self._continuity_active = False
        from app.engine.recording_loss import RecordingLossReport
        self._loss_report = RecordingLossReport()
        self.losscheck_path = None
        from app.engine.native_clock import NativeClock

        self._native_clock = NativeClock()

        # 녹화 통계 (FFmpegPipeline과 동일 구조)
        self._file_size_bytes: int = 0
        self._download_speed: float = 0.0
        self._bitrate: float = 0.0
        self._last_size: int = 0
        self._last_check_time: Optional[datetime] = None
        self._speed_samples = []
        self._speed_window_seconds = 0.0

    @property
    def state(self) -> RecordingState:
        return self._state

    @property
    def channel_id(self) -> str:
        return self._channel_id

    @property
    def output_path(self) -> Optional[str]:
        return self._output_path

    @property
    def preview_source_url(self) -> Optional[str]:
        """Reuse only an active CHZZK or YouTube source that this capture has already received."""
        if self._dash_source:
            return None
        if (self._state not in (RecordingState.RECORDING, RecordingState.RECONNECTING)
                or self._start_time is None or self._closed or not self._resume_args):
            return None
        if is_youtube_url(self._source_page_url):
            from app.engine.preview_proxy import PreviewProxy
            url = self._resume_args[0] if self._resume_args else None
            if url and PreviewProxy.allowed(url, set(), "youtube"):
                return url
        if not self._is_chzzk_live_page(self._source_page_url):
            return None
        from app.engine.chzzk_stream import trusted_media_url
        reader = self._readers[0] if self._readers else None
        continuity = getattr(getattr(reader, 'stream', None), 'continuity', None)
        current = getattr(getattr(continuity, 'primary', None), 'url', None)
        for url in (current, self._resume_args[0]):
            if trusted_media_url(url):
                return url
        return None

    @property
    def duration_seconds(self) -> float:
        start = self._start_time
        if start is None:
            return 0.0
        if self._media_duration is not None:
            return self._media_duration
        return max(0, ((self._last_data_at or start) - start).total_seconds())

    @property
    def file_size_bytes(self) -> int:
        return self._file_size_bytes

    @property
    def download_speed(self) -> float:
        return self._download_speed

    @property
    def bitrate(self) -> float:
        return self._bitrate

    async def start_recording(
        self,
        stream_obj: Optional[object] = None,  # str URL (FFmpegPipeline 호환 시그니처)
        output_dir: Optional[str] = None,
        filename: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        streamer_name: Optional[str] = None,
        title: Optional[str] = None,
        category: Optional[str] = None,
        live_started_at: Optional[str] = None,
        quality: str = "best",
        cookie_str: Optional[str] = None,
        fallback_cookie_file: Optional[str] = None,
        thumbnail_url: Optional[str] = None,
        source_resolver: Optional[
            Callable[[str], Awaitable[tuple[str, dict, Optional[str]]]]
        ] = None,
    ) -> str:
        """Save Streamlink packets, remuxing TikTok FLV to TS without encoding.

        Args:
            stream_obj: 라이브 URL 문자열 (예: https://chzzk.naver.com/live/{id})
            output_dir: 저장 디렉토리. None이면 settings.download_dir 사용.
            filename: 파일명. None이면 자동 생성.
            streamer_name: 파일명 자동 생성 시 사용할 채널명.
            title: 파일명 자동 생성 시 사용할 방송 제목.
            quality: 화질 ("best", "1080p", "720p", "480p").
            cookie_str: Chzzk 쿠키 문자열 (NID_AUT=...; NID_SES=...).
            fallback_cookie_file: 쿠키 없이 URL 추출에 실패했을 때만 쓰는 로그인 쿠키
                파일. 빌려받은 사본이며 지우는 건 빌려준 쪽 몫이다.

        Returns:
            출력 파일 경로.
        """
        if self._state == RecordingState.RECORDING:
            self._logger.warning(f"[{self._channel_id}] 이미 녹화 중입니다.")
            return self._output_path or ""

        self._intentional_stop = False
        page_url = str(stream_obj) if stream_obj else ""
        self._source_resolver = source_resolver
        self._source_page_url = page_url
        if page_url:
            self._logger = get_media_logger(page_url).getChild("recording")
        settings = get_settings()
        live_start_index: Optional[int] = None

        save_dir = (
            Path(output_dir or settings.effective_live_download_dir)
            .expanduser()
            .resolve()
        )
        save_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        live_date = now
        if live_started_at:
            try:
                live_date = datetime.fromisoformat(
                    live_started_at.replace("Z", "+00:00")
                )
            except ValueError:
                self._logger.warning(
                    f"[{self._channel_id}] 라이브 시작 시각을 읽지 못해 현재 시각을 파일명에 사용합니다."
                )
        ext = "ts"
        if ext not in {"ts", "mkv", "mp4"}:
            ext = "ts"
        if not filename:

            def date_values(prefix: str, value: datetime) -> dict[str, str]:
                return {
                    f"{prefix}date": value.strftime("%Y%m%d%H%M%S"),
                    f"{prefix}date_year": value.strftime("%Y"),
                    f"{prefix}date_year_full": value.strftime("%Y"),
                    f"{prefix}date_year_short": value.strftime("%y"),
                    f"{prefix}date_month": value.strftime("%m"),
                    f"{prefix}date_month_full": value.strftime("%B"),
                    f"{prefix}date_month_short": value.strftime("%b"),
                    f"{prefix}date_day": value.strftime("%d"),
                    f"{prefix}date_hour": value.strftime("%H"),
                    f"{prefix}date_minute": value.strftime("%M"),
                    f"{prefix}date_second": value.strftime("%S"),
                }

            values = {
                "channel_name": streamer_name or self._channel_id,
                "channel_uid": self._channel_id,
                "verified": "",
                "title": title or "live",
                "category": category or "",
                "category_value": category or "",
                "category_type": "",
                "date_time": now.strftime("%Y-%m-%d %H-%M"),
                "year": now.strftime("%Y"),
                "month": now.strftime("%m"),
                "day": now.strftime("%d"),
                "hour": now.strftime("%H"),
                "minute": now.strftime("%M"),
                "second": now.strftime("%S"),
                "quality": quality,
                "extension": f".{ext}",
            }
            values.update(
                {
                    "name": values["channel_name"],
                    "live_title": values["title"],
                    "live_date_year": values["year"],
                    "live_date_month": values["month"],
                    "live_date_day": values["day"],
                    "live_date_hour": values["hour"],
                    "live_date_minute": values["minute"],
                    "live_date_second": values["second"],
                    "record_quality": values["quality"],
                    "file_extension": values["extension"],
                }
            )
            values.update(date_values("", now))
            values.update(date_values("live_", live_date))
            values.update(date_values("download_", now))
            default_template = "[{name}] {title} {live_date_year}-{live_date_month}-{live_date_day} {live_date_hour}-{live_date_minute}-{live_date_second}"
            template = settings.live_filename_template or default_template
            try:
                filename = template.format(**values)
            except (KeyError, ValueError, IndexError) as exc:
                self._logger.warning(
                    f"[{self._channel_id}] 파일명 형식이 잘못되어 기본 형식을 사용합니다: {exc}"
                )
                filename = default_template.format(**values)
            filename = self._clean_filename(filename) or self._channel_id
            if not filename.lower().endswith(f".{ext}".lower()):
                filename += f".{ext}"

        # 같은 채널/제목이 같은 분 안에 재시작되더라도 기존 파일을 덮어쓰지 않는다.
        filename = self._clean_filename(filename)
        stem = (
            Path(filename).stem.encode("utf-8")[:160].decode("utf-8", errors="ignore")
        )
        if os.name == "nt":
            budget = (
                240
                - len(str(save_dir))
                - len(" (999999).native.mp4.part")
            )
            if budget < 1:
                raise RecordingError(
                    "storage_path",
                    "저장 폴더 경로가 너무 깁니다. 더 짧은 경로를 선택하세요.",
                )
            stem = stem[:budget]
        filename = f"{stem}.ts"
        output_file = save_dir / filename
        self._output_path = str(output_file)

        # ── Phase 1: 타임머신 또는 yt-dlp에서 HLS URL + HTTP 헤더 추출 ──
        # 로그인 쿠키는 실패했을 때만 쓴다. 지금 되는 녹화는 그대로 두고,
        # 로그인 전용 라이브만 한 번 더 시도한다. yt-dlp가 로그인 요구를 여러 문구로
        # 알려서 문구로 가려내지 않고 추출 실패면 모두 다시 시도한다.
        stream_cookies: Optional[str] = None
        stream_mode = settings.effective_chzzk_stream_mode
        time_machine_resolved = False
        if stream_mode != "standard" and self._is_chzzk_live_page(page_url):
            try:
                time_machine_stream = await resolve_time_machine_stream(
                    channel_id=self._channel_id,
                    quality=quality,
                    offset_seconds=settings.effective_chzzk_time_machine_offset,
                    cookie_header=cookie_str,
                    cdn=settings.chzzk_live_cdn,
                )
                self.cdn = getattr(time_machine_stream, "cdn", None)
                self.warning_message = getattr(time_machine_stream, "warning", None)
                hls_url = (
                    getattr(time_machine_stream, "master_url", None)
                    or time_machine_stream.url
                )
                http_headers = time_machine_stream.headers
                live_start_index = time_machine_stream.live_start_index
                time_machine_resolved = True
                self._logger.info(
                    f"[{self._channel_id}] 치지직 타임머신 스트림 연결 "
                    f"(시작 오프셋={settings.effective_chzzk_time_machine_offset}초, "
                    f"시작 인덱스={live_start_index if live_start_index is not None else '기본'})"
                )
            except Exception as e:
                if stream_mode == "force-timemachine":
                    self._state = RecordingState.ERROR
                    raise RuntimeError(
                        f"[{self._channel_id}] 타임머신 스트림을 가져오지 못해 강제 녹화를 시작하지 못했습니다: {e}"
                    ) from e
                self._logger.warning(
                    f"[{self._channel_id}] 타임머신 스트림을 사용할 수 없어 일반 스트림으로 전환합니다: {e}"
                )

        if source_resolver is not None:
            try:
                hls_url, http_headers, stream_cookies = await asyncio.wait_for(
                    source_resolver(quality), timeout=45
                )
            except BaseException:
                self._state = RecordingState.ERROR
                raise
        elif not time_machine_resolved:
            try:
                if self._is_chzzk_live_page(page_url):
                    selected_cdn = settings.chzzk_live_cdn

                    async def resolve_chzzk(selected_quality):
                        stream = await resolve_live_cdn_stream(
                            self._channel_id, selected_quality, cookie_str, selected_cdn
                        )
                        self.cdn, self.warning_message = stream.cdn, stream.warning
                        return stream.url, stream.headers, None

                    self._source_resolver = resolve_chzzk
                    hls_url, http_headers, stream_cookies = await resolve_chzzk(quality)
                else:
                    hls_url, http_headers, _ = await self._extract_hls_url(
                        page_url, quality, cookie_str
                    )
            except Exception as e:
                if not fallback_cookie_file:
                    self._state = RecordingState.ERROR
                    raise
                self._logger.warning(
                    f"[{self._channel_id}] 쿠키 없이 URL 추출 실패, 로그인 쿠키로 다시 시도: {e}"
                )
                try:
                    hls_url, http_headers, stream_cookies = await self._extract_hls_url(
                        page_url, quality, None, cookie_file=fallback_cookie_file
                    )
                except Exception:
                    self._state = RecordingState.ERROR
                    raise

        # Streamlink writes source packets directly. No FFmpeg process or pipe.
        self._quality = quality
        self._cookie_str = cookie_str
        self._closed = False
        self._ended_at = None
        self.end_reason = None
        self._start_time = None
        self._state = RecordingState.CONNECTING
        self._source_files = [str(output_file) + ".part"]
        self._resume_args = (
            hls_url,
            http_headers,
            stream_cookies,
            (
                settings.effective_chzzk_time_machine_offset
                if time_machine_resolved
                else 0
            ),
            time_machine_resolved,
            quality,
        )
        try:
            # Reserve after URL resolution. Concurrent sessions compete through
            # exclusive creation, then use readable suffixes instead of UUIDs.
            output_file = self._reserve_capture_file(output_file)
            self._output_path = str(output_file)
            self._source_files = [str(output_file) + ".part"]
            for attempt in range(2):
                self._intentional_stop = False
                try:
                    await self._begin_receiver()
                    break
                except Exception as error:
                    if (
                        attempt
                        or self._start_time is not None
                        or not classify_recording_error(error).retryable
                    ):
                        raise
                    if self._source_resolver:
                        url, headers, cookies = await asyncio.wait_for(
                            self._source_resolver(quality), 45
                        )
                    else:
                        url, headers, cookies = await self._extract_hls_url(
                            page_url, quality, cookie_str
                        )
                    self._resume_args = (url, headers, cookies, *self._resume_args[3:])
            if (
                settings.save_live_preview
                and thumbnail_url
                and self._is_chzzk_live_page(page_url)
            ):
                await self._save_live_preview(thumbnail_url, output_file)
            return self._output_path
        except BaseException:
            self._state = RecordingState.ERROR
            self._closed = True
            raise

    @staticmethod
    def _reserve_capture_file(base: Path) -> Path:
        """Reserve a human-readable capture name without replacing any file."""
        family = ('.ts', '.ts.part', '.native.mp4', '.native.mp4.part',
                  '.native.ts', '.native.mkv', '.mkv', '.mp4',
                  '.ts.audio1', '.ts.audio1.part', '.native.mp4.audio1', '.native.mp4.audio1.part',
                  '.jpg', '.jpeg', '.png', '.webp', '.avif')
        number = 1
        while True:
            stem = base.stem if number == 1 else f"{base.stem} ({number})"
            candidate = base.with_name(stem + base.suffix)
            if any(base.with_name(stem + suffix).exists() for suffix in family):
                number += 1
                continue
            try:
                with Path(str(candidate) + '.part').open('xb'):
                    pass
                return candidate
            except FileExistsError:
                number += 1

    def _ensure_start_allowed(self):
        guard = getattr(self, "_start_guard", None)
        if guard is not None and not guard():
            raise RecordingError(
                "auto_record_disabled", "자동 녹화가 꺼져 연결 시도를 중단했습니다."
            )

    async def _begin_receiver(self):
        self._ensure_start_allowed()
        preview_capture = None
        if (urlsplit(self._source_page_url).hostname or '').lower() in ('tiktok.com','www.tiktok.com','m.tiktok.com'):
            from app.engine.tiktok import normalize_tiktok_channel_id
            from app.engine.tiktok_preview import register_capture
            from app.engine.preview_frames import frame_previews
            channel = normalize_tiktok_channel_id(self._source_page_url)
            preview_capture = register_capture(channel)
            self._tiktok_preview_capture = preview_capture
        try:
            if preview_capture:
                # 먼저 공유 입력을 예약해 새 미리보기 접속을 막고, 진행 중인 한 장의 입력을 닫는다.
                await frame_previews.finish_current_frame('tiktok:'+channel)
            self._ensure_start_allowed()
            session, readers = await self._open_raw_readers(*self._resume_args)
        except BaseException:
            if preview_capture:
                preview_capture.close()
            raise
        try:
            self._ensure_start_allowed()
        except RecordingError:
            for reader in readers:
                await asyncio.to_thread(reader.close)
            await asyncio.to_thread(session.http.close)
            raise
        self._streamlink_session, self._readers = session, readers
        if self._dash_source:
            self._dash_received.clear()
            self._dash_duration_base = self._media_duration or 0.0
            if self.capture_format != "youtube_dash":
                from app.engine.recording_finalizer import publish_file
                video = self._dash_source[0]
                suffix = ".native.webm" if video.get("ext") == "webm" else ".native.mp4"
                native = str(Path(self._output_path).with_suffix(suffix))
                publish_file(Path(self._source_files[0]), Path(native + ".part"))
                self._output_path = native
                self._source_files[0] = native + ".part"
            self.capture_format = "youtube_dash"
        if readers and getattr(readers[0], 'capture_format', None) == 'h264':
            self.capture_format = 'h264'
        self._continuity_active = any(getattr(getattr(r, 'stream', None), 'continuity', None) for r in readers)
        while len(self._source_files) < len(readers):
            self._source_files.append(
                self._output_path + f".audio{len(self._source_files)}.part"
            )
        self._closed = False
        self._capture_ready = asyncio.get_running_loop().create_future()
        self._stall_detected = False
        self._feeder_task = asyncio.create_task(
            self._receive_packets(), name=f"streamlink-record-{self._channel_id}"
        )
        asyncio.create_task(self._update_statistics_loop())
        try:
            while True:
                try:
                    await asyncio.wait_for(asyncio.shield(self._capture_ready), 45)
                    break
                except asyncio.TimeoutError:
                    if not self._twitch_ad_waiting():
                        raise
        except BaseException:
            self._intentional_stop = True
            for reader in list(self._readers):
                await asyncio.to_thread(reader.close)
            await asyncio.gather(self._feeder_task, return_exceptions=True)
            if self._capture_ready.done() and not self._capture_ready.cancelled():
                self._capture_ready.exception()
            raise

    def _capture_started(self):
        if self._capture_ready.done():
            return
        try:
            self._update_statistics()
            if getattr(self, "_on_capture_started", None):
                self._on_capture_started(self)
                self._on_capture_started = None
            if self.output_errors:
                self._capture_ready.set_exception(self.last_exception)
                return
            self._state = RecordingState.RECORDING
            self.error_code = None
            self.error_message = None
            self.end_reason = None
            if not self._capture_ready.done():
                self._capture_ready.set_result(True)
        except Exception as error:
            self._intentional_stop = True
            if not self._capture_ready.done():
                self._capture_ready.set_exception(error)

    def _accept_continuity_event(self, event):
        from app.engine.chzzk_continuity_events import EVENT_PREFIX, parse_event
        import json
        safe = parse_event(EVENT_PREFIX + json.dumps(event))
        if safe is None:
            return
        self.continuity_events.append(safe)
        del self.continuity_events[:-64]
        kind = safe['kind']
        if kind == 'source':
            role = 'selected' if safe['state'] == 'selected' else 'standby'
            self.continuity_source[role] = {k: safe[k] for k in ('cdn', 'mode', 'state')}
            if role == 'selected':
                self.cdn = 'akamai' if safe['cdn'] == 'akamai' else 'default'
        elif kind == 'recovery_started' and self._state == RecordingState.RECORDING:
            if self._last_data_at is None or (datetime.now() - self._last_data_at).total_seconds() > 5.0:
                self._state = RecordingState.RECONNECTING
        elif kind == 'recovery_completed' and self._state == RecordingState.RECONNECTING:
            self._state = RecordingState.RECORDING
        elif kind == 'gap':
            self._loss_report.gap(safe)
            self.warning_message = '복구하지 못한 녹화 구간이 있습니다. 원본을 구간별 파일로 보관합니다.'
        self._logger.debug(f"[{self._channel_id}] 치지직 수신 상태: {json.dumps(safe, ensure_ascii=False)}")

    def _measure_ts(self, data):
        """Measure the MPEG-TS PCR clock without decoding or invoking FFmpeg."""
        data = self._ts_tail + data
        limit = len(data) // 188 * 188
        for pos in range(0, limit, 188):
            if data[pos] != 0x47:
                continue
            if (data[pos + 3] >> 4) & 2 and data[pos + 4] >= 7 and data[pos + 5] & 0x10:
                p = data[pos + 6 : pos + 12]
                clock = (
                    (p[0] << 25)
                    | (p[1] << 17)
                    | (p[2] << 9)
                    | (p[3] << 1)
                    | (p[4] >> 7)
                )
                if self._pcr_last is not None:
                    delta = (clock - self._pcr_last) % (1 << 33) / 90000
                    if delta < 60:
                        self._media_duration = (self._media_duration or 0) + delta
                self._pcr_last = clock
        self._ts_tail = data[limit:]

    async def _open_raw_readers(self, *args):
        loop = asyncio.get_running_loop()
        def open_sources():
            if self._dash_source:
                from app.engine.youtube_dash import open_dash
                return open_dash(self._dash_source, self._dash_resume,
                                 get_settings().youtube_time_machine_enabled)
            session, stream = self._create_streamlink_stream(
                *args, source_page_url=self._source_page_url,
                continuity_resume=self.continuity_resume,
                continuity_callback=lambda event: loop.call_soon_threadsafe(self._accept_continuity_event, event),
                api_cookie=self._cookie_str,
                continuity_buffer_dir=self._buffer_directory(),
                loss_report=self._loss_report,
                **({'preview_capture': self._tiktok_preview_capture} if getattr(self, '_tiktok_preview_capture', None) else {}),
            )
            readers = []
            try:
                for index, source in enumerate(getattr(stream, "substreams", None) or [stream]):
                    source._phrolova_track_id = str(index)
                    readers.append(source.open())
                return session, readers
            except BaseException:
                for reader in readers:
                    reader.close()
                session.http.close()
                raise

        worker = asyncio.create_task(asyncio.to_thread(open_sources))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            try:
                session, readers = await worker
                for reader in readers:
                    await asyncio.to_thread(reader.close)
                await asyncio.to_thread(session.http.close)
            except Exception:
                pass
            raise

    async def _receive_packets(self):
        readers = list(self._readers)
        loop = asyncio.get_running_loop()
        receivers = ThreadPoolExecutor(max_workers=max(1, len(readers)), thread_name_prefix="recording-read")

        async def receive(index, reader):
            def copy_packets():
                checked = False
                prefix = bytearray()
                source_index = -1 if self._sequential_sources and index == 0 else index
                file = open(self._source_files[source_index], "ab")
                last_flush = time.monotonic()
                try:
                    # Stop the producer first, then read through EOF. Accepted
                    # RingBuffer bytes belong to the completed media segment.
                    while not self._force_stop.is_set():
                        data = reader.read(128 * 1024)
                        if not data:
                            if self._intentional_stop:
                                return False
                            if index == 0 and prefix and not checked:
                                raise RecordingError(
                                    "unsupported_container",
                                    "선택된 스트림의 원본 형식을 확인할 수 없습니다.",
                                )
                            continuity = getattr(getattr(reader, 'stream', None), 'continuity', None)
                            boundary = getattr(continuity, 'boundary_event', None)
                            if boundary and boundary.get('reason') != 'broadcast_ended':
                                resume_from = boundary.get('resume_from')
                                if resume_from and self._start_time is not None:
                                    self.continuity_resume = {
                                        'live_id': boundary['live_id'], 'rendition': boundary['rendition'],
                                        'from': resume_from, 'after_gap': boundary.get('after_gap', False),
                                    }
                                    if boundary.get('recovery_deadline'):
                                        self.continuity_resume['recovery_deadline'] = boundary['recovery_deadline']
                                    self.end_reason = 'continuity_boundary'
                                    return True
                                raise RecordingError('continuity_gap', '필요한 녹화 구간을 복구하지 못했습니다. 저장된 원본을 확인하고 다시 시작하세요.')
                            if continuity is not None and (continuity.ended or getattr(continuity.primary.playlist, 'is_endlist', False)):
                                return True
                            finished = getattr(reader, 'is_finished', False) or self._hls_finished(reader)
                            if self._stall_detected or not finished:
                                raise RuntimeError(
                                    "라이브 연결이 중단되었습니다. 재연결을 시도합니다."
                                )
                            return True
                        if self.capture_format == "youtube_dash":
                            checked = True
                        if index == 0 and not checked:
                            prefix.extend(data)
                            if len(prefix) >= 8 and prefix[4:8] in (
                                b"ftyp",
                                b"styp",
                                b"moof",
                            ):
                                # Preserve the real container, never label MP4 as TS.
                                # Native -> TS normalization belongs to the closed-job queue.
                                from app.engine.recording_finalizer import publish_file

                                file.close()
                                native = str(
                                    Path(self._output_path).with_suffix(".native.mp4")
                                )
                                if self.capture_format != "fmp4":
                                    if Path(self._source_files[0]).stat().st_size:
                                        raise RecordingError(
                                            "container_changed",
                                            "재연결된 스트림의 원본 형식이 달라졌습니다. 저장된 원본을 확인하세요.",
                                        )
                                    publish_file(
                                        Path(self._source_files[0]),
                                        Path(native + ".part"),
                                    )
                                    self._output_path = native
                                    self._source_files[0] = native + ".part"
                                self.capture_format = "fmp4"
                                file = open(self._source_files[0], "ab")
                                data = bytes(prefix)
                                checked = True
                            elif self.capture_format == 'h264':
                                data = bytes(prefix)
                                checked = True
                            elif len(prefix) < 376:
                                continue
                            # Reads need not align to packet boundaries. Strip a
                            # bounded metadata prefix only after finding TS sync.
                            if not checked:
                                offset = next(
                                    (
                                        i
                                        for i in range(min(len(prefix) - 188, 65536))
                                        if prefix[i] == prefix[i + 188] == 0x47
                                    ),
                                    None,
                                )
                                if offset is None:
                                    if len(prefix) < 65536:
                                        continue
                                    raise RecordingError(
                                        "unsupported_container",
                                        "선택된 스트림의 원본 형식을 확인할 수 없습니다.",
                                    )
                                if self.capture_format != "ts":
                                    raise RecordingError(
                                        "container_changed",
                                        "재연결된 스트림의 원본 형식이 달라졌습니다. 저장된 원본을 확인하세요.",
                                    )
                                data = bytes(prefix[offset:])
                                checked = True
                        if index == 0 and getattr(self, "_twitch_reconnect_pending", False):
                            file = self._rotate_twitch_source(file, "connection_recovered")
                            self._twitch_reconnect_pending = False
                        stream = getattr(reader, "stream", None)
                        splitter = getattr(stream, "split_capture_data", None)
                        pieces = splitter(data) if splitter else [(None, data)]
                        for boundary, piece in pieces:
                            if boundary:
                                if self.capture_format != "ts" or len(readers) != 1:
                                    raise RecordingError("stream_discontinuity", "스트림 형식이 변경되었습니다. 원본 파일을 보관합니다.", retryable=True)
                                file = self._rotate_twitch_source(file, boundary)
                            file.write(piece)
                            if index == 0 and self.capture_format == "ts":
                                self._measure_ts(piece)
                        if self.capture_format == "youtube_dash":
                            self._dash_received.add(index)
                        now_mono = time.monotonic()
                        if now_mono - last_flush >= 1.0:
                            file.flush()
                            last_flush = now_mono
                        if index == 0:
                            if self.capture_format == "ts":
                                has_payload = True
                            elif self.capture_format == 'h264':
                                has_payload = True
                            elif self.capture_format == "youtube_dash":
                                self._media_duration = self._dash_duration_base + reader.received_duration
                                has_payload = len(self._dash_received) == len(readers)
                            else:
                                self._native_clock.feed(data)
                                self._media_duration = self._native_clock.duration
                                has_payload = self._native_clock.media_seen
                            if has_payload:
                                self._last_data_at = datetime.now()
                            if (
                                has_payload
                                and self._capture_ready
                                and not self._capture_ready.done()
                            ):
                                file.flush()
                                if self._start_time is None:
                                    self._start_time = self._last_data_at
                                loop.call_soon_threadsafe(self._capture_started)
                finally:
                    if not file.closed:
                        if (
                            index == 0
                            and self.capture_format == "fmp4"
                            and (self._native_clock.remaining or self._native_clock.buffer)
                            and (self._intentional_stop or self._hls_finished(reader))
                        ):
                            # Keep the exact captured bytes for manual recovery;
                            # never certify an interrupted mdat as complete.
                            self._record_output_error('partial_input')
                        if index == 0 and self.capture_format == 'ts' and file.tell() % 188:
                            self._record_output_error('partial_input')
                        file.flush()
                        os.fsync(file.fileno())
                        file.close()
                return False

            try:
                return await loop.run_in_executor(receivers, copy_packets)
            except Exception:
                for other in readers:
                    if other is not reader:
                        await asyncio.to_thread(other.close)
                raise

        completed = False
        copies = [asyncio.create_task(receive(i, r)) for i, r in enumerate(readers)]
        receiving = asyncio.gather(*copies, return_exceptions=True)
        try:
            try:
                results = await asyncio.shield(receiving)
            except asyncio.CancelledError:
                # Cancelling an asyncio wrapper does not stop its file-writing
                # thread. Keep ownership until all copying threads have exited.
                self._record_output_error('forced_stop')
                self._force_stop.set()
                for reader in readers:
                    await asyncio.to_thread(reader.close)
                results = await asyncio.shield(receiving)
            error = next((r for r in results if isinstance(r, BaseException)), None)
            if error:
                raise error
            completed = all(results) or self._intentional_stop
        except Exception as error:
            self.last_exception = error
            failure = classify_recording_error(error)
            self._state = RecordingState.ERROR
            self.error_message = str(failure)
            self.error_code = failure.code
            self.retryable = failure.retryable and not self._continuity_active
            self.end_reason = failure.code
            self._ended_at = self._last_data_at
            if self._capture_ready and not self._capture_ready.done():
                self._capture_ready.set_exception(failure)
            self._logger.warning(
                "[%s] 녹화 수신 실패 · 세션=%s · 코드=%s · 재시도=%s · 상세=%s: %s",
                self._channel_id, self.session_id, failure.code, self.retryable,
                type(error).__name__, self._redact_streamlink_error(str(error)),
            )
        finally:
            receivers.shutdown(wait=False, cancel_futures=True)
            for reader in readers:
                try:
                    await asyncio.to_thread(reader.close)
                except Exception:
                    pass
            if self._streamlink_session:
                await asyncio.to_thread(self._streamlink_session.http.close)
            self._readers = []
            self._streamlink_session = None
            self._closed = True
            if self.capture_format == "youtube_dash" and readers:
                self._media_duration = self._dash_duration_base + readers[0].received_duration
            self._update_statistics()
            await self._write_losscheck()
            if self._capture_ready and not self._capture_ready.done():
                self.last_exception = RecordingError(
                    "empty_stream",
                    "녹화 데이터가 수신되지 않았습니다.",
                    retryable=not completed,
                )
                self._state = RecordingState.ERROR
                self.error_message = str(self.last_exception)
                self.error_code = self.last_exception.code
                self._capture_ready.set_exception(self.last_exception)
            if (
                getattr(self, "_on_capture_error", None)
                and self._state == RecordingState.ERROR
            ):
                self._on_capture_error(self)
        if completed and self._start_time is not None:
            self.end_reason = self.error_code if self.output_errors else ("manual" if self._intentional_stop else
                               "continuity_boundary" if self.continuity_resume else "broadcast_ended")
            await self._seal_sources()
            if not self._intentional_stop and getattr(self, "_on_capture_ended", None):
                asyncio.create_task(self._on_capture_ended(self))

    async def _seal_sources(self):
        if not self._closed:
            raise RuntimeError("녹화 파일 쓰기가 종료되지 않았습니다.")
        from app.engine.recording_finalizer import publish_file

        for index, source in enumerate(self._source_files):
            path = Path(source)
            if path.suffix == ".part" and path.is_file() and path.stat().st_size:
                target = self._output_path if index == 0 else str(path)[:-5]
                await asyncio.to_thread(publish_file, path, Path(target))
                self._source_files[index] = target
        self._ended_at = datetime.now()
        self._update_statistics()
        self._state = self._state if self._state == RecordingState.ERROR else (
            RecordingState.COMPLETED
            if self._start_time is not None and Path(self._output_path).is_file()
            else RecordingState.ERROR
        )
        await self._write_losscheck()

    def _rotate_twitch_source(self, file, reason):
        file.flush()
        os.fsync(file.fileno())
        file.close()
        number = len(self._source_files) + 1
        path = self._output_path + f".segment{number}.ts.part"
        following = open(path, "xb")
        self._source_files.append(path)
        self._sequential_sources = True
        self._pcr_last = None
        self._ts_tail = b""
        self.warning_message = "live.twitchCaptureSplit"
        self.continuity_events.append({"kind": "capture_split", "reason": reason,
                                       "part": number, "at": datetime.now().isoformat()})
        del self.continuity_events[:-64]
        self._loss_report.gap({"reason": reason})
        self._logger.warning("[%s] Twitch 원본 구간 분리: %s · 구간=%s", self._channel_id, reason, number)
        return following

    async def _write_losscheck(self):
        if not self._output_path or not self._file_size_bytes:
            return
        try:
            self.losscheck_path = await asyncio.to_thread(
                self._loss_report.write, self._output_path,
                {"session_id": self.session_id, "channel_id": self._channel_id, "container": self.capture_format,
                 "duration_seconds": self.duration_seconds, "file_size_bytes": self._file_size_bytes,
                 "started_at": self._start_time.isoformat() if self._start_time else None,
                 "ended_at": self._ended_at.isoformat() if self._ended_at else None,
                 "end_reason": self.end_reason},
            )
        except OSError as error:
            self._logger.warning("[%s] losscheck 저장 실패: %s", self._channel_id, error)

    async def reconnect(self):
        if not self._closed or self._state != RecordingState.ERROR:
            return
        self._intentional_stop = False
        self._force_stop.clear()
        self._stall_detected = False
        if not self.retryable:
            raise RecordingError(
                self.error_code or "blocked",
                self.error_message or "녹화 설정을 확인하세요.",
            )
        self._state = RecordingState.RECONNECTING
        if self.capture_format == "fmp4":
            # Resume at a complete media-box boundary. A disconnected mdat tail
            # must not absorb the next reader's initialization bytes.
            with open(self._source_files[0], "r+b") as source:
                source.truncate(self._native_clock.complete_media_end)
            self._native_clock.buffer.clear()
            self._native_clock.body.clear()
            self._native_clock.remaining = 0
            self._native_clock.position = self._native_clock.complete_media_end
        try:
            if self._source_resolver:
                url, headers, cookies = await asyncio.wait_for(
                    self._source_resolver(self._quality), 45
                )
            else:
                url, headers, cookies = await self._extract_hls_url(
                    self._source_page_url, self._quality, self._cookie_str
                )
            self._resume_args = (url, headers, cookies, 0, False, self._quality)
            if self.capture_format == "ts" and (urlsplit(self._source_page_url).hostname or "") in (
                    "twitch.tv", "www.twitch.tv", "m.twitch.tv", "go.twitch.tv"):
                self._twitch_reconnect_pending = True
            self._closed = False
            await self._begin_receiver()
        except BaseException as error:
            self._closed = True
            self._state = RecordingState.ERROR
            self.last_exception = error
            failure = classify_recording_error(error)
            self.error_code = failure.code
            self.error_message = str(failure)
            self.retryable = failure.retryable
            raise

    async def stop_recording(self):
        self._intentional_stop = True
        if self._state == RecordingState.COMPLETED:
            return
        if self._stop_task and self._stop_task.done() and (
            self._stop_task.cancelled() or self._stop_task.exception() is not None
        ):
            self._stop_task = None
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._finish_stop())
        try:
            await asyncio.shield(self._stop_task)
        except asyncio.CancelledError:
            self._record_output_error('forced_stop')
            await asyncio.shield(self._stop_task)
            raise

    async def _finish_stop(self):
        previous_reason = self.end_reason
        if self._state != RecordingState.ERROR:
            self._state = RecordingState.STOPPING
        readers = list(self._readers)
        stopping = [asyncio.create_task(asyncio.to_thread(
            getattr(reader, 'request_stop', reader.close))) for reader in readers]
        if stopping:
            _, pending = await asyncio.wait(stopping, timeout=self.STOP_COOPERATIVE_SECONDS)
            if pending:
                self._record_output_error('forced_stop')
                self._force_stop.set()
                forcing = [asyncio.create_task(asyncio.to_thread(reader.close)) for reader in readers]
                await asyncio.wait(forcing, timeout=self.STOP_FORCE_SECONDS)
            for task in stopping:
                if task.done() and not task.cancelled() and task.exception():
                    self._record_output_error('forced_stop')
        if self._feeder_task:
            try:
                await asyncio.wait_for(asyncio.shield(self._feeder_task), self.STOP_DRAIN_SECONDS)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._record_output_error('forced_stop')
                self._force_stop.set()
                # Never cancel the thread owner or publish a still-open file.
                raise RecordingError('forced_stop', '녹화 종료가 완료되지 않았습니다. 원본 파일은 보관됩니다.')
        if self._closed:
            await self._seal_sources()
            self.end_reason = self.error_code if self.output_errors else previous_reason or 'manual'

    def _record_output_error(self, category):
        if category not in self.output_errors:
            self.output_errors.append(category)
        self.error_code = category
        self.error_message = '녹화 종료 중 데이터 손상이 감지되었습니다. 원본을 보관하고 파일 확인이 필요합니다.'
        self.last_exception = RecordingError(category, self.error_message)
        self.end_reason = category
        self.retryable = False
        self._state = RecordingState.ERROR

    def _buffer_directory(self):
        if 'chzzk.naver.com' not in self._source_page_url:
            return None
        if self.continuity_buffer is None:
            try:
                self.continuity_buffer = tempfile.TemporaryDirectory(
                    prefix='phrolova-buffer-')
            except OSError:
                return '-'
        return self.continuity_buffer.name

    @staticmethod
    def _hls_finished(reader) -> bool:
        worker = getattr(reader, "worker", None)
        end = getattr(worker, "playlist_end", None)
        if end is not None:
            return getattr(worker, "sequence", -1) > end
        streams = getattr(reader, "streams", None)
        return bool(streams) and all(
            YtdlpLivePipeline._hls_finished(child) for child in streams
        )

    @staticmethod
    def _redact_streamlink_error(message: str) -> str:
        """Remove signed playlist/segment URLs from third-party error messages."""

        def redact(match: re.Match[str]) -> str:
            parsed = urlsplit(match.group(0).rstrip(").,;"))
            return urlunsplit((parsed.scheme, parsed.netloc, "/<redacted>", "", ""))

        return re.sub(r"https?://[^\s\"'<>]+", redact, message)

    @staticmethod
    def _create_streamlink_stream(
        hls_url: str,
        headers: dict[str, str],
        cookies: Optional[str],
        start_offset: int,
        force_restart: bool,
        quality: str,
        source_page_url: str = "",
        continuity_resume=None,
        continuity_buffer_dir=None,
        continuity_callback=None,
        api_cookie=None,
        preview_capture=None,
        loss_report=None,
    ) -> tuple[object, object]:
        """Create a Streamlink reader, with a stream-copy TS adapter for TikTok FLV."""
        from streamlink import Streamlink
        from streamlink.stream.hls import HLSStream
        from http.cookies import CookieError, SimpleCookie
        from urllib.parse import urlsplit
        from requests.cookies import create_cookie

        session = Streamlink(plugins_builtin=False)
        session.set_option("http-timeout", 30.0)
        session.set_option("stream-segment-timeout", 30.0)
        session.set_option("stream-segment-attempts", 10)
        session.set_option("stream-segment-threads", 3)
        session.set_option("hls-playlist-reload-attempts", 10)
        session.set_option("dash-manifest-reload-attempts", 10)
        session.set_option("stream-segmented-queue-deadline", 30.0)
        session.set_option("hls-live-edge", 4)

        request_headers = {
            key: value for key, value in headers.items() if key.lower() != "cookie"
        }
        session.set_option("http-headers", request_headers)

        uhd_auth = None
        if (urlsplit(source_page_url).hostname or "").lower() in ("ci.me", "www.ci.me"):
            from app.engine.cime import CimeUhdAuth
            # Keep renewable UHD cookies out of the generic jar: that jar would
            # otherwise widen their path and lose their Secure attribute.
            uhd_auth = CimeUhdAuth.for_url(hls_url, source_page_url)
            session.http.auth = uhd_auth

        # Keep cookies within the CDN host/domain instead of sending a global
        # Cookie header to every URL encountered while following the playlist.
        jar = SimpleCookie()
        cookie_text = cookies or next(
            (value for key, value in headers.items() if key.lower() == "cookie"),
            "",
        )
        if uhd_auth is not None:
            cookie_text = ""
        if cookie_text:
            try:
                jar.load(cookie_text)
            except CookieError:
                jar = SimpleCookie()
        host = (urlsplit(hls_url).hostname or "").lower()
        for morsel in jar.values():
            domain = morsel["domain"].strip() or host
            normalized_domain = domain.lstrip(".").lower()
            if not host or not (
                host == normalized_domain or host.endswith("." + normalized_domain)
            ):
                continue
            session.http.cookies.set_cookie(
                create_cookie(
                    name=morsel.key,
                    value=morsel.value,
                    domain=domain,
                    path=morsel["path"] or "/",
                    secure=bool(morsel["secure"]),
                )
            )

        from app.engine.platform_media import media_platform
        from app.engine.streamlink_support import configure_streamlink_session, guarded_hls_stream
        configure_streamlink_session(session, media_platform(source_page_url), hls_url, loss_report)

        if (urlsplit(source_page_url).hostname or "").lower() in ("tiktok.com", "www.tiktok.com", "m.tiktok.com"):
            from app.engine.platform_auth import platform_cookie_jar
            from app.engine.tiktok_transport import TikTokFLVStream
            from app.engine.tiktok import normalize_tiktok_channel_id
            session.http.cookies.update(platform_cookie_jar('tiktok'))
            session.set_option('stream-timeout', 10)
            if loss_report is not None:
                loss_report.transport = "http-flv"
            return session, TikTokFLVStream(session, hls_url, normalize_tiktok_channel_id(source_page_url), capture=preview_capture)

        if (urlsplit(source_page_url).hostname or "").lower() == "live.bilibili.com":
            from app.engine.platform_auth import platform_cookie_jar
            session.http.cookies.update(platform_cookie_jar('bilibili'))

        if (urlsplit(source_page_url).hostname or "").lower() in ("pandalive.co.kr", "www.pandalive.co.kr"):
            from app.engine.platform_auth import platform_cookie_jar
            session.http.cookies.update(platform_cookie_jar("pandalive"))

        if (urlsplit(source_page_url).hostname or "").lower() in ("popkontv.com", "www.popkontv.com"):
            from app.engine.platform_auth import platform_cookie_jar
            session.http.cookies.update(platform_cookie_jar("popkontv"))

        # Read the manifest through Streamlink, without its FFmpeg-backed muxer.
        if urlsplit(hls_url).path.lower().endswith(".mpd"):
            session.http.close()
            raise RuntimeError(
                "DASH 전용 라이브는 TS 직접 녹화를 지원하지 않습니다. HLS 스트림이 필요합니다."
            )
        from streamlink.stream.hls.m3u8 import parse_m3u8
        from types import SimpleNamespace

        stream_type = HLSStream
        if (urlsplit(source_page_url).hostname or "").lower() in ("kick.com", "www.kick.com"):
            from streamlink.plugins.kick import KickHLSStream

            stream_type = KickHLSStream
        if (urlsplit(source_page_url).hostname or "").lower() in ("twitch.tv", "www.twitch.tv", "m.twitch.tv", "go.twitch.tv"):
            from app.engine.twitch_stream import TwitchCaptureStream

            stream_type = TwitchCaptureStream
        if YtdlpLivePipeline._is_chzzk_live_page(source_page_url):
            from app.engine.chzzk_stream import ChzzkHLSStream
            ChzzkHLSStream = guarded_hls_stream(ChzzkHLSStream)
            channel_id = urlsplit(source_page_url).path.rstrip('/').rsplit('/', 1)[-1]
            def make_stream(uri, **kwargs):
                video = ChzzkHLSStream(
                    session, uri, channel_id, event_callback=continuity_callback,
                    api_cookie=api_cookie, resume=continuity_resume,
                    buffer_dir=continuity_buffer_dir,
                    recording_time_machine=force_restart,
                    capture_start_offset=float(max(0, start_offset)), **kwargs,
                )
                video.initialize_sources()
                if continuity_resume and continuity_resume['live_id'] != video.continuity.live_id:
                    raise RecordingError('broadcast_changed', '방송이 변경되어 이전 녹화 위치에서 이어갈 수 없습니다. 다시 시작하세요.')
                media_manifest = session.http.get(uri).text
                video.continuity.primary.mode = ('llhls' if any(tag in media_manifest for tag in ('#EXT-X-PART:', '#EXT-X-PART-INF:')) else 'hls')
                from app.engine.chzzk_continuity import SourcePath
                video.continuity.paths[0] = SourcePath(uri, False, video.continuity.primary.mode, video.continuity.primary.cdn)
                return video
        else:
            rplay_channel = None
            if (urlsplit(source_page_url).hostname or "").lower() in ("rplay.live", "www.rplay.live"):
                from app.engine.rplay_live import normalize_rplay_channel_id
                from app.engine.rplay_stream import RplayHLSStream
                stream_type = RplayHLSStream
                rplay_channel = normalize_rplay_channel_id(source_page_url)
            stream_type = guarded_hls_stream(stream_type)
            def make_stream(uri, **kwargs):
                stream = (stream_type(session, uri, rplay_channel, quality, **kwargs)
                          if rplay_channel else stream_type(session, uri, **kwargs))
                if is_youtube_url(source_page_url):
                    # YouTube audio can contain ID3v2.3, while Streamlink's
                    # packed-audio parser accepts only ID3v2.4. Preserve tags
                    # and packets for the post-capture FFmpeg remux instead.
                    stream.parse_packed_audio = False
                return stream
        try:
            response = session.http.get(hls_url)
            response.raise_for_status()
            manifest = parse_m3u8(
                response.text, base_uri=response.url, parser=stream_type.__parser__
            )
            variants = [p for p in manifest.playlists if not p.is_iframe]
            if variants:

                def rank(p):
                    info = p.stream_info
                    return (
                        info.resolution.height if info.resolution else 0,
                        info.framerate or 0,
                        info.bandwidth or 0,
                    )

                requested = re.fullmatch(r"(\d+)p([\d.]+)?", quality)
                eligible = [
                    p
                    for p in variants
                    if not requested or rank(p)[0] <= int(requested[1])
                ]
                exact = [
                    p
                    for p in eligible
                    if requested
                    and requested[2]
                    and rank(p)[0] == int(requested[1])
                    and abs(rank(p)[1] - float(requested[2])) < 0.1
                ]
                selected = (min if quality == "worst" else max)(
                    exact or eligible or variants, key=rank
                )
                # HLS is a protocol, not a container. Prefer a TS rendition
                # before falling back to a correctly named native fMP4 capture.
                ordered = sorted(
                    exact or eligible or variants, key=rank, reverse=quality != "worst"
                )
                for candidate in ordered[:16]:
                    child = session.http.get(candidate.uri)
                    child.raise_for_status()
                    if "#EXT-X-MAP" not in child.text:
                        selected = candidate
                        break
                video = make_stream(
                    selected.uri,
                    multivariant=manifest,
                    start_offset=float(max(0, start_offset)),
                )
                audio = [
                    m
                    for m in selected.media
                    if m.type == "AUDIO"
                    and m.uri
                    and m.group_id == selected.stream_info.audio
                ]
                if audio:
                    choice = next((m for m in audio if m.default), audio[0])
                    stream = SimpleNamespace(
                        substreams=[
                            video,
                            make_stream(
                                choice.uri,
                                start_offset=float(max(0, start_offset)),
                            ),
                        ]
                    )
                else:
                    stream = video
            else:
                stream = make_stream(
                    hls_url, start_offset=float(max(0, start_offset))
                )
            if force_restart:
                session.set_option("hls-live-restart", True)
        except BaseException:
            session.http.close()
            raise
        return session, stream

    @staticmethod
    def _hls_master_url(candidate: dict) -> Optional[str]:
        """Keep separate audio renditions connected through the HLS master."""
        value = candidate.get("manifest_url")
        if not isinstance(value, str) or any(c.isspace() for c in value):
            return None
        try:
            parsed = urlsplit(value)
            parsed.port
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                return None
            if parsed.username or parsed.password:
                return None
            if parsed.path.lower().endswith(
                (".mpd", ".mp4", ".webm", ".ts", ".aac", ".mp3")
            ):
                return None
        except ValueError:
            return None
        return value

    @staticmethod
    def _select_preview_hls_format(info: dict) -> dict:
        """Prefer actual Full HD dimensions without changing recording quality.

        Preview runs in browsers, so DASH/progressive URLs and audio-only HLS
        formats cannot be substituted for a video HLS rendition. Format labels
        are intentionally ignored; only extractor-provided dimensions are used.
        """
        import math

        def dimension(value: object) -> float:
            if isinstance(value, bool):
                return 0
            try:
                number = float(value)
            except (TypeError, ValueError):
                return 0
            return number if math.isfinite(number) and number > 0 else 0

        candidates = []
        for candidate in [
            *(info.get("formats") or []),
            *(info.get("requested_formats") or []),
            info,
        ]:
            if not isinstance(candidate, dict):
                continue
            url = candidate.get("url")
            if not isinstance(url, str):
                continue
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                continue
            if parsed.path.lower().endswith(".mpd"):
                continue
            protocol = candidate.get("protocol")
            if protocol not in ("m3u8", "m3u8_native") and not (
                not protocol and parsed.path.lower().endswith(".m3u8")
            ):
                continue
            codec = str(candidate.get("vcodec") or "").lower()
            width = dimension(candidate.get("width"))
            height = dimension(candidate.get("height"))
            if codec == "none" or (not codec and not height):
                continue
            # H.264 HLS is supported by the existing hls.js and native players.
            # Unknown codecs with video dimensions can be tried by the player;
            # known incompatible codecs must not displace a playable rendition.
            if codec and not codec.startswith(("avc", "h264")):
                continue
            video_only = candidate.get("acodec") == "none"
            master = YtdlpLivePipeline._hls_master_url(candidate) if video_only else None
            # Without a master we cannot reconnect separate audio. Prefer a
            # usable A/V rendition, while still allowing truly silent broadcasts
            # when no other video format is available.
            audio_priority = 0 if video_only and not master else 1
            full_hd = (
                2 if (width, height) == (1920, 1080) else 1 if height == 1080 else 0
            )
            playable = {**candidate, "url": master} if master else candidate
            candidates.append(
                (
                    (
                        audio_priority,
                        full_hd,
                        height,
                        width,
                        dimension(candidate.get("fps")),
                        dimension(candidate.get("tbr")),
                    ),
                    playable,
                )
            )
        if not candidates:
            raise RuntimeError(
                "브라우저에서 재생할 수 있는 영상 HLS 스트림을 찾지 못했습니다."
            )
        return max(candidates, key=lambda item: item[0])[1]

    async def _extract_preview_hls_url(
        self,
        page_url: str,
        cookie_file: Optional[str] = None,
    ) -> tuple[str, dict[str, str], Optional[str]]:
        """Resolve preview-only HLS by numeric resolution, never by recording settings."""
        import json as _json

        cmd = [
            *(youtube_extractor_command() if is_youtube_url(page_url) else [get_settings().resolve_ytdlp_path()]),
            page_url,
            "--format",
            "best[protocol^=m3u8]/bestvideo[protocol^=m3u8]/best/bestvideo+bestaudio",
            "--dump-single-json",
            "--skip-download",
            "--no-warnings",
            "--ignore-config",
        ]
        if is_youtube_url(page_url):
            cmd.extend(require_runtime_cli_options())
            cmd.extend(['--no-playlist', '--socket-timeout', '10', '--extractor-retries', '1', '--sleep-requests', '1'])
        if cookie_file:
            cmd.extend(["--cookies", cookie_file])
        # Never log the command: page/stream URLs and cookie paths may be sensitive.
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            if proc.returncode is None:
                proc.kill()
            await proc.communicate()
            raise
        finally:
            self._logger.debug("미리보기 yt-dlp 종료 · 종료코드=%s", proc.returncode)
        if proc.returncode != 0:
            # stderr may contain signed URLs or upstream credentials.
            from app.engine.platform_auth import redact_media_error
            raise RuntimeError(
                f"미리보기 스트림 정보 조회 실패 (code={proc.returncode}): {redact_media_error(stderr.decode(errors='replace')[-2000:])}"
            )
        try:
            info = _json.loads(stdout.decode())
            if not isinstance(info, dict):
                raise ValueError("invalid metadata")
        except (UnicodeError, ValueError) as exc:
            raise RuntimeError("미리보기 스트림 정보를 읽지 못했습니다.") from exc
        selected = self._select_preview_hls_format(info)
        width, height = selected.get("width"), selected.get("height")
        # Numeric metadata only; no format names, URLs, headers, or cookies.
        self._logger.info(
            "라이브 미리보기 HLS 선택: %s×%s",
            width if isinstance(width, (int, float)) else "?",
            height if isinstance(height, (int, float)) else "?",
        )
        return (
            selected["url"],
            selected.get("http_headers") or info.get("http_headers") or {},
            selected.get("cookies") or info.get("cookies"),
        )

    async def _extract_hls_url(
        self,
        page_url: str,
        quality: str,
        cookie_str: Optional[str],
        cookie_file: Optional[str] = None,
        dash: bool = False,
    ) -> tuple[str, dict[str, str], Optional[str]]:
        """yt-dlp로 라이브 HLS URL과 HTTP 헤더를 추출한다.

        cookie_file을 주면 cookie_str 대신 그 파일을 쓴다. 빌려받은 사본이라 지우지 않는다.

        Returns:
            (hls_url, http_headers, 스트림 주소에 해당하는 쿠키) 튜플.
            쿠키는 yt-dlp `-j` 출력의 `cookies` 필드이며 없으면 None.
        """
        import json as _json

        extractor = youtube_extractor_command() if is_youtube_url(page_url) else [get_settings().resolve_ytdlp_path()]
        height = re.match(r"(\d+)p", quality)
        fmt = (
            f"best[protocol^=m3u8][height<={height[1]}]/best[protocol^=m3u8]"
            if height
            else "best[protocol^=m3u8]"
        )
        youtube = is_youtube_url(page_url)
        if youtube and dash:
            preference = "worst" if quality == "worst" else "best"
            limit = f"[height<={height[1]}]" if height else ""
            fmt = f"{preference}video{limit}+bestaudio"
        elif youtube:
            settings = get_settings()
            sabr_priority = getattr(settings, "youtube_sabr_priority", "auto")
            codec_priority = getattr(settings, "youtube_codec_priority", "av1")
            time_machine = getattr(settings, "youtube_time_machine_enabled", False)
            prefer_res = getattr(settings, "youtube_prefer_resolution_over_timemachine", True)

            preference = "worst" if quality == "worst" else "best"
            limit = f"[height<={height[1]}]" if height else ""
            codec_filter = ""
            if codec_priority == "av1":
                codec_filter = "[vcodec^=av01]"
            elif codec_priority == "vp9":
                codec_filter = "[vcodec^=vp9]"
            elif codec_priority == "h264":
                codec_filter = "[vcodec^=avc1]"

            selectors = []
            if sabr_priority == "sabr_first":
                if codec_filter:
                    selectors.append(f"{preference}[protocol^=sabr]{limit}{codec_filter}")
                selectors.append(f"{preference}[protocol^=sabr]{limit}")
                selectors.append(f"{preference}[protocol^=m3u8]{limit}")
                selectors.append(f"{preference}video[protocol^=m3u8]{limit}")
            elif sabr_priority == "sabr_fallback":
                selectors.append(f"{preference}[protocol^=m3u8]{limit}")
                selectors.append(f"{preference}video[protocol^=m3u8]{limit}")
                if codec_filter:
                    selectors.append(f"{preference}[protocol^=sabr]{limit}{codec_filter}")
                selectors.append(f"{preference}[protocol^=sabr]{limit}")
            else: # auto
                # 2k+ or high resolution: prefer SABR for quality if prefer_res is true
                if height and int(height[1]) >= 1440 and prefer_res:
                    if codec_filter:
                        selectors.append(f"{preference}[protocol^=sabr]{limit}{codec_filter}")
                    selectors.append(f"{preference}[protocol^=sabr]{limit}")
                elif time_machine:
                    selectors.append(f"{preference}[protocol^=mpd]{limit}")
                selectors.append(f"{preference}[protocol^=m3u8]{limit}")
                selectors.append(f"{preference}video[protocol^=m3u8]{limit}")
                if codec_filter:
                    selectors.append(f"{preference}[protocol^=sabr]{limit}{codec_filter}")
                selectors.append(f"{preference}[protocol^=sabr]{limit}")

            if limit:
                selectors.append(f"{preference}[protocol^=m3u8]")
                selectors.append(f"{preference}video[protocol^=m3u8]")
                selectors.append(f"{preference}[protocol^=sabr]")
            fmt = "/".join(selectors)

        cmd = [
            *extractor,
            page_url,
            "--format",
            fmt,
            "-j",
            "--no-warnings",
            "--ignore-config",
        ]

        if is_youtube_url(page_url):
            cmd.extend(require_runtime_cli_options())
            cmd.extend(['--no-playlist', '--socket-timeout', '10', '--extractor-retries', '1', '--sleep-requests', '1'])
            if dash:
                cmd.append("--live-from-start")

        cookie_file_path: Optional[str] = None
        if cookie_file:
            cmd += ["--cookies", cookie_file]
        elif cookie_str:
            cookie_file_path = self._write_cookie_file(cookie_str)
            cmd += ["--cookies", cookie_file_path]

        self._logger.debug(f"[{self._channel_id}] yt-dlp 스트림 정보 조회")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                if proc.returncode is None:
                    proc.kill()
                await proc.communicate()
                raise
            finally:
                self._logger.debug("스트림 조회 yt-dlp 종료 · 종료코드=%s", proc.returncode)
        finally:
            if cookie_file_path:
                try:
                    Path(cookie_file_path).unlink(missing_ok=True)
                except Exception:
                    pass

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise RuntimeError(
                f"yt-dlp URL 추출 실패 (code={proc.returncode}): {err[-2000:]}"
            )

        info = _json.loads(stdout.decode())
        if dash:
            tracks = info.get("requested_formats") or []
            if (len(tracks) != 2 or tracks[0].get("vcodec") in (None, "none")
                    or tracks[1].get("acodec") in (None, "none")
                    or any(track.get("protocol") != "http_dash_segments_generator"
                           or not track.get("target_duration") for track in tracks)):
                raise RecordingError("youtube_dash_unavailable", "이 방송에서 DASH 원본을 제공하지 않습니다.")
            if self._dash_source and [
                (track.get("format_id"), track.get("vcodec"), track.get("acodec"))
                for track in tracks
            ] != [
                (track.get("format_id"), track.get("vcodec"), track.get("acodec"))
                for track in self._dash_source
            ]:
                raise RecordingError("container_changed", "재연결된 영상·음성 형식이 달라졌습니다. 원본을 보관합니다.")
            self._dash_source = tracks
            self.recording_resolution = {key: tracks[0].get(key) for key in ("width", "height", "fps")}
            return tracks[0]["url"], tracks[0].get("http_headers") or {}, None
        self.recording_resolution = {key: info.get(key) for key in ("width", "height", "fps")}

        selected = info
        hls_url: Optional[str] = info.get("url")
        http_headers: dict[str, str] = info.get("http_headers", {})
        cookies: Optional[str] = info.get("cookies")

        if not hls_url:
            # audio/video 분리 포맷인 경우 첫 번째 URL 사용
            formats = info.get("requested_formats", [])
            if formats:
                selected = formats[0]
                hls_url = selected.get("url")
                http_headers = selected.get("http_headers") or http_headers
                cookies = selected.get("cookies") or cookies

        if youtube and selected.get("acodec") == "none":
            master = self._hls_master_url(selected)
            if not master:
                raise RecordingError(
                    "youtube_hls_audio",
                    "유튜브 영상·음성 분리 스트림의 HLS 마스터 주소를 찾지 못했습니다. 다시 시도하세요.",
                )
            hls_url = master

        if not hls_url:
            raise RuntimeError("yt-dlp URL 추출 실패: HLS URL을 찾을 수 없음")

        self._logger.debug(f"[{self._channel_id}] HLS URL 추출 완료")
        return hls_url, http_headers, cookies

    async def _resolve_stream_spec(self, engine, channel_id, quality):
        spec = await engine.resolve_stream_spec(channel_id, quality)
        self.recording_resolution = {key: spec.get(key) for key in ("width", "height", "fps")}
        return spec["url"], spec["headers"], spec["cookies"]

    async def _extract_youtube_source(self, page_url, quality, cookie_file=None):
        height = re.match(r"(\d+)p", quality)
        settings = get_settings()
        use_dash = (bool(self._dash_source) or settings.youtube_time_machine_enabled
                    or quality == "best" or height and int(height[1]) > 1080)
        if use_dash:
            try:
                return await self._extract_hls_url(page_url, quality, None,
                                                   cookie_file=cookie_file, dash=True)
            except Exception as error:
                # Authentication, throttling and network failures must not be
                # disguised as a successful lower-quality recording.
                unavailable = (getattr(error, "code", None) == "youtube_dash_unavailable"
                               or "requested format is not available" in str(error).lower())
                if not unavailable or self._dash_source or settings.youtube_time_machine_enabled:
                    raise
                self._logger.info("YouTube DASH 미제공 · HLS 원본으로 전환")
        return await self._extract_hls_url(page_url, quality, None, cookie_file=cookie_file)

    @staticmethod
    def _is_chzzk_live_page(page_url: str) -> bool:
        """타임머신은 치지직 라이브 페이지에만 적용한다."""
        from urllib.parse import urlsplit

        parsed = urlsplit(page_url)
        return (
            parsed.scheme in ("http", "https")
            and parsed.hostname in ("chzzk.naver.com", "www.chzzk.naver.com")
            and parsed.path.startswith("/live/")
        )

    async def _save_live_preview(self, thumbnail_url: str, output_file: Path) -> None:
        """Save the current Chzzk preview beside the recording without blocking it on errors."""
        from app.core.http import get_http_client

        parsed = urlsplit(thumbnail_url)
        host = (parsed.hostname or "").lower()
        trusted = (
            parsed.scheme == "https"
            and not parsed.username
            and not parsed.password
            and (
                host == "chzzk.naver.com"
                or host.endswith(".chzzk.naver.com")
                or host.endswith(".pstatic.net")
                or host.endswith(".nimg.naver.net")
            )
        )
        if not trusted:
            self._logger.warning(
                f"[{self._channel_id}] 미리보기 이미지 URL을 허용된 Chzzk CDN으로 확인하지 못했습니다."
            )
            return

        try:
            async with get_http_client().stream(
                "GET", thumbnail_url, timeout=10.0
            ) as response:
                response.raise_for_status()
                final_url = urlsplit(str(response.url))
                final_host = (final_url.hostname or "").lower()
                if final_url.scheme != "https" or not (
                    final_host == "chzzk.naver.com"
                    or final_host.endswith(".chzzk.naver.com")
                    or final_host.endswith(".pstatic.net")
                    or final_host.endswith(".nimg.naver.net")
                ):
                    self._logger.warning(
                        f"[{self._channel_id}] 미리보기 리디렉션 주소를 허용된 도메인으로 확인하지 못했습니다."
                    )
                    return
                content_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].lower()
                )
                content_length = response.headers.get("content-length")
                if not content_type.startswith("image/") or (
                    content_length and int(content_length) > 20 * 1024 * 1024
                ):
                    self._logger.warning(
                        f"[{self._channel_id}] 미리보기 응답이 이미지가 아니거나 20MB를 초과합니다."
                    )
                    return
                image_data = bytearray()
                async for chunk in response.aiter_bytes():
                    image_data.extend(chunk)
                    if len(image_data) > 20 * 1024 * 1024:
                        self._logger.warning(
                            f"[{self._channel_id}] 미리보기 이미지가 20MB를 초과합니다."
                        )
                        return
            extension = Path(final_url.path).suffix.lower()
            if extension not in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
                extension = mimetypes.guess_extension(content_type) or ".jpg"
            preview_path = output_file.with_suffix(extension)
            await asyncio.to_thread(preview_path.write_bytes, image_data)
            self._logger.debug(f"[{self._channel_id}] 라이브 미리보기 저장: {preview_path}")
        except Exception as exc:
            self._logger.warning(
                f"[{self._channel_id}] 미리보기 저장 실패 (녹화는 계속 진행): {exc}"
            )

    def _update_statistics(self) -> None:
        """파일 크기 기반 통계를 업데이트한다."""
        if not self._output_path:
            return
        try:
            paths = self._source_files or [self._output_path]
            current_size = sum(
                Path(path).stat().st_size for path in paths if Path(path).is_file()
            )
            self._file_size_bytes = current_size
            # HLS segments arrive in bursts. Bitrate describes the saved media,
            # not how quickly the latest segment happened to reach the disk.
            duration = self.duration_seconds
            # 초기 3초 미만 구간에서는 분모가 극소화되어 수백 Mbps로 스파이크되는 현상을 방지한다.
            self._bitrate = current_size * 8 / duration / 1000 if duration >= 3.0 else 0.0
            now = datetime.now()
            for reader in self._readers:
                continuity = getattr(getattr(reader, "stream", None), "continuity", None)
                if continuity and continuity.primary.playlist:
                    self._speed_window_seconds = float(continuity.primary.playlist.targetduration or 0)
            if self._speed_window_seconds > 0:
                if not self._speed_samples and self._last_check_time is not None:
                    self._speed_samples.append((self._last_check_time, self._last_size))
                self._speed_samples.append((now, current_size))
                # Cover one advertised segment interval. The older boundary
                # sample is retained, so a normal gap between segments is not
                # mistaken for a stopped receiver. Real stalls still decay to 0.
                while len(self._speed_samples) > 2 and (
                    now - self._speed_samples[1][0]
                ).total_seconds() >= self._speed_window_seconds:
                    self._speed_samples.pop(0)
                earlier, size = self._speed_samples[0]
                elapsed = (now - earlier).total_seconds()
                self._download_speed = max(0, current_size - size) / elapsed / (1024 * 1024) if elapsed > 0 else 0.0
            elif self._last_check_time is not None:
                elapsed = (now - self._last_check_time).total_seconds()
                if elapsed > 0:
                    size_diff = current_size - self._last_size
                    if size_diff > 0:
                        self._download_speed = (size_diff / elapsed) / (1024 * 1024)
                    else:
                        self._download_speed = 0.0
            self._last_size = current_size
            self._last_check_time = now
        except Exception as e:
            self._logger.error(f"[{self._channel_id}] 통계 업데이트 실패: {e}")

    async def _update_statistics_loop(self) -> None:
        """녹화 중 통계를 주기적으로 업데이트한다."""
        try:
            for _ in range(10):
                if any(Path(path).is_file() for path in self._source_files):
                    break
                await asyncio.sleep(1.0)

            while self._state in (
                RecordingState.CONNECTING,
                RecordingState.RECONNECTING,
                RecordingState.RECORDING,
            ):
                self._update_statistics()
                if (
                    self._last_data_at
                    and (datetime.now() - self._last_data_at).total_seconds() > (95 if self._continuity_active else 90)
                    and not self._twitch_ad_waiting()
                    and not self._stall_detected
                ):
                    self._stall_detected = True
                    for reader in list(self._readers):
                        await asyncio.to_thread(reader.close)
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._logger.error(f"[{self._channel_id}] 통계 루프 오류: {e}")

    def get_status(self) -> dict:
        """현재 녹화 상태를 딕셔너리로 반환 (FFmpegPipeline과 동일 구조)."""
        start = self._start_time
        return {
            "channel_id": self._channel_id,
            "state": self._state.value,
            "is_recording": self._state
            in (RecordingState.RECORDING, RecordingState.STOPPING),
            "output_path": (
                self._source_files[0] if self._source_files else self._output_path
            ),
            "source_paths": list(self._source_files),
            "writer_closed": self._closed,
            "end_reason": self.end_reason,
            "session_id": self.session_id,
            "capture_format": self.capture_format,
            "recording_resolution": self.recording_resolution,
            "cdn": self.cdn,
            "warning_message": "live.twitchAdWaiting" if self._twitch_ad_waiting() else self.warning_message,
            "continuity_source": dict(self.continuity_source),
            "continuity_events": list(self.continuity_events),
            "output_errors": list(self.output_errors),
            "has_data": self._start_time is not None and self._file_size_bytes > 0,
            "retryable": self.retryable,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "data_received_at": (
                self._last_data_at.isoformat() if self._last_data_at else None
            ),
            "output_file": self._output_path,  # conductor의 legacy 접근자 호환
            "duration_seconds": round(float(self.duration_seconds), 1),
            "start_time": start.isoformat() if start is not None else None,
            "file_size_bytes": self._file_size_bytes,
            "download_speed": round(self._download_speed, 2),
            "bitrate": round(self._bitrate, 1),
        }

    def _twitch_ad_waiting(self):
        from app.engine.twitch_stream import TwitchCaptureStream
        return any(
            isinstance(getattr(reader, "stream", None), TwitchCaptureStream)
            and reader.stream.ad_active
            and time.monotonic() - reader.stream.last_activity < 90
            for reader in self._readers
        )

    @staticmethod
    def _write_cookie_file(cookie_str: str) -> str:
        """쿠키 문자열을 Netscape 형식 임시 파일로 저장하고 경로를 반환한다."""
        import os

        lines = ["# Netscape HTTP Cookie File"]
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" not in part:
                continue
            name, _, value = part.partition("=")
            lines.append(
                f".naver.com\tTRUE\t/\tTRUE\t0\t{name.strip()}\t{value.strip()}"
            )
        fd, path = tempfile.mkstemp(prefix="chzzk_cookie_", suffix=".txt")
        try:
            os.write(fd, "\n".join(lines).encode())
        finally:
            os.close(fd)
        return path

    def _clean_filename(self, name: str) -> str:
        """파일명에서 사용할 수 없는 특수문자를 제거한다."""
        from app.core.utils import clean_filename

        return clean_filename(name, max_length=150)
