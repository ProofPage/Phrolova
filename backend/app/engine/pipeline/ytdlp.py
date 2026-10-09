"""yt-dlp로 스트림을 찾고 Streamlink/FFmpeg로 라이브를 녹화한다."""

from __future__ import annotations

import asyncio
import os
import asyncio.subprocess
import mimetypes
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from app.core.config import get_settings
from app.core.logger import logger
from app.engine.chzzk_time_machine import resolve_time_machine_stream
from app.engine.youtube_support import is_youtube_url, runtime_cli_options

from app.engine.pipeline.state import RecordingState


class YtdlpLivePipeline:
    """yt-dlp URL 추출 + Streamlink HLS 수신 + FFmpeg 저장 파이프라인.

    yt-dlp는 라이브 HLS에 무조건 ffmpegFD를 사용하므로(--downloader native 무시),
    yt-dlp를 URL 추출 용도로만 쓰고 ffmpeg은 직접 제어한다.

    FFmpegPipeline과 동일한 인터페이스를 구현하므로 conductor.py에서
    별도 분기 없이 교체 사용 가능하다.
    """

    # quality 문자열 → yt-dlp format 문자열 매핑
    _QUALITY_MAP: dict[str, str] = {
        "best":  "best",
        "1080p": "best[height<=1080]/best",
        "720p":  "best[height<=720]/best",
        "480p":  "best[height<=480]/best",
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
        return (datetime.now() - start).total_seconds()

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
        settings = get_settings()
        live_start_index: Optional[int] = None

        save_dir = Path(output_dir or settings.effective_live_download_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        live_date = now
        if live_started_at:
            try:
                live_date = datetime.fromisoformat(live_started_at.replace("Z", "+00:00"))
            except ValueError:
                logger.warning(f"[{self._channel_id}] 라이브 시작 시각을 읽지 못해 현재 시각을 파일명에 사용합니다.")
        ext = (settings.live_format or "ts").lower().lstrip(".")
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
            values.update({
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
            })
            values.update(date_values("", now))
            values.update(date_values("live_", live_date))
            values.update(date_values("download_", now))
            default_template = "[{name}] {title} {live_date_year}-{live_date_month}-{live_date_day} {live_date_hour}-{live_date_minute}-{live_date_second}"
            template = settings.live_filename_template or default_template
            try:
                filename = template.format(**values)
            except (KeyError, ValueError, IndexError) as exc:
                logger.warning(f"[{self._channel_id}] 파일명 형식이 잘못되어 기본 형식을 사용합니다: {exc}")
                filename = default_template.format(**values)
            filename = self._clean_filename(filename) or self._channel_id
            if not filename.lower().endswith(f".{ext}".lower()):
                filename += f".{ext}"

        # 같은 채널/제목이 같은 분 안에 재시작되더라도 기존 파일을 덮어쓰지 않는다.
        filename = self._clean_filename(filename)
        output_file = save_dir / filename
        suffix_number = 1
        preview_suffixes = (".jpg", ".jpeg", ".png", ".webp", ".avif")
        while output_file.exists() or any(
            (save_dir / f"{output_file.stem}{suffix}").exists()
            for suffix in preview_suffixes
        ):
            output_file = save_dir / f"{Path(filename).stem} ({suffix_number}){Path(filename).suffix}"
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

        if not time_machine_resolved:
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

        # ── Phase 2: Streamlink가 HLS를 받고 FFmpeg에 전달 ──
        try:
            import streamlink  # noqa: F401
        except ImportError as exc:
            self._state = RecordingState.ERROR
            raise RuntimeError(
                "라이브 녹화에 Streamlink가 필요합니다. 최신 Phrolova 빌드를 설치해 주세요."
            ) from exc

        ffmpeg_path = settings.resolve_ffmpeg_path()

        cmd = [ffmpeg_path, "-hide_banner", "-loglevel", "error"]

        # HLS URL에 Akamai 인증 토큰이 이미 포함됨 (hdntl=...~hmac=...)
        # Streamlink consumes HLS and sends media bytes through pipe:0. FFmpeg sees
        # a byte stream here, not an HLS playlist, so HLS-only options such as
        # extension_picky are unsupported and must not be passed to this input.
        # Streamlink handles playlist reloads, segment retries, headers and offsets.
        time_machine_offset = (
            settings.effective_chzzk_time_machine_offset if time_machine_resolved else 0
        )
        if http_headers:
            logger.debug(f"[{self._channel_id}] Streamlink HTTP 헤더 적용: {list(http_headers.keys())}")
        cmd += ["-i", "pipe:0", "-c", "copy"]

        # 실제 파일 확장자에 맞춰 컨테이너를 기록한다. MP4는 중단된 녹화도
        # 재생할 수 있도록 fragmented MP4로 저장한다.
        if ext == "mkv":
            cmd += ["-f", "matroska"]
        elif ext == "mp4":
            cmd += ["-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-f", "mp4"]
        else:
            cmd += ["-f", "mpegts"]

        # 이름 확인 후 파일이 생기는 경합 상황에서도 FFmpeg가 덮어쓰지 않게 한다.
        cmd += ["-n", str(output_file)]

        logger.info(
            f"[{self._channel_id}] Streamlink 라이브 수신 및 FFmpeg 녹화 시작 "
            f"(quality={quality}, 타임머신 오프셋={time_machine_offset}초): {output_file}"
        )
        logger.debug(f"[{self._channel_id}] ffmpeg CMD: {' '.join(cmd)}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,   # Streamlink가 HLS 데이터를 전달
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                # Terminal Ctrl+C belongs to the server; it finalizes FFmpeg via EOF/q.
                start_new_session=(os.name != "nt"),
            )
            process = self._process
            self._state = RecordingState.RECORDING
            self._start_time = datetime.now()
            stderr_task = asyncio.create_task(
                self._drain_process_stderr(process),
                name=f"ffmpeg-stderr-{self._channel_id}",
            )
            self._feeder_task = asyncio.create_task(
                self._run_streamlink_feeder(
                    hls_url=hls_url,
                    headers=http_headers,
                    cookies=stream_cookies,
                    start_offset=time_machine_offset,
                    force_restart=time_machine_resolved,
                    quality=quality,
                ),
                name=f"streamlink-feeder-{self._channel_id}",
            )
            asyncio.create_task(
                self._watch_process(process, stderr_task),
                name=f"ffmpeg-watch-{self._channel_id}",
            )
            asyncio.create_task(self._update_statistics_loop())
            if (
                settings.save_live_preview
                and thumbnail_url
                and self._is_chzzk_live_page(page_url)
            ):
                await self._save_live_preview(thumbnail_url, output_file)
            return self._output_path

        except FileNotFoundError:
            self._state = RecordingState.ERROR
            raise FileNotFoundError(f"FFmpeg를 찾을 수 없습니다: {ffmpeg_path}")
        except Exception as e:
            self._state = RecordingState.ERROR
            logger.error(f"[{self._channel_id}] ffmpeg 시작 실패: {e}")
            raise

    async def _run_streamlink_feeder(
        self,
        hls_url: str,
        headers: dict[str, str],
        cookies: Optional[str],
        start_offset: int,
        force_restart: bool,
        quality: str,
    ) -> None:
        """Read HLS data with Streamlink and feed FFmpeg's input pipe."""
        max_open_retries = 3
        try:
            for attempt in range(1, max_open_retries + 1):
                session = None
                try:
                    session, stream = await asyncio.to_thread(
                        self._create_streamlink_stream,
                        hls_url,
                        headers,
                        cookies,
                        start_offset,
                        force_restart,
                        quality,
                    )
                    self._streamlink_session = session
                    self._streamlink_fd = await asyncio.to_thread(stream.open)
                    logger.info(
                        f"[{self._channel_id}] Streamlink HLS 연결 성공 "
                        f"(시도 {attempt}/{max_open_retries})"
                    )
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if session is not None:
                        try:
                            await asyncio.to_thread(session.http.close)
                        except Exception:
                            pass
                    logger.warning(
                        f"[{self._channel_id}] Streamlink 연결 실패 "
                        f"(시도 {attempt}/{max_open_retries}): {type(exc).__name__}: "
                        f"{self._redact_streamlink_error(str(exc))}"
                    )
                    if attempt == max_open_retries:
                        raise RuntimeError("Streamlink가 라이브 HLS 스트림을 열지 못했습니다.") from exc
                    await asyncio.sleep(attempt * 2)

            while self._state == RecordingState.RECORDING:
                stream_fd = self._streamlink_fd
                process = self._process
                if stream_fd is None or process is None or process.stdin is None:
                    break
                data = await asyncio.to_thread(stream_fd.read, 128 * 1024)
                if not data:
                    logger.warning(
                        f"[{self._channel_id}] 방송 감시 중 Streamlink 입력이 끝났습니다. "
                        "녹화를 오류로 표시해 자동 재연결을 요청합니다."
                    )
                    self._state = RecordingState.ERROR
                    break
                process.stdin.write(data)
                await process.stdin.drain()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._state == RecordingState.RECORDING:
                if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
                    proc = self._process
                    return_code = proc.returncode if proc is not None else None
                    logger.warning(
                        f"[{self._channel_id}] FFmpeg 입력 파이프가 닫혔습니다 "
                        f"(FFmpeg 종료 코드={return_code}). 종료 감시 로그에서 원인을 확인합니다."
                    )
                else:
                    logger.error(
                        f"[{self._channel_id}] Streamlink 수신 오류: {type(exc).__name__}: "
                        f"{self._redact_streamlink_error(str(exc))}"
                    )
                self._state = RecordingState.ERROR
        finally:
            stream_fd = self._streamlink_fd
            self._streamlink_fd = None
            if stream_fd is not None:
                try:
                    await asyncio.to_thread(stream_fd.close)
                except Exception:
                    pass
            session = self._streamlink_session
            self._streamlink_session = None
            if session is not None:
                try:
                    await asyncio.to_thread(session.http.close)
                except Exception:
                    pass
            process = self._process
            if process and process.stdin and not process.stdin.is_closing():
                process.stdin.close()

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
    ) -> tuple[object, object]:
        """Create a fresh Streamlink session and HLS/DASH stream reader."""
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
            key: value for key, value in headers.items()
            if key.lower() != "cookie"
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
            session.http.cookies.set_cookie(create_cookie(
                name=morsel.key,
                value=morsel.value,
                domain=domain,
                path=morsel["path"] or "/",
                secure=bool(morsel["secure"]),
            ))

        if urlsplit(hls_url).path.lower().endswith(".mpd"):
            from streamlink.stream.dash import DASHStream

            streams = DASHStream.parse_manifest(session, hls_url)
            if not streams:
                raise RuntimeError("Streamlink에서 사용할 수 있는 DASH 스트림을 찾지 못했습니다.")
            height_limit = {"1080p": 1080, "720p": 720, "480p": 480}.get(quality)
            ranked = []
            for name, candidate in streams.items():
                match = re.search(r"(\d+)p", str(name).lower())
                height = int(match.group(1)) if match else 0
                ranked.append((height, str(name), candidate))
            candidates = ranked
            if height_limit is not None:
                limited = [item for item in ranked if 0 < item[0] <= height_limit]
                if limited:
                    candidates = limited
            stream = max(candidates, key=lambda item: (item[0], item[1]))[2]
        else:
            stream = HLSStream(
                session,
                hls_url,
                start_offset=float(max(0, start_offset)),
                force_restart=force_restart,
            )
        return session, stream

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
        fmt = self._QUALITY_MAP.get(quality, self._QUALITY_MAP["best"])

        cmd = [
            ytdlp_path, page_url, "--format", fmt, "-j", "--no-warnings",
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
            raise RuntimeError(f"yt-dlp URL 추출 실패 (code={proc.returncode}): {err[-300:]}")

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
            logger.warning(f"[{self._channel_id}] 미리보기 이미지 URL을 허용된 Chzzk CDN으로 확인하지 못했습니다.")
            return

        try:
            async with get_http_client().stream("GET", thumbnail_url, timeout=10.0) as response:
                response.raise_for_status()
                final_url = urlsplit(str(response.url))
                final_host = (final_url.hostname or "").lower()
                if final_url.scheme != "https" or not (
                    final_host == "chzzk.naver.com"
                    or final_host.endswith(".chzzk.naver.com")
                    or final_host.endswith(".pstatic.net")
                    or final_host.endswith(".nimg.naver.net")
                ):
                    logger.warning(f"[{self._channel_id}] 미리보기 리디렉션 주소를 허용된 도메인으로 확인하지 못했습니다.")
                    return
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                content_length = response.headers.get("content-length")
                if not content_type.startswith("image/") or (
                    content_length and int(content_length) > 20 * 1024 * 1024
                ):
                    logger.warning(f"[{self._channel_id}] 미리보기 응답이 이미지가 아니거나 20MB를 초과합니다.")
                    return
                image_data = bytearray()
                async for chunk in response.aiter_bytes():
                    image_data.extend(chunk)
                    if len(image_data) > 20 * 1024 * 1024:
                        logger.warning(f"[{self._channel_id}] 미리보기 이미지가 20MB를 초과합니다.")
                        return
            extension = Path(final_url.path).suffix.lower()
            if extension not in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
                extension = mimetypes.guess_extension(content_type) or ".jpg"
            preview_path = output_file.with_suffix(extension)
            await asyncio.to_thread(preview_path.write_bytes, image_data)
            logger.info(f"[{self._channel_id}] 라이브 미리보기 저장: {preview_path}")
        except Exception as exc:
            logger.warning(f"[{self._channel_id}] 미리보기 저장 실패 (녹화는 계속 진행): {exc}")

    async def stop_recording(self) -> None:
        """ffmpeg 프로세스를 정상 종료한다."""
        proc = self._process
        if proc is None or self._state not in (RecordingState.RECORDING, RecordingState.ERROR):
            logger.warning(f"[{self._channel_id}] 녹화 중이 아닙니다.")
            return

        had_error = self._state == RecordingState.ERROR
        self._intentional_stop = not had_error
        if not had_error:
            self._state = RecordingState.STOPPING
        logger.info(
            f"[{self._channel_id}] Streamlink/FFmpeg 녹화 종료 요청..."
            if not had_error
            else f"[{self._channel_id}] 실패한 Streamlink/FFmpeg 프로세스 정리 중..."
        )

        stream_fd = self._streamlink_fd
        if stream_fd is not None:
            try:
                await asyncio.to_thread(stream_fd.close)
            except Exception:
                pass
        feeder_task = self._feeder_task
        if feeder_task is not None and not feeder_task.done():
            feeder_task.cancel()
            await asyncio.gather(feeder_task, return_exceptions=True)
        self._feeder_task = None

        if proc.returncode is None:
            try:
                # stdin is the media pipe, so sending FFmpeg's interactive "q"
                # command here would corrupt the stream. Close Streamlink first,
                # then EOF on pipe:0 lets FFmpeg finalize the output cleanly.
                stdin = proc.stdin
                if stdin is not None and not stdin.is_closing():
                    stdin.close()

                await asyncio.wait_for(proc.wait(), timeout=10.0)
                if not had_error and proc.returncode == 0:
                    logger.info(
                        f"[{self._channel_id}] 녹화 완료. "
                        f"경과 시간: {self.duration_seconds:.0f}초, "
                        f"파일: {self._output_path}"
                    )
            except asyncio.TimeoutError:
                logger.warning(f"[{self._channel_id}] ffmpeg 종료 타임아웃. 강제 종료합니다.")
                proc.kill()
                await proc.wait()

        self._state = (
            RecordingState.ERROR
            if had_error or (proc.returncode is not None and proc.returncode != 0)
            else RecordingState.COMPLETED
        )
        self._process = None
        self._streamlink_fd = None
        self._streamlink_session = None
        self._feeder_task = None

    @staticmethod
    async def _drain_process_stderr(
        proc: asyncio.subprocess.Process,
    ) -> bytearray:
        """Drain FFmpeg diagnostics while it runs and retain only the newest 16 KiB."""
        tail = bytearray()
        if proc.stderr is None:
            return tail
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                return tail
            tail.extend(chunk)
            if len(tail) > 16 * 1024:
                del tail[:-16 * 1024]

    async def _watch_process(
        self,
        proc: asyncio.subprocess.Process,
        stderr_task: asyncio.Task[bytearray],
    ) -> None:
        """Watch FFmpeg and report its drained diagnostic tail on failure."""
        return_code = await proc.wait()
        stderr_data = await stderr_task
        if return_code != 0 and not self._intentional_stop:
            err_text = stderr_data.decode(errors="replace").strip()
            if not err_text:
                err_text = "FFmpeg가 상세 오류 없이 종료했습니다. 입력 스트림 또는 프로세스 종료를 확인하세요."
            logger.error(
                f"[{self._channel_id}] ffmpeg 비정상 종료 (code={return_code}): "
                f"{err_text[-2000:]}"
            )
            if self._process is proc:
                self._state = RecordingState.ERROR
        elif self._process is proc and self._state == RecordingState.RECORDING:
            self._state = RecordingState.COMPLETED
            logger.info(f"[{self._channel_id}] ffmpeg 프로세스 정상 종료.")

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
            "is_recording": self._state == RecordingState.RECORDING,
            "output_path": self._output_path,
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
