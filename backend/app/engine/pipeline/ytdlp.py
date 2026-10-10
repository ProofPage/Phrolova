"""Resolve live HLS and write Streamlink packets directly; remux only after closing."""

from __future__ import annotations

import asyncio
import os
import asyncio.subprocess
import mimetypes
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Awaitable
from urllib.parse import urlsplit, urlunsplit

from app.core.config import get_settings
from app.core.logger import logger
from app.engine.chzzk_time_machine import resolve_time_machine_stream
from app.engine.youtube_support import is_youtube_url, runtime_cli_options

from app.engine.pipeline.state import RecordingState


class YtdlpLivePipeline:
    """Resolve live URLs, receive Streamlink TS packets and close writers.

    Container conversion belongs exclusively to RecordingFinalizer.
    """

    # quality 문자열 → yt-dlp format 문자열 매핑
    _QUALITY_MAP: dict[str, str] = {
        "best": "best",
        "1080p": "best[height<=1080]/best",
        "720p": "best[height<=720]/best",
        "480p": "best[height<=480]/best",
    }

    def __init__(self, channel_id: str) -> None:
        self._channel_id = channel_id
        self._state = RecordingState.IDLE
        self._process: Optional[asyncio.subprocess.Process] = None
        self._streamlink_fd: Optional[object] = None
        self._streamlink_session: Optional[object] = None
        self._feeder_task: Optional[asyncio.Task[None]] = None
        self._output_path: Optional[str] = None
        self._start_time: Optional[datetime] = None
        self._intentional_stop = False
        self._source_resolver = None
        self._source_page_url = ""
        self._closed = True
        self._ended_at = None
        self._readers = []
        self._source_files = []
        self._resume_args = None
        self._quality = "best"
        self.end_reason = None

        # 녹화 통계 (FFmpegPipeline과 동일 구조)
        self._file_size_bytes: int = 0
        self._download_speed: float = 0.0
        self._bitrate: float = 0.0
        self._last_size: int = 0
        self._last_check_time: Optional[datetime] = None

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
    def duration_seconds(self) -> float:
        start = self._start_time
        if start is None:
            return 0.0
        return ((self._ended_at or datetime.now()) - start).total_seconds()

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
        """yt-dlp로 HLS URL을 추출한 뒤 ffmpeg으로 직접 녹화한다.

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
            logger.warning(f"[{self._channel_id}] 이미 녹화 중입니다.")
            return self._output_path or ""

        self._intentional_stop = False
        page_url = str(stream_obj) if stream_obj else ""
        self._source_resolver = source_resolver
        self._source_page_url = page_url
        settings = get_settings()
        live_start_index: Optional[int] = None

        save_dir = Path(output_dir or settings.effective_live_download_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        live_date = now
        if live_started_at:
            try:
                live_date = datetime.fromisoformat(
                    live_started_at.replace("Z", "+00:00")
                )
            except ValueError:
                logger.warning(
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
                logger.warning(
                    f"[{self._channel_id}] 파일명 형식이 잘못되어 기본 형식을 사용합니다: {exc}"
                )
                filename = default_template.format(**values)
            filename = self._clean_filename(filename) or self._channel_id
            if not filename.lower().endswith(f".{ext}".lower()):
                filename += f".{ext}"

        # 같은 채널/제목이 같은 분 안에 재시작되더라도 기존 파일을 덮어쓰지 않는다.
        filename = self._clean_filename(filename)
        output_file = save_dir / filename
        suffix_number = 1
        preview_suffixes = (".jpg", ".jpeg", ".png", ".webp", ".avif")
        while (
            output_file.exists()
            or Path(str(output_file) + ".part").exists()
            or any(
                (save_dir / f"{output_file.stem}{suffix}").exists()
                for suffix in preview_suffixes
            )
        ):
            output_file = (
                save_dir
                / f"{Path(filename).stem} ({suffix_number}){Path(filename).suffix}"
            )
            suffix_number += 1
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
                )
                hls_url = time_machine_stream.url
                http_headers = time_machine_stream.headers
                live_start_index = time_machine_stream.live_start_index
                time_machine_resolved = True
                logger.info(
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
                logger.warning(
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
                hls_url, http_headers, _ = await self._extract_hls_url(
                    page_url, quality, cookie_str
                )
            except Exception as e:
                if not fallback_cookie_file:
                    self._state = RecordingState.ERROR
                    raise
                logger.warning(
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
        self._start_time = datetime.now()
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
            # Exclusive creation reserves the filename without overwriting data.
            with open(self._source_files[0], "xb"):
                pass
            for attempt in range(3):
                try:
                    await self._begin_receiver()
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1)
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

    async def _begin_receiver(self):
        session, readers = await self._open_raw_readers(*self._resume_args)
        self._streamlink_session, self._readers = session, readers
        while len(self._source_files) < len(readers):
            self._source_files.append(
                self._output_path + f".audio{len(self._source_files)}.part"
            )
        self._closed = False
        if getattr(self, "_on_capture_started", None):
            self._on_capture_started(self)
            self._on_capture_started = None
        self._state = RecordingState.RECORDING
        self._feeder_task = asyncio.create_task(
            self._receive_packets(), name=f"streamlink-record-{self._channel_id}"
        )
        asyncio.create_task(self._update_statistics_loop())

    async def _open_raw_readers(self, *args):
        def open_sources():
            session, stream = self._create_streamlink_stream(
                *args, source_page_url=self._source_page_url
            )
            readers = []
            try:
                for source in getattr(stream, "substreams", None) or [stream]:
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

        async def receive(index, reader):
            def copy_packets():
                checked = False
                with open(self._source_files[index], "ab") as file:
                    try:
                        while not self._intentional_stop:
                            data = reader.read(128 * 1024)
                            if not data:
                                if self._intentional_stop:
                                    return False
                                if not self._hls_finished(reader):
                                    raise RuntimeError(
                                        "라이브 연결이 중단되었습니다. 재연결을 시도합니다."
                                    )
                                return True
                            if index == 0 and not checked:
                                # Do not disguise CMAF/DASH MP4 packets as a TS file.
                                if (
                                    len(data) < 188
                                    or data[0] != 0x47
                                    or len(data) >= 376
                                    and data[188] != 0x47
                                ):
                                    raise RuntimeError(
                                        "이 스트림은 TS 직접 저장을 지원하지 않습니다. HLS TS 화질을 선택하세요."
                                    )
                                checked = True
                            file.write(data)
                    finally:
                        file.flush()
                        os.fsync(file.fileno())
                return False

            try:
                return await asyncio.to_thread(copy_packets)
            except Exception:
                for other in readers:
                    if other is not reader:
                        await asyncio.to_thread(other.close)
                raise

        completed = False
        try:
            results = await asyncio.gather(
                *(receive(i, r) for i, r in enumerate(readers)), return_exceptions=True
            )
            error = next((r for r in results if isinstance(r, BaseException)), None)
            if error:
                raise error
            completed = all(results) or self._intentional_stop
        except Exception as error:
            self._state = RecordingState.ERROR
            self.end_reason = "connection_error"
            logger.warning(
                f"[{self._channel_id}] {self._redact_streamlink_error(str(error))}"
            )
        finally:
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
            self._update_statistics()
        if completed:
            self.end_reason = "manual" if self._intentional_stop else "broadcast_ended"
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
        self._state = (
            RecordingState.COMPLETED
            if Path(self._output_path).is_file()
            else RecordingState.ERROR
        )

    async def reconnect(self):
        if not self._closed or self._state != RecordingState.ERROR:
            return
        self._intentional_stop = False
        if self._source_resolver:
            url, headers, cookies = await asyncio.wait_for(
                self._source_resolver(self._quality), 45
            )
        else:
            url, headers, cookies = await self._extract_hls_url(
                self._source_page_url, self._quality, self._cookie_str
            )
        self._resume_args = (url, headers, cookies, 0, False, self._quality)
        await self._begin_receiver()

    async def stop_recording(self):
        previous_reason = self.end_reason
        self._intentional_stop = True
        if self._state == RecordingState.COMPLETED:
            return
        self._state = RecordingState.STOPPING
        for reader in list(self._readers):
            await asyncio.to_thread(reader.close)
        if self._feeder_task:
            await asyncio.wait_for(asyncio.shield(self._feeder_task), 45)
        if self._closed:
            await self._seal_sources()
            self.end_reason = previous_reason or "manual"

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
    ) -> tuple[object, object]:
        """Create a fresh Streamlink HLS reader without an FFmpeg muxer."""
        from streamlink import Streamlink
        from streamlink.stream.hls import HLSStream
        from http.cookies import CookieError, SimpleCookie
        from urllib.parse import urlsplit
        from requests.cookies import create_cookie

        session = Streamlink(plugins_builtin=False)
        session.set_option("http-timeout", 30.0)
        session.set_option("stream-segment-timeout", 30.0)
        session.set_option("stream-segment-attempts", 10)
        session.set_option("hls-playlist-reload-attempts", 10)
        session.set_option("dash-manifest-reload-attempts", 10)

        request_headers = {
            key: value for key, value in headers.items() if key.lower() != "cookie"
        }
        session.set_option("http-headers", request_headers)

        # Keep cookies within the CDN host/domain instead of sending a global
        # Cookie header to every URL encountered while following the playlist.
        jar = SimpleCookie()
        cookie_text = cookies or next(
            (value for key, value in headers.items() if key.lower() == "cookie"),
            "",
        )
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

        # Read the manifest through Streamlink, without its FFmpeg-backed muxer.
        if urlsplit(hls_url).path.lower().endswith(".mpd"):
            session.http.close()
            raise RuntimeError(
                "DASH 전용 라이브는 TS 직접 녹화를 지원하지 않습니다. HLS 스트림이 필요합니다."
            )
        from streamlink.stream.hls.m3u8 import parse_m3u8
        from types import SimpleNamespace

        stream_type = HLSStream
        if (urlsplit(source_page_url).hostname or "").startswith("play.sooplive."):
            from streamlink.plugins.soop import SoopHLSStream

            stream_type = SoopHLSStream
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
                video = stream_type(
                    session,
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
                            stream_type(
                                session,
                                choice.uri,
                                start_offset=float(max(0, start_offset)),
                            ),
                        ]
                    )
                else:
                    stream = video
            else:
                stream = stream_type(
                    session, hls_url, start_offset=float(max(0, start_offset))
                )
            if force_restart:
                session.set_option("hls-live-restart", True)
        except BaseException:
            session.http.close()
            raise
        return session, stream

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

        def master_url(candidate: dict) -> Optional[str]:
            # yt-dlp's HLS manifest_url retains rendition groups that disappear
            # when its extracted video-only variant is played on its own.
            value = candidate.get("manifest_url")
            if not isinstance(value, str) or any(
                character.isspace() for character in value
            ):
                return None
            try:
                parsed = urlsplit(value)
                parsed.port  # Validate the port before handing this URL to a browser.
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
            master = master_url(candidate) if video_only else None
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
            get_settings().resolve_ytdlp_path(),
            page_url,
            "--format",
            "best[protocol^=m3u8]/bestvideo[protocol^=m3u8]/best/bestvideo+bestaudio",
            "--dump-single-json",
            "--skip-download",
            "--no-warnings",
            "--ignore-config",
        ]
        if is_youtube_url(page_url):
            cmd.extend(runtime_cli_options())
        if cookie_file:
            cmd.extend(["--cookies", cookie_file])
        # Never log the command: page/stream URLs and cookie paths may be sensitive.
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            if proc.returncode is None:
                proc.kill()
            await proc.communicate()
            raise
        if proc.returncode != 0:
            # stderr may contain signed URLs or upstream credentials.
            raise RuntimeError(
                f"미리보기 스트림 정보 조회 실패 (code={proc.returncode})"
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
        logger.info(
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
    ) -> tuple[str, dict[str, str], Optional[str]]:
        """yt-dlp로 라이브 HLS URL과 HTTP 헤더를 추출한다.

        cookie_file을 주면 cookie_str 대신 그 파일을 쓴다. 빌려받은 사본이라 지우지 않는다.

        Returns:
            (hls_url, http_headers, 스트림 주소에 해당하는 쿠키) 튜플.
            쿠키는 yt-dlp `-j` 출력의 `cookies` 필드이며 없으면 None.
        """
        import json as _json

        ytdlp_path = get_settings().resolve_ytdlp_path()
        height = re.match(r"(\d+)p", quality)
        fmt = (
            f"best[protocol^=m3u8][height<={height[1]}]/best[protocol^=m3u8]"
            if height
            else "best[protocol^=m3u8]"
        )

        cmd = [
            ytdlp_path,
            page_url,
            "--format",
            fmt,
            "-j",
            "--no-warnings",
            "--ignore-config",
        ]

        if is_youtube_url(page_url):
            cmd.extend(runtime_cli_options())

        cookie_file_path: Optional[str] = None
        if cookie_file:
            cmd += ["--cookies", cookie_file]
        elif cookie_str:
            cookie_file_path = self._write_cookie_file(cookie_str)
            cmd += ["--cookies", cookie_file_path]

        logger.debug(f"[{self._channel_id}] yt-dlp URL 추출 CMD: {' '.join(cmd)}")

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
            if cookie_file_path:
                try:
                    Path(cookie_file_path).unlink(missing_ok=True)
                except Exception:
                    pass

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise RuntimeError(
                f"yt-dlp URL 추출 실패 (code={proc.returncode}): {err[-300:]}"
            )

        info = _json.loads(stdout.decode())

        hls_url: Optional[str] = info.get("url")
        http_headers: dict[str, str] = info.get("http_headers", {})
        cookies: Optional[str] = info.get("cookies")

        if not hls_url:
            # audio/video 분리 포맷인 경우 첫 번째 URL 사용
            formats = info.get("requested_formats", [])
            if formats:
                hls_url = formats[0].get("url")
                http_headers = formats[0].get("http_headers", {})
                cookies = formats[0].get("cookies")

        if not hls_url:
            raise RuntimeError("yt-dlp URL 추출 실패: HLS URL을 찾을 수 없음")

        logger.debug(f"[{self._channel_id}] HLS URL 추출 완료")
        return hls_url, http_headers, cookies

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
            logger.warning(
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
                    logger.warning(
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
                    logger.warning(
                        f"[{self._channel_id}] 미리보기 응답이 이미지가 아니거나 20MB를 초과합니다."
                    )
                    return
                image_data = bytearray()
                async for chunk in response.aiter_bytes():
                    image_data.extend(chunk)
                    if len(image_data) > 20 * 1024 * 1024:
                        logger.warning(
                            f"[{self._channel_id}] 미리보기 이미지가 20MB를 초과합니다."
                        )
                        return
            extension = Path(final_url.path).suffix.lower()
            if extension not in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
                extension = mimetypes.guess_extension(content_type) or ".jpg"
            preview_path = output_file.with_suffix(extension)
            await asyncio.to_thread(preview_path.write_bytes, image_data)
            logger.info(f"[{self._channel_id}] 라이브 미리보기 저장: {preview_path}")
        except Exception as exc:
            logger.warning(
                f"[{self._channel_id}] 미리보기 저장 실패 (녹화는 계속 진행): {exc}"
            )

    def _update_statistics(self) -> None:
        """파일 크기 기반 통계를 업데이트한다."""
        if not self._output_path:
            return
        output_file = Path(self._output_path)
        if not output_file.exists():
            return
        try:
            current_size = output_file.stat().st_size
            self._file_size_bytes = current_size
            now = datetime.now()
            if self._last_check_time is not None:
                elapsed = (now - self._last_check_time).total_seconds()
                if elapsed > 0:
                    size_diff = current_size - self._last_size
                    if size_diff > 0:
                        self._download_speed = (size_diff / elapsed) / (1024 * 1024)
                        self._bitrate = (size_diff * 8 / elapsed) / 1000
            self._last_size = current_size
            self._last_check_time = now
        except Exception as e:
            logger.error(f"[{self._channel_id}] 통계 업데이트 실패: {e}")

    async def _update_statistics_loop(self) -> None:
        """녹화 중 통계를 주기적으로 업데이트한다."""
        try:
            for _ in range(10):
                if self._output_path and Path(self._output_path).exists():
                    break
                await asyncio.sleep(1.0)

            while self._state == RecordingState.RECORDING:
                self._update_statistics()
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{self._channel_id}] 통계 루프 오류: {e}")

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
            "output_file": self._output_path,  # conductor의 legacy 접근자 호환
            "duration_seconds": round(float(self.duration_seconds), 1),
            "start_time": start.isoformat() if start is not None else None,
            "file_size_bytes": self._file_size_bytes,
            "download_speed": round(self._download_speed, 2),
            "bitrate": round(self._bitrate, 1),
        }

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
