"""슬래시 커맨드를 누가 어디서 부를 수 있는지 판정한다.

여기가 뚫리면 봇을 초대한 서버의 아무나 남의 녹화를 건드릴 수 있다. 설정이 비어
있으면 허용이 아니라 거부로 기운다. 판정 규칙은 tests/test_discord_auth.py가 지킨다.

이 모듈은 discord.py에 의존하지 않는다 — 순수한 판단 로직만 둔다.
"""

from __future__ import annotations

from typing import Optional

from app.core.config import get_settings
from app.core.logger import logger

_DENIED_MESSAGE = (
    "⛔ 이 봇을 제어할 권한이 없습니다.\n"
    "설정 → 알림 탭에서 `명령어 허용 사용자 ID` 또는 `명령어 허용 채널 ID`를 지정하세요."
)


def _parse_id_list(raw: Optional[str]) -> set[int]:
    """쉼표로 구분된 Discord ID 문자열을 정수 집합으로 변환한다."""
    if not raw:
        return set()

    ids: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            logger.warning(f"Discord 명령어 허용 사용자 ID가 올바르지 않습니다: {part!r}")
    return ids


def _parse_id(raw: Optional[str], label: str) -> Optional[int]:
    """단일 Discord ID 문자열을 정수로 변환한다. 실패 시 None."""
    if not raw or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning(f"{label}가 올바르지 않습니다: {raw!r}")
        return None


def _is_authorized(user_id: int, channel_id: Optional[int]) -> bool:
    """봇 명령어 실행 권한을 판정한다.

    아무것도 설정되지 않았을 때 열어두면 봇이 초대된 서버의 누구나 남의 녹화를
    중단시킬 수 있으므로, 안전한 쪽으로 닫는다.

    규칙:
        - DISCORD_COMMAND_USER_IDS가 설정되면 해당 사용자만 허용한다.
        - DISCORD_COMMAND_CHANNEL_ID가 설정되면 해당 채널에서만 허용한다.
        - 둘 다 설정되면 두 조건을 모두 만족해야 한다.
        - 둘 다 비어 있으면 DISCORD_NOTIFICATION_CHANNEL_ID를 채널 조건으로 사용한다.
        - 어느 것도 설정되지 않으면 거부한다.
    """
    settings = get_settings()

    allowed_users = _parse_id_list(settings.discord_command_user_ids)
    allowed_channel = _parse_id(settings.discord_command_channel_id, "Discord 명령어 허용 채널 ID")

    if not allowed_users and allowed_channel is None:
        allowed_channel = _parse_id(
            settings.discord_notification_channel_id, "Discord 알림 채널 ID"
        )

    if not allowed_users and allowed_channel is None:
        return False

    if allowed_users and user_id not in allowed_users:
        return False
    if allowed_channel is not None and channel_id != allowed_channel:
        return False
    return True
