"""Discord 봇·웹훅과 알림 파이프라인 설정."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logger import logger
from app.core.utils import update_env_file as _update_env_file

from app.services.notifications import NotificationKind

from app.api.settings._shared import SETTINGS_PREFIX, SETTINGS_TAGS, _csv_to_list, _list_to_csv


# ── 요청 스키마 ──────────────────────────────────────────

router = APIRouter(prefix=SETTINGS_PREFIX, tags=SETTINGS_TAGS)


class DiscordSettingsUpdateRequest(BaseModel):
    """Discord Bot 및 알림 설정 업데이트 요청."""

    discord_bot_token: Optional[str] = Field(None, description="Discord Bot 토큰")
    discord_notification_channel_id: Optional[str] = Field(None, description="알림을 보낼 Discord 채널 ID")
    discord_command_user_ids: Optional[str] = Field(None, description="봇 명령어를 실행할 수 있는 사용자 ID (쉼표 구분)")
    discord_command_channel_id: Optional[str] = Field(None, description="봇 명령어를 허용할 채널 ID (미설정 시 알림 채널 사용)")
    discord_webhook_url: Optional[str] = Field(
        None, description="Bot 장애 시 폴백으로 사용할 Discord Webhook URL"
    )
    discord_notify_events: Optional[list[str]] = Field(
        None, description="전송할 알림 종류 목록. 전체 허용은 ['all']"
    )
    discord_mention_events: Optional[list[str]] = Field(
        None, description="멘션을 붙일 알림 종류 목록"
    )
    discord_mention_target: Optional[str] = Field(
        None, description="멘션 대상: @here, @everyone, <@&역할ID>"
    )
    discord_notify_ttl: Optional[int] = Field(
        None, ge=60, le=86400, description="대기 중인 알림의 최대 수명 (초)"
    )


@router.put("/discord", summary="Discord Bot 및 알림 설정 업데이트")
async def update_discord_settings(req: DiscordSettingsUpdateRequest):
    """Discord Bot 및 알림 설정을 업데이트합니다.

    토큰/채널 ID 변경은 재시작 후 적용되지만, 알림 종류·멘션·TTL은
    매 전송 시 설정을 다시 읽으므로 즉시 반영됩니다.
    """
    settings = get_settings()

    updates = {}
    if req.discord_bot_token is not None:
        settings.discord_bot_token = req.discord_bot_token if req.discord_bot_token.strip() else None
        updates["DISCORD_BOT_TOKEN"] = req.discord_bot_token.strip()

    if req.discord_notification_channel_id is not None:
        settings.discord_notification_channel_id = req.discord_notification_channel_id if req.discord_notification_channel_id.strip() else None
        updates["DISCORD_NOTIFICATION_CHANNEL_ID"] = req.discord_notification_channel_id.strip()

    if req.discord_command_user_ids is not None:
        cleaned = ",".join(
            part.strip()
            for part in req.discord_command_user_ids.replace(";", ",").split(",")
            if part.strip()
        )
        settings.discord_command_user_ids = cleaned or None
        updates["DISCORD_COMMAND_USER_IDS"] = cleaned

    if req.discord_command_channel_id is not None:
        settings.discord_command_channel_id = req.discord_command_channel_id.strip() or None
        updates["DISCORD_COMMAND_CHANNEL_ID"] = req.discord_command_channel_id.strip()

    if req.discord_webhook_url is not None:
        url = req.discord_webhook_url.strip()
        if url and not url.startswith("https://"):
            raise HTTPException(
                status_code=400,
                detail="Webhook URL은 https://로 시작해야 합니다.",
            )
        settings.discord_webhook_url = url or None
        updates["DISCORD_WEBHOOK_URL"] = url

    if req.discord_notify_events is not None:
        settings.discord_notify_events = _list_to_csv(req.discord_notify_events) or "none"
        updates["DISCORD_NOTIFY_EVENTS"] = settings.discord_notify_events

    if req.discord_mention_events is not None:
        settings.discord_mention_events = _list_to_csv(req.discord_mention_events)
        updates["DISCORD_MENTION_EVENTS"] = settings.discord_mention_events

    if req.discord_mention_target is not None:
        settings.discord_mention_target = req.discord_mention_target.strip() or "@here"
        updates["DISCORD_MENTION_TARGET"] = settings.discord_mention_target

    if req.discord_notify_ttl is not None:
        settings.discord_notify_ttl = req.discord_notify_ttl
        updates["DISCORD_NOTIFY_TTL"] = str(req.discord_notify_ttl)

    try:
        _update_env_file(updates)
    except Exception as e:
        logger.error(f"설정 파일 저장 실패: {e}")

    return {
        "message": "Discord 설정이 업데이트되었습니다. 토큰/채널 변경은 재시작 후 적용됩니다.",
        "settings": {
            "discord_bot_configured": bool(settings.discord_bot_token),
            "discord_notification_channel_id": settings.discord_notification_channel_id,
            "discord_command_user_ids": settings.discord_command_user_ids,
            "discord_command_channel_id": settings.discord_command_channel_id,
            "discord_webhook_configured": bool(settings.discord_webhook_url),
            "discord_notify_events": _csv_to_list(settings.discord_notify_events) or ["all"],
            "discord_mention_events": _csv_to_list(settings.discord_mention_events),
            "discord_mention_target": settings.discord_mention_target,
            "discord_notify_ttl": settings.discord_notify_ttl,
        },
    }


@router.get("/discord/status", summary="알림 파이프라인 상태 조회")
async def get_notification_status():
    """알림 큐와 전송 채널 상태를 반환합니다 (알림 누락 진단용)."""
    from app.main import get_notification_service

    try:
        service = get_notification_service()
    except RuntimeError:
        return {"available": False, "reason": "알림 서비스가 초기화되지 않았습니다."}

    return {"available": True, **service.get_stats()}


@router.post("/discord/test", summary="테스트 알림 전송")
async def send_test_notification():
    """설정된 알림 채널로 테스트 알림을 발행합니다."""
    from app.main import get_notification_service

    try:
        service = get_notification_service()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="알림 서비스가 초기화되지 않았습니다.")

    if not service.has_transport:
        raise HTTPException(
            status_code=400,
            detail="Discord Bot 토큰+채널 ID 또는 Webhook URL 중 하나는 설정되어야 합니다.",
        )

    service.notify(
        kind=NotificationKind.SYSTEM,
        title="🔔 테스트 알림",
        description="알림 파이프라인이 정상 동작합니다.",
        color="green",
        fields={"발신": "설정 페이지"},
    )
    return {"message": "테스트 알림을 큐에 넣었습니다. Discord 채널을 확인하세요."}
