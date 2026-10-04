"""
Rookery: X Spaces 녹화 제어

X Spaces는 다른 플랫폼과 녹화 방식이 다르다. 스트림 URL을 yt-dlp 파이프라인에
넘기는 대신 space_id로 yt-dlp subprocess를 직접 띄우고 프로세스를 관리한다.
Conductor에 섞여 있던 이 특수 경로를 분리했다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from app.core.config import get_settings
from app.core.logger import logger

if TYPE_CHECKING:
    from app.engine.channel import ChannelTask
    from app.engine.x_spaces import XSpacesEngine

#: yt-dlp에 SIGTERM을 보낸 뒤 강제 종료까지 기다리는 시간 (초).
TERMINATE_TIMEOUT = 10.0


class SpacesRecorder:
    """X Spaces 녹화 프로세스의 시작/종료와 Master URL 백업을 담당한다."""

    def __init__(self, engine_provider) -> None:
        """
        Args:
            engine_provider: XSpacesEngine을 반환하는 호출 가능 객체.
                             엔진은 지연 생성되므로 팩토리로 받는다.
        """
        self._engine_provider = engine_provider

    @property
    def _engine(self) -> "XSpacesEngine":
        return self._engine_provider()

    async def start(
        self,
        task: "ChannelTask",
        channel_name: Optional[str] = None,
        title: Optional[str] = None,
    ) -> None:
        """Space 녹화를 시작하고 프로세스 핸들을 task에 기록한다.

        Raises:
            ValueError: space_id가 없어 녹화할 수 없는 경우.
            Exception: yt-dlp 기동 실패 시 그대로 전파한다 (호출부가 알림 처리).
        """
        if task._current_space_id is None:
            raise ValueError("Space ID가 없어 녹화를 시작할 수 없습니다.")

        settings = get_settings()
        process, output_path = await self._engine.start_ytdlp_recording(
            space_id=task._current_space_id,
            output_dir=settings.download_dir,
            channel_name=channel_name or task.channel_name or task.channel_id,
            title=title or task.title,
            cookie_file=settings.x_cookie_file,
        )
        task.spaces_process = process
        task.spaces_output_path = output_path

    async def stop(self, task: "ChannelTask", label: str) -> None:
        """Space 녹화 프로세스를 종료하고 결과 파일을 정리한다."""
        proc = task.spaces_process
        if proc is None:
            return

        output_path = task.spaces_output_path
        try:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=TERMINATE_TIMEOUT)
                except asyncio.TimeoutError:
                    logger.warning(f"[{label}] yt-dlp가 응답하지 않아 강제 종료합니다.")
                    proc.kill()

            task.spaces_process = None
            task.spaces_output_path = None
            task._current_space_id = None
            logger.info(f"[{label}] Spaces 녹화 중지.")

            self._finalize_part_file(output_path, label)
        except Exception as e:
            logger.error(f"[{label}] Spaces 녹화 중지 실패: {e}")

    @staticmethod
    def _finalize_part_file(output_path: Optional[str], label: str) -> None:
        """SIGTERM으로 종료된 yt-dlp가 남긴 .part 파일을 최종 파일명으로 바꾼다."""
        if not output_path:
            return
        try:
            part_file = Path(output_path + ".part")
            final_file = Path(output_path)
            if part_file.exists() and not final_file.exists():
                part_file.rename(final_file)
                logger.info(f"[{label}] .part 파일 rename 완료: {final_file.name}")
        except OSError as e:
            logger.error(f"[{label}] .part 파일 정리 실패: {e}")

    @staticmethod
    def save_master_url_file(
        task: "ChannelTask",
        master_url: str,
        space_id: Optional[str],
    ) -> Optional[str]:
        """Master URL을 .txt 파일로 저장하고 경로를 반환한다.

        녹화가 실패하더라도 나중에 수동으로 받을 수 있도록 남기는 백업이다.
        저장 위치: {download_dir}/x_spaces_urls/{channel}_{space_id}_{datetime}.txt
        """
        try:
            settings = get_settings()
            now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            channel_name = task.channel_name or task.channel_id
            safe_name = "".join(c for c in channel_name if c.isalnum() or c in "-_@")
            sid = (space_id or "unknown")[:20]

            url_dir = Path(settings.download_dir) / "x_spaces_urls"
            url_dir.mkdir(parents=True, exist_ok=True)
            file_path = url_dir / f"{safe_name}_{sid}_{now_str}.txt"

            file_path.write_text(
                f"X Spaces Master URL\n"
                f"{'=' * 50}\n"
                f"채널: @{channel_name}\n"
                f"제목: {task.title or 'N/A'}\n"
                f"Space ID: {space_id or 'unknown'}\n"
                f"캡처 시각: {now_str}\n"
                f"\nMaster URL (안정적, ~30일 유효):\n{master_url}\n"
                f"\n다운로드 방법:\n"
                f'  yt-dlp "{master_url}" -o "{channel_name}_%(title)s.%(ext)s"\n',
                encoding="utf-8",
            )
            logger.info(f"[{task.channel_id}] 🗂️ Master URL 파일 저장: {file_path}")
            return str(file_path)
        except Exception as e:
            logger.error(f"[{task.channel_id}] Master URL 파일 저장 실패: {e}")
            return None
