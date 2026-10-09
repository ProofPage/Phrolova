"""FFmpeg를 직접 띄워 녹화하는 파이프라인 (Legacy, VOD용)."""

from __future__ import annotations

import asyncio
import os
import asyncio.subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import get_settings
from app.core.logger import logger

from app.engine.pipeline.state import RecordingState


class FFmpegPipeline:
    """FFmpeg 기반 녹화 파이프라인.

    HLS 스트림 URL을 입력받아 FFmpeg 프로세스로 녹화한다.
    비동기 subprocess를 사용하여 논블로킹으로 동작한다.
    """

    def __init__(self, channel_id: str) -> None:
        self._channel_id = channel_id
        self._process: Optional[asyncio.subprocess.Process] = None
        self._state = RecordingState.IDLE
        self._start_time: Optional[datetime] = None
        self._output_path: Optional[str] = None
        self._feeder_task: Optional[asyncio.Task] = None
        self._stream_fd = None
        self._intentional_stop = False  # stop_recording() 호출 시 True → _watch_process가 에러 무시

        # 녹화 통계
        self._file_size_bytes: int = 0  # 현재 파일 크기 (바이트)
        self._download_speed: float = 0.0  # 다운로드 속도 (MB/s)
        self._bitrate: float = 0.0  # 비트레이트 (kbps)
        self._last_size: int = 0  # 이전 파일 크기
        self._last_check_time: Optional[datetime] = None  # 마지막 체크 시간

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
        """녹화 경과 시간(초)."""
        start = self._start_time
        if start is None:
            return 0.0
        return (datetime.now() - start).total_seconds()

    @property
    def file_size_bytes(self) -> int:
        """현재 파일 크기 (바이트)."""
        return self._file_size_bytes

    @property
    def download_speed(self) -> float:
        """다운로드 속도 (MB/s)."""
        return self._download_speed

    @property
    def bitrate(self) -> float:
        """비트레이트 (kbps)."""
        return self._bitrate

    def _update_statistics(self) -> None:
        """녹화 통계를 업데이트한다."""
        if not self._output_path:
            logger.debug(f"[{self._channel_id}] 통계 업데이트: output_path가 없음")
            return

        output_file = Path(self._output_path)
        if not output_file.exists():
            logger.debug(f"[{self._channel_id}] 통계 업데이트: 파일이 아직 생성되지 않음")
            return

        try:
            current_size = output_file.stat().st_size
            self._file_size_bytes = current_size

            now = datetime.now()
            if self._last_check_time is not None:
                elapsed = (now - self._last_check_time).total_seconds()
                if elapsed > 0:
                    size_diff = current_size - self._last_size

                    # 파일 크기가 증가했을 때만 속도/비트레이트 업데이트
                    # (FFmpeg 버퍼링으로 인해 일시적으로 크기가 안 늘어날 수 있음)
                    if size_diff > 0:
                        # 속도 (bytes/s → MB/s)
                        self._download_speed = (size_diff / elapsed) / (1024 * 1024)

                        # 비트레이트 (bits/s → kbps)
                        self._bitrate = (size_diff * 8 / elapsed) / 1000

                        logger.debug(
                            f"[{self._channel_id}] 통계 업데이트: "
                            f"size={current_size}, speed={self._download_speed:.2f}MB/s, "
                            f"bitrate={self._bitrate:.0f}kbps"
                        )
                    # size_diff == 0인 경우 이전 값 유지 (로그 생략)

            self._last_size = current_size
            self._last_check_time = now

        except Exception as e:
            logger.error(f"[{self._channel_id}] 통계 업데이트 실패: {e}")

    async def _update_statistics_loop(self) -> None:
        """녹화 중 통계를 주기적으로 업데이트한다."""
        try:
            logger.info(f"[{self._channel_id}] 통계 업데이트 루프 시작")

            # 파일이 생성될 때까지 최대 10초 대기
            for _ in range(10):
                if self._output_path and Path(self._output_path).exists():
                    logger.info(f"[{self._channel_id}] 녹화 파일 생성 확인: {self._output_path}")
                    break
                await asyncio.sleep(1.0)

            while self._state == RecordingState.RECORDING:
                self._update_statistics()
                await asyncio.sleep(2.0)  # 2초마다 업데이트

            logger.info(f"[{self._channel_id}] 통계 업데이트 루프 종료")
        except asyncio.CancelledError:
            logger.info(f"[{self._channel_id}] 통계 업데이트 루프 취소됨")
        except Exception as e:
            logger.error(f"[{self._channel_id}] 통계 업데이트 루프 오류: {e}")

    async def start_recording(
        self,
        stream_obj: Optional[object] = None, # HLS URL or stream object
        output_dir: Optional[str] = None,
        filename: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        streamer_name: Optional[str] = None,
        title: Optional[str] = None,
    ) -> str:
        """FFmpeg 녹화를 시작한다.

        Args:
            stream_url: HLS 스트림 URL.
            output_dir: 저장 디렉토리 (기본: settings.download_dir).
            filename: 파일명 (기본: 자동 생성).

        Returns:
            출력 파일 경로.
        """
        if self._state == RecordingState.RECORDING:
            logger.warning(f"[{self._channel_id}] 이미 녹화 중입니다.")
            return self._output_path or ""

        settings = get_settings()
        ffmpeg_path = settings.resolve_ffmpeg_path()

        # 저장 경로 결정
        save_dir = Path(output_dir or settings.effective_live_download_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        if not filename:
            # [채널이름] 2026-02-11 19：01 방송제목.{format} 형식
            now = datetime.now()
            ts_str = now.strftime("%Y-%m-%d %H：%M")
            ext = settings.live_format or "ts"

            raw_name = f"[{streamer_name or self._channel_id}] {ts_str} {title or 'live'}"
            filename = self._clean_filename(raw_name) + f".{ext}"

        output_file = save_dir / filename
        self._output_path = str(output_file)

        # FFmpeg 명령어 구성
        cmd = [
            ffmpeg_path,
        ]

        is_hybrid = False
        input_source = ""

        if stream_obj and not isinstance(stream_obj, str):
            # Hybrid Mode: Streamlink Object (piped via stdin)
            is_hybrid = True
            input_source = "pipe:0"
            # FFmpeg needs to know the format if coming via pipe
            # But for TS/HLS, 'copy' usually works with 'pipe:0'
        else:
            # Legacy Mode: Direct URL
            input_source = str(stream_obj) if stream_obj else ""
            if headers:
                header_str = "".join([f"{k}: {v}\r\n" for k, v in headers.items()])
                cmd.extend(["-headers", header_str])

        cmd.extend(["-i", input_source, "-c", "copy"])

        # 포맷별 옵션
        ext = settings.live_format or "ts"

        if ext in ("mp4", "mkv"):
            cmd.extend(["-bsf:a", "aac_adtstoasc"])

        if ext == "mp4":
            # MP4 fragmented 모드: 중단되어도 재생 가능!
            # -movflags +frag_keyframe: 키프레임마다 fragment 생성
            # -movflags +empty_moov: 파일 헤더를 맨 앞에 먼저 작성
            # -movflags +default_base_moof: fragment 기반 재생 지원
            cmd.extend(["-movflags", "+frag_keyframe+empty_moov+default_base_moof"])
            logger.info(f"[{self._channel_id}] MP4 fragmented 모드 활성화 (중단 시 자동 복구)")

        cmd.extend(["-y", str(output_file)])

        logger.info(f"[{self._channel_id}] FFmpeg 녹화 시작({'Hybrid' if is_hybrid else 'Direct'}): {output_file}")
        logger.debug(f"[{self._channel_id}] FFmpeg CMD: {' '.join(cmd)}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Terminal Ctrl+C belongs to the server; it finalizes FFmpeg via EOF/q.
                start_new_session=(os.name != "nt"),
            )
            self._state = RecordingState.RECORDING
            self._start_time = datetime.now()

            # Hybrid Mode일 경우 데이터 피더 작동
            if is_hybrid and stream_obj:
                self._feeder_task = asyncio.create_task(
                    self._run_feeder(stream_obj)
                )

            # 백그라운드에서 프로세스 종료 감시
            asyncio.create_task(self._watch_process())

            # 백그라운드에서 통계 업데이트
            asyncio.create_task(self._update_statistics_loop())

            return self._output_path or ""

        except FileNotFoundError:
            # ffmpeg 실행 파일 자체를 찾지 못한 경우
            self._state = RecordingState.ERROR
            raise FileNotFoundError(
                f"FFmpeg를 찾을 수 없습니다: {ffmpeg_path}"
            )
        except Exception as e:
            import traceback
            self._state = RecordingState.ERROR
            logger.error(f"[{self._channel_id}] FFmpeg 시작 실패 ({type(e).__name__}): {e}")
            logger.error(traceback.format_exc())
            raise

    async def _run_feeder(self, stream_obj: object) -> None:
        """스트림 데이터를 FFmpeg stdin으로 전달한다."""
        max_open_retries = 3
        for attempt in range(1, max_open_retries + 1):
            try:
                self._stream_fd = await asyncio.to_thread(lambda: stream_obj.open())  # type: ignore
                logger.info(f"[{self._channel_id}] 스트림 열기 성공 (시도 {attempt}/{max_open_retries})")
                break
            except Exception as e:
                logger.warning(f"[{self._channel_id}] 스트림 열기 실패 (시도 {attempt}/{max_open_retries}): {e}")
                if attempt < max_open_retries:
                    await asyncio.sleep(3.0)
                else:
                    logger.error(f"[{self._channel_id}] 스트림 열기 최종 실패. 녹화를 종료합니다.")
                    self._state = RecordingState.ERROR
                    return

        try:
            while self._state == RecordingState.RECORDING:
                # 데이터 읽기 (128KB 덩어리)
                data = await asyncio.to_thread(lambda: self._stream_fd.read(1024 * 128))  # type: ignore
                if not data:
                    logger.info(f"[{self._channel_id}] 스트림 소스 종료 (EOF).")
                    break

                if self._process and self._process.stdin:
                    self._process.stdin.write(data)
                    await self._process.stdin.drain()
                else:
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{self._channel_id}] 데이터 피더 오류: {e}")
        finally:
            if self._stream_fd:
                try:
                    self._stream_fd.close()
                except Exception:
                    pass
            if self._process and self._process.stdin and not self._process.stdin.is_closing():
                try:
                    self._process.stdin.close()
                except Exception:
                    pass

    async def stop_recording(self) -> None:
        """FFmpeg 녹화를 정상 종료한다."""
        proc = self._process
        if proc is None or self._state not in (RecordingState.RECORDING, RecordingState.ERROR):
            logger.warning(f"[{self._channel_id}] 녹화 중이 아닙니다.")
            return

        self._intentional_stop = True  # _watch_process에 에러 무시 신호
        self._state = RecordingState.STOPPING
        logger.info(f"[{self._channel_id}] FFmpeg 정상 종료 요청...")

        # ── 1. Feeder Task 취소 (Streamlink 스트림 핸들 해제) ──
        feeder = self._feeder_task
        if feeder is not None and not feeder.done():
            feeder.cancel()
            try:
                await feeder
            except asyncio.CancelledError:
                pass
            logger.debug(f"[{self._channel_id}] Feeder task 취소 완료.")
        self._feeder_task = None

        # ── 2. Stream FD 강제 종료 ──
        if self._stream_fd is not None:
            try:
                await asyncio.to_thread(self._stream_fd.close)
            except Exception:
                pass
            self._stream_fd = None
            logger.debug(f"[{self._channel_id}] Stream FD 종료 완료.")

        # ── 3. FFmpeg 프로세스 종료 ──
        if proc is not None and proc.returncode is None:
            try:
                # Windows에서는 SIGINT 대신 stdin에 'q' 전송
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

                # 최대 10초 대기
                await asyncio.wait_for(proc.wait(), timeout=10.0)
                logger.info(
                    f"[{self._channel_id}] 녹화 완료. "
                    f"경과 시간: {self.duration_seconds:.0f}초, "
                    f"파일: {self._output_path}"
                )
            except asyncio.TimeoutError:
                logger.warning(f"[{self._channel_id}] FFmpeg 종료 타임아웃. 강제 종료합니다.")
                proc.kill()
                await proc.wait()

        self._state = RecordingState.COMPLETED
        self._process = None

    async def _watch_process(self) -> None:
        """FFmpeg 프로세스의 종료를 감시한다."""
        proc = self._process
        if proc is None:
            return

        return_code = await proc.wait()

        if self._state == RecordingState.RECORDING:
            # 예상치 못한 종료
            if return_code != 0:
                stderr_data = b""
                stderr_stream = proc.stderr
                if stderr_stream is not None:
                    stderr_data = await stderr_stream.read()
                err_text: str = stderr_data.decode(errors="replace")
                tail: str = err_text[len(err_text) - 500:]  # pyre-ignore[16]: Pyre2 str slice bug
                logger.error(
                    f"[{self._channel_id}] FFmpeg 비정상 종료 (code={return_code}): "
                    f"{tail}"
                )
                self._state = RecordingState.ERROR
            else:
                self._state = RecordingState.COMPLETED
                logger.info(f"[{self._channel_id}] FFmpeg 프로세스 정상 종료.")
        elif self._state == RecordingState.STOPPING:
            # stop_recording()이 호출된 후 FFmpeg가 종료된 경우
            # (stop_recording()의 마지막에서 COMPLETED로 설정하므로 여기선 무시)
            logger.debug(f"[{self._channel_id}] FFmpeg 종료 감지 (STOPPING 상태, 무시).")

    def get_status(self) -> dict:
        """현재 녹화 상태를 딕셔너리로 반환."""
        start = self._start_time
        return {
            "channel_id": self._channel_id,
            "state": self._state.value,
            "is_recording": self._state == RecordingState.RECORDING,
            "output_path": self._output_path,
            "duration_seconds": round(float(self.duration_seconds), 1),  # pyre-ignore[6]: Pyre2 round overload bug
            "start_time": start.isoformat() if start is not None else None,
            # 녹화 통계
            "file_size_bytes": self._file_size_bytes,
            "download_speed": round(self._download_speed, 2),  # MB/s
            "bitrate": round(self._bitrate, 1),  # kbps
        }

    def _clean_filename(self, name: str) -> str:
        """파일명에서 사용할 수 없는 특수문자를 제거한다."""
        from app.core.utils import clean_filename
        return clean_filename(name, max_length=150)
