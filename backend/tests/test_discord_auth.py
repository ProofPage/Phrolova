"""
test_discord_auth.py
Discord Bot 명령어 권한 검사(_is_authorized) 테스트
"""

import pytest

discord_bot = pytest.importorskip(
    "app.services.discord_bot",
    reason="discord.py가 설치되지 않았습니다.",
)

from app.core.config import get_settings  # noqa: E402

USER_ID = 111
OTHER_USER_ID = 222
CHANNEL_ID = 999
OTHER_CHANNEL_ID = 888


@pytest.fixture
def discord_settings():
    """Discord 권한 관련 설정을 조작하고 테스트 후 복원한다."""
    settings = get_settings()
    original = (
        settings.discord_command_user_ids,
        settings.discord_command_channel_id,
        settings.discord_notification_channel_id,
    )

    def configure(users=None, command_channel=None, notification_channel=None):
        settings.discord_command_user_ids = users
        settings.discord_command_channel_id = command_channel
        settings.discord_notification_channel_id = notification_channel

    yield configure

    (
        settings.discord_command_user_ids,
        settings.discord_command_channel_id,
        settings.discord_notification_channel_id,
    ) = original


class TestIsAuthorized:
    """_is_authorized 판정 규칙 테스트"""

    def test_denies_when_nothing_configured(self, discord_settings):
        """아무 설정도 없으면 안전을 위해 거부한다."""
        discord_settings()
        assert discord_bot._is_authorized(USER_ID, CHANNEL_ID) is False

    def test_falls_back_to_notification_channel(self, discord_settings):
        """허용 설정이 비면 알림 채널이 기본 제한으로 쓰인다."""
        discord_settings(notification_channel=str(CHANNEL_ID))
        assert discord_bot._is_authorized(OTHER_USER_ID, CHANNEL_ID) is True
        assert discord_bot._is_authorized(OTHER_USER_ID, OTHER_CHANNEL_ID) is False

    def test_denies_dm_when_only_channel_configured(self, discord_settings):
        """채널 제한만 있으면 DM(channel 불일치)은 거부된다."""
        discord_settings(notification_channel=str(CHANNEL_ID))
        assert discord_bot._is_authorized(USER_ID, None) is False

    def test_user_allowlist_permits_any_channel(self, discord_settings):
        """사용자 허용 목록만 지정하면 채널과 무관하게 허용된다."""
        discord_settings(users=str(USER_ID), notification_channel=str(CHANNEL_ID))
        assert discord_bot._is_authorized(USER_ID, OTHER_CHANNEL_ID) is True
        assert discord_bot._is_authorized(USER_ID, None) is True
        assert discord_bot._is_authorized(OTHER_USER_ID, CHANNEL_ID) is False

    def test_both_configured_requires_both(self, discord_settings):
        """사용자와 채널을 함께 지정하면 두 조건을 모두 만족해야 한다."""
        discord_settings(users=str(USER_ID), command_channel=str(CHANNEL_ID))
        assert discord_bot._is_authorized(USER_ID, CHANNEL_ID) is True
        assert discord_bot._is_authorized(USER_ID, OTHER_CHANNEL_ID) is False
        assert discord_bot._is_authorized(OTHER_USER_ID, CHANNEL_ID) is False

    def test_command_channel_overrides_notification_channel(self, discord_settings):
        """명령어 전용 채널이 지정되면 알림 채널보다 우선한다."""
        discord_settings(
            command_channel=str(OTHER_CHANNEL_ID),
            notification_channel=str(CHANNEL_ID),
        )
        assert discord_bot._is_authorized(USER_ID, OTHER_CHANNEL_ID) is True
        assert discord_bot._is_authorized(USER_ID, CHANNEL_ID) is False

    def test_blank_values_are_treated_as_unset(self, discord_settings):
        """공백 문자열은 미설정으로 간주되어 거부된다."""
        discord_settings(users="   ", command_channel="  ", notification_channel=" ")
        assert discord_bot._is_authorized(USER_ID, CHANNEL_ID) is False

    def test_invalid_user_id_is_ignored(self, discord_settings):
        """숫자가 아닌 사용자 ID는 무시되어 아무도 허용되지 않는다."""
        discord_settings(users="not-a-number")
        assert discord_bot._is_authorized(USER_ID, CHANNEL_ID) is False


class TestParseHelpers:
    """ID 파싱 헬퍼 테스트"""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, set()),
            ("", set()),
            ("111", {111}),
            (" 111 , 222 ", {111, 222}),
            ("111;222", {111, 222}),
            ("111,,222,", {111, 222}),
            ("111,bad,222", {111, 222}),
        ],
    )
    def test_parse_id_list(self, raw, expected):
        assert discord_bot._parse_id_list(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [(None, None), ("", None), ("  ", None), (" 42 ", 42), ("bad", None)],
    )
    def test_parse_id(self, raw, expected):
        assert discord_bot._parse_id(raw, "테스트 ID") == expected


class TestBotWiring:
    """권한 검사가 슬래시 커맨드에 연결되는지 테스트"""

    @pytest.mark.asyncio
    async def test_guard_applied_to_slash_commands(self):
        """CommandTree.interaction_check로 모든 슬래시 커맨드에 일괄 적용된다."""
        service = discord_bot.DiscordBotService(recorder_service=object())
        # _build_bot은 동기 함수다. 다만 commands.Bot 생성이 실행 중인 루프를
        # 필요로 하므로 테스트 자체는 async로 둔다.
        bot = service._build_bot()

        assert isinstance(bot.tree, discord_bot.app_commands.CommandTree)
        assert type(bot.tree).interaction_check is not (
            discord_bot.app_commands.CommandTree.interaction_check
        )

        # 상태 변경 명령어가 실제로 등록되어 있는지 확인
        slash_names = {c.name for c in bot.tree.get_commands()}
        for name in ("start", "stop", "rescan", "download-space", "capture-space"):
            assert name in slash_names

    @pytest.mark.asyncio
    async def test_no_prefix_commands_and_no_privileged_intent(self):
        """프리픽스 명령이 남아 있으면 message_content intent가 다시 필요해진다."""
        service = discord_bot.DiscordBotService(recorder_service=object())
        bot = service._build_bot()

        assert list(bot.commands) == []
        assert bot.intents.message_content is False

    @pytest.mark.asyncio
    async def test_slash_check_denies_and_replies(self, discord_settings):
        """거부 시 ephemeral 안내 메시지를 보내고 False를 반환한다."""
        discord_settings(notification_channel=str(CHANNEL_ID))

        service = discord_bot.DiscordBotService(recorder_service=object())
        bot = service._build_bot()

        replies = []

        class FakeResponse:
            async def send_message(self, message, ephemeral=False):
                replies.append((message, ephemeral))

        class FakeInteraction:
            channel_id = OTHER_CHANNEL_ID
            user = type("U", (), {"id": OTHER_USER_ID, "__str__": lambda s: "someone"})()
            command = type("C", (), {"name": "stop"})()
            response = FakeResponse()

        allowed = await type(bot.tree).interaction_check(bot.tree, FakeInteraction())

        assert allowed is False
        assert len(replies) == 1
        assert "권한이 없습니다" in replies[0][0]
        assert replies[0][1] is True