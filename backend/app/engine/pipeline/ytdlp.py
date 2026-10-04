"""yt-dlp subprocess로 라이브를 녹화하는 파이프라인 (Chzzk/TwitCasting)."""

from __future__ import annotations

import asyncio
import asyncio.subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import get_settings
from app.core.logger import logger
from app.core.utils import ffmpeg_supports_extension_picky

from app.engine.pipeline.state import RecordingState


class YtdlpLivePipeline:
    """yt-dlp URL 추출 + ffmpeg 직접 녹화 파이프라인.

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
        quality: str = "best",
        cookie_str: Optional[str] = None,
        fallback_cookie_file: Optional[str] = None,
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
                파일(TwitCasting). 빌려받은 사본이며 지우는 건 빌려준 쪽 몫이다.

        Returns:
            출력 파일 경로.
        """
        if self._state == RecordingState.RECORDING:
            logger.warning(f"[{self._channel_id}] 이미 녹화 중입니다.")
            return self._output_path or ""

        page_url = str(stream_obj) if stream_obj else ""
        settings = get_settings()

        save_dir = Path(output_dir or settings.download_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        if not filename:
            now = datetime.now()
            ts_str = now.strftime("%Y-%m-%d %H：%M")
            ext = settings.live_format or "ts"
            raw_name = f"[{streamer_name or self._channel_id}] {ts_str} {title or 'live'}"
            filename = self._clean_filename(raw_name) + f".{ext}"

        output_file = save_dir / filename
        self._output_path = str(output_file)

        # ── Phase 1: yt-dlp로 HLS URL + HTTP 헤더 추출 ──
        # 로그인 쿠키는 실패했을 때만 쓴다. 지금 되는 녹화는 그대로 두고,
        # 로그인 전용 라이브만 한 번 더 시도한다. yt-dlp가 로그인 요구를 여러 문구로
        # 알려서 문구로 가려내지 않고 추출 실패면 모두 다시 시도한다.
        stream_cookies: Optional[str] = None
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

        # ── Phase 2: ffmpeg으로 직접 녹화 ──
        ffmpeg_path = settings.resolve_ffmpeg_path()

        cmd = [ffmpeg_path, "-hide_banner", "-loglevel", "error"]

        # HLS URL에 Akamai 인증 토큰이 이미 포함됨 (hdntl=...~hmac=...)
        # extension_picky(기본 true)가 세그먼트 포맷 vs URL 확장자 일치를 강제함.
        # Chzzk CDN은 .m4v 확장자를 사용하지만 MOV 디먹서의 확장자 목록에 없어 거부됨.
        # → ffmpeg 7.1.1+ 에서 엄격해진 보안 패치: 해당 버전 이상에서만 비활성화.
        # → ffmpeg 6.x (apt 기본) 등 구버전에서는 옵션 자체가 없거나 불필요하므로 생략.
        if ffmpeg_supports_extension_picky(ffmpeg_path):
            cmd += ["-extension_picky", "0"]
            logger.debug(f"[{self._channel_id}] extension_picky 비활성화 적용 (ffmpeg 7.1.1+)")
        # yt-dlp가 추출한 HTTP 헤더를 ffmpeg에 전달 (TwitCasting 등 Origin/Referer 필요 플랫폼)
        # Chzzk는 HLS URL에 Akamai 토큰이 내장되어 있어 헤더 불필요 → http_headers가 비어 있음
        if http_headers:
            header_str = "".join(f"{k}: {v}\r\n" for k, v in http_headers.items())
            cmd += ["-headers", header_str]
            logger.debug(f"[{self._channel_id}] ffmpeg HTTP 헤더 주입: {list(http_headers.keys())}")
        # 로그인 쿠키로 추출한 스트림은 받을 때도 로그인이 필요할 수 있다.
        # yt-dlp가 스트림 주소에 맞춰 골라 준 쿠키만 넘긴다 (yt-dlp FFmpegFD와 같은 방식).
        if stream_cookies:
            cookie_lines = self._ffmpeg_cookies(stream_cookies)
            if cookie_lines:
                cmd += ["-cookies", cookie_lines]
                logger.debug(f"[{self._channel_id}] ffmpeg 로그인 쿠키 주입")
        cmd += ["-i", hls_url, "-c", "copy"]

        # 라이브 HLS → MPEG-TS 출력 강제 (yt-dlp FFmpegFD와 동일)
        cmd += ["-f", "mpegts"]

        cmd += ["-y", str(output_file)]

        logger.info(
            f"[{self._channel_id}] ffmpeg 라이브 녹화 시작 (quality={quality}): {output_file}"
        )
        logger.debug(f"[{self._channel_id}] ffmpeg CMD: {' '.join(cmd)}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,   # 종료 시 'q' 전송용
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._state = RecordingState.RECORDING
            self._start_time = datetime.now()
            asyncio.create_task(self._watch_process())
            asyncio.create_task(self._update_statistics_loop())
            return self._output_path

        except FileNotFoundError:
            self._state = RecordingState.ERROR
            raise FileNotFoundError(f"FFmpeg를 찾을 수 없습니다: {ffmpeg_path}")
        except Exception as e:
            self._state = RecordingState.ERROR
            logger.error(f"[{self._channel_id}] ffmpeg 시작 실패: {e}")
            raise

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

        cmd = [ytdlp_path, page_url, "--format", fmt, "-j", "--no-warnings"]

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
            stdout, stderr = await proc.communicate()
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

        logger.debug(f"[{self._channel_id}] HLS URL 추출 완료: {hls_url[:100]}...")
        return hls_url, http_headers, cookies

    @staticmethod
    def _ffmpeg_cookies(cookies: str) -> str:
        """yt-dlp `cookies` 필드를 ffmpeg `-cookies` 형식(쿠키마다 한 줄)으로 바꾼다.

        yt-dlp는 `-j` 출력의 http_headers에서 Cookie를 빼고 도메인 정보가 붙은
        `cookies` 필드로 따로 준다. ffmpeg도 도메인을 보고 보내도록 그대로 옮긴다.
        """
        from http.cookies import CookieError, SimpleCookie

        jar = SimpleCookie()
        try:
            jar.load(cookies)
        except CookieError as e:
            # 쿠키를 못 옮겨도 녹화 시도 자체는 막지 않는다.
            logger.warning(f"스트림 쿠키 해석 실패, 쿠키 없이 녹화합니다: {e}")
            return ""
        return "".join(
            f"{m.key}={m.value}; path={m['path'] or '/'}; domain={m['domain']};\r\n"
            for m in jar.values()
        )

    async def stop_recording(self) -> None:
        """ffmpeg 프로세스를 정상 종료한다."""
        proc = self._process
        if proc is None or self._state not in (RecordingState.RECORDING, RecordingState.ERROR):
            logger.warning(f"[{self._channel_id}] 녹화 중이 아닙니다.")
            return

        self._intentional_stop = True
        self._state = RecordingState.STOPPING
        logger.info(f"[{self._channel_id}] ffmpeg 녹화 종료 요청...")

        if proc.returncode is None:
            try:
                # Windows: stdin에 'q' 전송으로 ffmpeg 정상 종료
                stdin = proc.stdin
                if stdin is not None and not stdin.is_closing():
                    try:
                        stdin.write(b"q")
                        await stdin.drain()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    try:
                        stdin.close()
                    except Exception:
                        pass
                else:
                    proc.terminate()

                await asyncio.wait_for(proc.wait(), timeout=10.0)
                logger.info(
                    f"[{self._channel_id}] 녹화 완료. "
                    f"경과 시간: {self.duration_seconds:.0f}초, "
                    f"파일: {self._output_path}"
                )
            except asyncio.TimeoutError:
                logger.warning(f"[{self._channel_id}] ffmpeg 종료 타임아웃. 강제 종료합니다.")
                proc.kill()
                await proc.wait()

        self._state = RecordingState.COMPLETED
        self._process = None

    async def _watch_process(self) -> None:
        """ffmpeg 프로세스의 종료를 감시한다."""
        proc = self._process
        if proc is None:
            return

        return_code = await proc.wait()

        if self._state == RecordingState.RECORDING:
            if return_code != 0 and not self._intentional_stop:
                stderr_data = b""
                if proc.stderr:
                    stderr_data = await proc.stderr.read()
                err_text = stderr_data.decode(errors="replace")
                logger.error(
                    f"[{self._channel_id}] ffmpeg 비정상 종료 (code={return_code}): "
                    f"{err_text[-2000:]}"
                )
                self._state = RecordingState.ERROR
            else:
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
                f".naver.com\tTRUE\t/\tFALSE\t0\t{name.strip()}\t{value.strip()}"
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
