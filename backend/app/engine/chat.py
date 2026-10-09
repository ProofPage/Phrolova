"""
Phrolova: ChatArchiver
실시간 채팅을 수집하고 JSONL 파일로 저장한다.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from chzzkpy.unofficial.chat import ChatClient, ChatMessage

from app.core.config import get_settings
from app.core.logger import logger as app_logger

logger = app_logger.getChild("chzzk")
from app.engine.auth import AuthManager


class ChatArchiver:
    """라이브 방송 중 채팅을 실시간으로 수집하고 JSONL로 저장한다.

    chzzkpy의 ChatClient를 사용하여 WebSocket으로 채팅을 수신하고,
    각 메시지를 타임스탬프와 함께 JSONL 형식으로 저장한다.
    """

    def __init__(
        self,
        channel_id: str,
        output_path: Path,
        auth: Optional[AuthManager] = None,
    ) -> None:
        """ChatArchiver를 초기화한다.

        Args:
            channel_id: 치지직 채널 ID
            output_path: 채팅 로그를 저장할 파일 경로 (.jsonl)
            auth: 인증 매니저 (쿠키 제공)
        """
        self.channel_id = channel_id
        self.output_path = output_path
        self._auth = auth or AuthManager()

        self._client: Optional[ChatClient] = None
        self._task: Optional[asyncio.Task] = None
        self._message_count = 0
        self._is_running = False

    async def start(self) -> None:
        """채팅 수집을 시작한다."""
        if self._is_running:
            logger.warning(f"[ChatArchiver] 이미 실행 중입니다: {self.channel_id}")
            return

        logger.info(f"[ChatArchiver] 채팅 수집 시작: {self.channel_id} → {self.output_path}")

        # 출력 디렉토리 생성
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        # 인증 정보 가져오기
        cookies = self._auth.get_cookies()
        nid_aut = cookies.nid_aut if cookies else None
        nid_ses = cookies.nid_ses if cookies else None

        # ChatClient 생성 및 이벤트 핸들러 등록
        self._client = ChatClient(
            channel_id=self.channel_id,
            authorization_key=nid_aut,
            session_key=nid_ses,
        )

        @self._client.event
        async def on_connect():
            """채팅 연결 완료 시"""
            logger.info(f"[ChatArchiver] 채팅 연결 완료: {self.channel_id}")

        @self._client.event
        async def on_chat(message: ChatMessage):
            """채팅 메시지 수신 시"""
            await self._save_message(message)

        @self._client.event
        async def on_client_error(*args):
            """채팅 클라이언트 에러 발생 시"""
            error = args[0] if args else None
            logger.error(f"[ChatArchiver] 채팅 에러: {error}", exc_info=error if isinstance(error, BaseException) else None)

        # 비동기 태스크로 연결 시작
        self._is_running = True
        self._task = asyncio.create_task(self._run_client())

    async def _run_client(self) -> None:
        """ChatClient를 실행한다 (내부 메서드)."""
        try:
            await self._client.connect()
        except asyncio.CancelledError:
            raise  # 정상 종료 시그널, 상위로 전달
        except RuntimeError as e:
            if "Session is closed" in str(e):
                logger.debug(f"[ChatArchiver] 세션 이미 닫힘, 종료: {self.channel_id}")
            else:
                logger.error(f"[ChatArchiver] 런타임 오류: {e}", exc_info=e)
            self._is_running = False
        except Exception as e:
            logger.error(f"[ChatArchiver] 채팅 연결 실패: {e}", exc_info=e)
            self._is_running = False

    async def _save_message(self, message: ChatMessage) -> None:
        """채팅 메시지를 JSONL 파일에 저장한다.

        Args:
            message: chzzkpy ChatMessage 객체
        """
        try:
            # 채팅 데이터 직렬화 (profile 원본 데이터는 저장하지 않음)
            chat_data = {
                "timestamp": datetime.now().isoformat(),
                "user_id": message.profile.user_id_hash if message.profile else None,
                "nickname": message.profile.nickname if message.profile else "Unknown",
                "message": message.content,
            }

            # JSONL 형식으로 한 줄씩 추가
            with open(self.output_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(chat_data, ensure_ascii=False) + "\n")

            self._message_count += 1

            # 100개마다 로그
            if self._message_count % 100 == 0:
                logger.debug(f"[ChatArchiver] 채팅 수집 중: {self._message_count}개 저장됨")

        except Exception as e:
            logger.error(f"[ChatArchiver] 메시지 저장 실패: {e}", exc_info=e)

    async def stop(self) -> None:
        """채팅 수집을 중지한다."""
        if not self._is_running and (self._task is None or self._task.done()):
            logger.warning(f"[ChatArchiver] 실행 중이 아닙니다: {self.channel_id}")
            return

        logger.info(f"[ChatArchiver] 채팅 수집 중지: {self.channel_id} (총 {self._message_count}개 메시지)")

        self._is_running = False

        # 1. Task 먼저 취소 (client.close() 이전에 해야 Session is closed 오류 방지)
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # 2. Task 종료 후 ChatClient 닫기
        if self._client:
            try:
                await self._client.close()
            except Exception as e:
                logger.error(f"[ChatArchiver] 클라이언트 종료 중 에러: {e}")

        logger.info(f"[ChatArchiver] 채팅 아카이빙 완료: {self.output_path}")

    def get_status(self) -> dict:
        """현재 채팅 수집 상태를 반환한다."""
        return {
            "channel_id": self.channel_id,
            "is_running": self._is_running,
            "message_count": self._message_count,
            "output_path": str(self.output_path),
        }
