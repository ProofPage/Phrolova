"""
Phrolova: Discord Bot 서비스
User-Hosted Bot으로 원격에서 녹화 상태 확인 및 제어.

사용자가 DISCORD_BOT_TOKEN을 설정에 입력하면 자동 구동된다.
명령어: /status, /list, /start, /stop 등 슬래시 커맨드 전용.

모든 명령어는 DISCORD_COMMAND_USER_IDS / DISCORD_COMMAND_CHANNEL_ID 기반 권한 검사를
거친다. 두 값이 비어 있으면 DISCORD_NOTIFICATION_CHANNEL_ID가 사용되며, 어느 것도
설정되지 않으면 모든 명령어가 거부된다. (authorization.py 참고)

이 모듈은 NotificationService의 전송 채널(transport) 역할도 겸한다.
알림 큐/재시도/유실 방지 로직은 app.services.notifications가 담당하고,
여기서는 "지금 이 embed를 Discord 채널에 보낸다"만 책임진다.

NOTE: discord.py 라이브러리가 필요합니다.
      requirements.txt에 discord.py 추가 필요.
"""

from __future__ import annotations
import asyncio
import math
import platform
import random
from typing import TYPE_CHECKING, Callable, Optional
from app.core.config import get_settings
from app.core.logger import logger
from app.services.notifications import (
    DeliveryResult,
    EmbedPayload,
    MAX_FIELD_VALUE,
    truncate,
)

if TYPE_CHECKING:
    from app.services.recorder import RecorderService
try:
    import discord
    from discord import app_commands
    from discord.ext import commands

    HAS_DISCORD = True
except ImportError:
    HAS_DISCORD = False
from app.services.discord_bot.authorization import _DENIED_MESSAGE, _is_authorized

_RECONNECT_BASE_DELAY = 5.0
_RECONNECT_MAX_DELAY = 300.0


def _make_embed(
    title: str,
    description: str = "",
    color: str = "green",
    fields: Optional[dict[str, str]] = None,
) -> discord.Embed:
    """공통 Embed 생성 헬퍼.

    Discord 제약(제목 256자, 설명 4096자, 필드 값 1024자)을 넘기면
    400 에러로 메시지 전체가 실패하므로 여기서 잘라낸다.
    """
    color_map = {
        "green": discord.Color.green(),
        "red": discord.Color.red(),
        "blue": discord.Color.blue(),
        "yellow": discord.Color.yellow(),
    }
    embed = discord.Embed(
        title=truncate(title, 256),
        description=truncate(description or "", 4096),
        color=color_map.get(color, discord.Color.greyple()),
    )
    if fields:
        for key, value in list(fields.items())[:25]:
            embed.add_field(
                name=truncate(str(key), 256),
                value=truncate(str(value), MAX_FIELD_VALUE) or "\u200b",
                inline=False,
            )
    return embed


class DiscordBotService:
    """Discord Bot 서비스.

    등록된 채널의 녹화 상태를 외부에서 확인하고 제어한다.
    사용자가 직접 발급받은 BOT_TOKEN으로 구동한다.

    Commands (프리픽스 & 슬래시 동시 지원):
        status          — 현재 녹화 상태 + 시스템 리소스
        list            — 감시 중인 채널 목록
        start [channel_id] — 녹화 시작 + 자동 녹화 ON
        stop  [channel_id] — 녹화 중지 + 자동 녹화 OFF
    """

    name = "discord_bot"

    def __init__(
        self,
        recorder_service: RecorderService,
        on_ready: Optional[Callable[[], None]] = None,
    ) -> None:
        self._service = recorder_service
        self._bot: Optional[commands.Bot] = None
        self._task: Optional[asyncio.Task] = None
        self._stopping = False
        self._on_ready = on_ready
        self._channel_cache: dict[int, object] = {}
        self._reconnect_failures = 0
        self._notifier = None

    def set_notifier(self, notifier) -> None:
        """진단 커맨드가 알림 큐 상태를 읽을 수 있도록 서비스를 연결한다."""
        self._notifier = notifier

    async def start(self) -> None:
        """Discord Bot을 시작한다."""
        if not HAS_DISCORD:
            logger.warning(
                "discord.py가 설치되지 않았습니다. Discord Bot 기능을 사용하려면 'pip install discord.py'를 실행하세요."
            )
            return
        settings = get_settings()
        token = settings.discord_bot_token
        if not token:
            logger.info("Discord Bot 토큰이 설정되지 않았습니다. Bot을 건너뜁니다.")
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run_with_reconnect(token))

    def _build_bot(self) -> commands.Bot:
        """Bot 인스턴스를 생성하고 명령어를 등록한다."""

        class _AuthorizedCommandTree(app_commands.CommandTree):
            """모든 슬래시 커맨드에 권한 검사를 적용하는 CommandTree."""

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                channel_id = interaction.channel_id
                if _is_authorized(interaction.user.id, channel_id):
                    return True
                command_name = interaction.command.name if interaction.command else "?"
                logger.warning(
                    f"Discord 명령어 권한 거부 (슬래시): user={interaction.user} ({interaction.user.id}) channel={channel_id} command={command_name}"
                )
                try:
                    await interaction.response.send_message(
                        _DENIED_MESSAGE, ephemeral=True
                    )
                except Exception:
                    pass
                return False

            async def on_error(
                self,
                interaction: discord.Interaction,
                error: app_commands.AppCommandError,
            ) -> None:
                """핸들러가 예외로 죽어도 사용자에게 결과를 알린다.

                defer만 하고 followup을 못 보내면 Discord는 "생각 중" 상태에
                영원히 머문다. 사용자 입장에서는 원인을 알 길이 없다.
                """
                if isinstance(error, app_commands.CheckFailure):
                    return
                command_name = interaction.command.name if interaction.command else "?"
                logger.error(
                    f"Discord 명령 처리 실패 ({command_name}): {error}", exc_info=error
                )
                notice = "⚠️ 명령을 처리하지 못했습니다. 서버 로그를 확인하세요."
                try:
                    if interaction.response.is_done():
                        await interaction.followup.send(notice, ephemeral=True)
                    else:
                        await interaction.response.send_message(notice, ephemeral=True)
                except Exception:
                    pass

        intents = discord.Intents.default()
        bot = commands.Bot(
            command_prefix=commands.when_mentioned,
            intents=intents,
            tree_cls=_AuthorizedCommandTree,
            help_command=None,
        )
        self._register_commands(bot)
        return bot

    async def _run_with_reconnect(self, token: str) -> None:
        """연결 끊김 시 지수 백오프로 재연결하며 Bot을 실행한다.

        기존 구현은 예외 처리에서 30초를 먼저 자고 그 뒤에 finally가 돌았기 때문에,
        대기하는 동안 이미 죽은 Bot 객체가 self._bot에 남아 있었다.
        여기서는 정리를 먼저 하고 대기한다.
        """
        while not self._stopping:
            bot = self._build_bot()
            self._bot = bot
            self._channel_cache.clear()
            try:
                logger.info("🤖 Discord Bot 시작 중...")
                await bot.start(token)
                if self._stopping:
                    break
                logger.warning("Discord Bot 연결이 종료되었습니다. 재연결합니다.")
            except discord.LoginFailure:
                logger.error(
                    "Discord Bot 로그인 실패: 토큰이 올바르지 않습니다. 재연결을 중단합니다. 설정에서 토큰을 다시 확인하세요."
                )
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._stopping:
                    break
                logger.error(f"Discord Bot 연결 끊김: {e}")
            finally:
                self._bot = None
                self._channel_cache.clear()
                if not bot.is_closed():
                    try:
                        await bot.close()
                    except BaseException:
                        pass
            if self._stopping:
                break
            self._reconnect_failures += 1
            failures = self._reconnect_failures
            delay = min(
                _RECONNECT_BASE_DELAY * 2 ** (failures - 1), _RECONNECT_MAX_DELAY
            )
            delay += random.uniform(0, delay * 0.2)
            logger.info(
                f"🤖 {delay:.0f}초 후 Discord 재연결을 시도합니다. (시도 {failures}회)"
            )
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break

    async def stop(self) -> None:
        """Discord Bot을 종료한다."""
        self._stopping = True
        bot = self._bot
        if bot is not None and (not bot.is_closed()):
            await bot.close()
            logger.info("🤖 Discord Bot 종료.")
        task = self._task
        if task is not None and (not task.done()):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    def is_configured(self) -> bool:
        """봇 토큰과 알림 채널 ID가 모두 설정되어 있는지."""
        if not HAS_DISCORD:
            return False
        settings = get_settings()
        return bool(
            settings.discord_bot_token and settings.discord_notification_channel_id
        )

    def is_available(self) -> bool:
        """지금 즉시 메시지를 보낼 수 있는 상태인지."""
        bot = self._bot
        return self.is_configured() and bot is not None and bot.is_ready()

    async def _resolve_channel(self, channel_id: int):
        """알림 채널 객체를 얻는다.

        get_channel()은 캐시 전용이라 재연결 직후나 스레드 채널에서 None을 반환한다.
        그 경우 REST API(fetch_channel)로 폴백한다. 기존 구현에는 이 폴백이 없어
        캐시 미스가 곧 알림 유실로 이어졌다.
        """
        cached = self._channel_cache.get(channel_id)
        if cached is not None:
            return cached
        bot = self._bot
        if bot is None:
            return None
        channel = bot.get_channel(channel_id)
        if channel is None:
            channel = await bot.fetch_channel(channel_id)
        self._channel_cache[channel_id] = channel
        return channel

    async def send(self, payload: EmbedPayload) -> DeliveryResult:
        """NotificationService가 호출하는 실제 전송 진입점."""
        if not HAS_DISCORD:
            return DeliveryResult.UNAVAILABLE
        bot = self._bot
        if bot is None or not bot.is_ready():
            return DeliveryResult.UNAVAILABLE
        channel_id_str = get_settings().discord_notification_channel_id
        if not channel_id_str:
            return DeliveryResult.UNAVAILABLE
        try:
            channel_id = int(str(channel_id_str).strip())
        except (TypeError, ValueError):
            logger.error(
                f"Discord 알림 채널 ID가 숫자가 아닙니다: {channel_id_str!r}. 채널 우클릭 > 'ID 복사'로 얻은 값을 넣어주세요."
            )
            return DeliveryResult.PERMANENT_FAIL
        embed = discord.Embed(
            title=payload.title,
            description=payload.description,
            color=discord.Color(payload.color),
        )
        for name, value in payload.fields:
            embed.add_field(name=name, value=value, inline=False)
        try:
            channel = await self._resolve_channel(channel_id)
            if channel is None or not hasattr(channel, "send"):
                logger.error(f"Discord 채널 {channel_id}에 메시지를 보낼 수 없습니다.")
                return DeliveryResult.PERMANENT_FAIL
            await channel.send(
                content=payload.mention or None,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(everyone=True, roles=True),
            )
            return DeliveryResult.DELIVERED
        except discord.Forbidden:
            self._channel_cache.pop(channel_id, None)
            logger.error(
                f"Discord 채널 {channel_id}에 메시지 전송 권한이 없습니다. 봇에게 '메시지 보내기' 및 '링크 첨부' 권한을 부여하세요."
            )
            return DeliveryResult.PERMANENT_FAIL
        except discord.NotFound:
            self._channel_cache.pop(channel_id, None)
            logger.error(
                f"Discord 채널 {channel_id}을(를) 찾을 수 없습니다. 채널 ID를 확인하세요."
            )
            return DeliveryResult.PERMANENT_FAIL
        except discord.HTTPException as e:
            self._channel_cache.pop(channel_id, None)
            if e.status == 429:
                logger.warning("Discord 레이트 리밋 — 알림을 재시도 큐로 되돌립니다.")
                return DeliveryResult.RETRY
            if 500 <= e.status < 600:
                return DeliveryResult.RETRY
            logger.error(f"Discord 알림 전송 실패 (HTTP {e.status}): {e.text[:300]}")
            return DeliveryResult.PERMANENT_FAIL
        except (ConnectionError, asyncio.TimeoutError) as e:
            logger.warning(f"Discord 알림 전송 중 네트워크 오류: {e}")
            return DeliveryResult.RETRY
        except Exception as e:
            logger.error(f"Discord 알림 전송 실패: {e}")
            return DeliveryResult.RETRY

    def _register_commands(self, bot: commands.Bot) -> None:
        """Bot 명령어를 등록한다 (프리픽스 + 슬래시)."""

        def _get_status_embed() -> discord.Embed:
            channels = self._service.get_channels()
            recording_count = sum(
                (
                    1
                    for ch in channels
                    if ch.get("recording")
                    and ch["recording"].get("state") == "recording"
                )
            )
            try:
                import psutil

                cpu = psutil.cpu_percent()
                mem = psutil.virtual_memory().percent
                disk = psutil.disk_usage("/").percent
                sys_info = f"CPU: {cpu}% | RAM: {mem}% | Disk: {disk}%"
            except Exception as e:
                logger.warning(f"시스템 정보 조회 실패: {e}")
                sys_info = f"OS: {platform.system()} {platform.release()}"
            embed = discord.Embed(
                title="📊 Phrolova 상태",
                color=(
                    discord.Color.green()
                    if recording_count > 0
                    else discord.Color.grey()
                ),
            )
            embed.add_field(name="감시 채널", value=str(len(channels)), inline=True)
            embed.add_field(name="녹화 중", value=str(recording_count), inline=True)
            embed.add_field(name="시스템", value=sys_info, inline=False)
            return embed

        def _get_list_embed() -> tuple[discord.Embed | None, str | None]:
            """(embed, error_message) 반환. 채널 없으면 embed=None."""
            channels = self._service.get_channels()
            if not channels:
                return (None, "📭 등록된 채널이 없습니다.")
            lines: list[str] = []
            for ch in channels:
                live_status = "🔴 LIVE" if ch["is_live"] else "⚫ OFF"
                name = ch.get("channel_name") or ch["channel_id"]
                channel_id = ch["channel_id"]
                rec = ""
                if ch.get("recording"):
                    rec_state = ch["recording"].get("state", "")
                    if rec_state == "recording":
                        dur = ch["recording"].get("duration_seconds", 0)
                        rec = f" | 🎬 녹화 중 ({dur:.0f}s)"
                lines.append(f"{live_status} **{name}** `({channel_id})`{rec}")
            embed = discord.Embed(
                title="📋 채널 목록",
                description="\n".join(lines),
                color=discord.Color.blue(),
            )
            return (embed, None)

        def _find_channel(channel_id: str) -> dict | None:
            for ch in self._service.get_channels():
                if ch.get("channel_id") == channel_id:
                    return ch
            return None

        @bot.event
        async def on_ready() -> None:
            logger.info(f"🤖 Discord Bot 로그인: {bot.user}")
            self._channel_cache.clear()
            self._reconnect_failures = 0
            if self._on_ready is not None:
                try:
                    self._on_ready()
                except Exception as e:
                    logger.error(f"알림 큐 flush 트리거 실패: {e}")
            total = 0
            for guild in bot.guilds:
                try:
                    bot.tree.copy_global_to(guild=guild)
                    synced = await bot.tree.sync(guild=guild)
                    total += len(synced)
                except Exception as e:
                    logger.error(f"슬래시 커맨드 동기화 실패 ({guild.name}): {e}")
            logger.info(f"🤖 슬래시 커맨드 동기화 완료: {total}개 (서버별 즉시 적용)")

        @bot.tree.command(
            name="status", description="현재 녹화 상태와 시스템 리소스를 확인합니다"
        )
        async def slash_status(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            embed = await asyncio.to_thread(_get_status_embed)
            await interaction.followup.send(embed=embed)

        @bot.tree.command(name="list", description="감시 중인 채널 목록을 표시합니다")
        async def slash_list(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            embed, err = await asyncio.to_thread(_get_list_embed)
            if err:
                await interaction.followup.send(err)
            else:
                await interaction.followup.send(embed=embed)

        @bot.tree.command(
            name="start",
            description="채널 녹화를 시작하고 자동 녹화를 ON으로 설정합니다",
        )
        @app_commands.describe(channel_id="감시 중인 채널 ID (/list에서 확인)")
        async def slash_start(
            interaction: discord.Interaction, channel_id: str
        ) -> None:
            await interaction.response.defer()
            ch = await asyncio.to_thread(_find_channel, channel_id)
            if ch is None:
                await interaction.followup.send(
                    f"❌ 등록되지 않은 채널 ID입니다: `{channel_id}`", ephemeral=True
                )
                return
            display_name = ch.get("channel_name") or channel_id
            composite_key = ch["composite_key"]
            await self._service.start_channel(composite_key)
            await interaction.followup.send(
                embed=_make_embed(
                    "🎬 녹화 시작", f"**{display_name}**\n자동 녹화 ON", "green"
                )
            )

        @bot.tree.command(
            name="stop", description="채널 녹화를 중지하고 자동 녹화를 OFF로 설정합니다"
        )
        @app_commands.describe(channel_id="감시 중인 채널 ID (/list에서 확인)")
        async def slash_stop(interaction: discord.Interaction, channel_id: str) -> None:
            await interaction.response.defer()
            ch = await asyncio.to_thread(_find_channel, channel_id)
            if ch is None:
                await interaction.followup.send(
                    f"❌ 등록되지 않은 채널 ID입니다: `{channel_id}`", ephemeral=True
                )
                return
            display_name = ch.get("channel_name") or channel_id
            composite_key = ch["composite_key"]
            await self._service.stop_channel(composite_key)
            await interaction.followup.send(
                embed=_make_embed(
                    "⏹ 녹화 중지", f"**{display_name}**\n자동 녹화 OFF", "blue"
                )
            )

        def _get_diag_embed() -> discord.Embed:
            """알림 파이프라인 상태를 보여준다 (알림 누락 원인 추적용)."""
            raw_latency = bot.latency
            latency = (
                f"{raw_latency * 1000:.0f}ms"
                if isinstance(raw_latency, float) and math.isfinite(raw_latency)
                else "N/A"
            )
            embed = discord.Embed(
                title="🩺 알림 파이프라인 진단", color=discord.Color.blue()
            )
            embed.add_field(name="게이트웨이 지연", value=latency, inline=True)
            settings = get_settings()
            embed.add_field(
                name="알림 채널 ID",
                value=f"`{settings.discord_notification_channel_id or '미설정'}`",
                inline=True,
            )
            if self._notifier is None:
                embed.add_field(name="알림 큐", value="서비스 미연결", inline=False)
                return embed
            stats = self._notifier.get_stats()
            embed.add_field(
                name="큐 상태",
                value=f"대기 `{stats['pending']}` · 전송 `{stats['delivered']}` · 폐기 `{stats['dropped']}` · 만료 `{stats['expired']}`",
                inline=False,
            )
            transports = "\n".join(
                (
                    f"{('🟢' if t['available'] else '🟡' if t['configured'] else '⚪')} **{t['name']}** — 설정 {('O' if t['configured'] else 'X')} / 가용 {('O' if t['available'] else 'X')}"
                    for t in stats["transports"]
                )
            )
            embed.add_field(name="전송 채널", value=transports or "없음", inline=False)
            embed.add_field(
                name="전송 대상 알림",
                value=f"`{settings.discord_notify_events or 'all'}`",
                inline=False,
            )
            return embed

        @bot.tree.command(
            name="diag", description="알림 큐와 전송 채널 상태를 진단합니다"
        )
        async def slash_diag(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            embed = await asyncio.to_thread(_get_diag_embed)
            await interaction.followup.send(embed=embed)

        def _send_test_notification() -> str:
            """알림 큐를 통해 테스트 알림을 발행하고 결과 문구를 반환한다."""
            if self._notifier is None:
                return "❌ 알림 서비스가 연결되지 않았습니다."
            from app.services.notifications import NotificationKind

            self._notifier.notify(
                kind=NotificationKind.SYSTEM,
                title="🔔 테스트 알림",
                description="알림 파이프라인이 정상 동작합니다.",
                color="green",
                fields={"발신": "테스트 커맨드"},
            )
            return "📨 테스트 알림을 큐에 넣었습니다. 알림 채널을 확인하세요."

        @bot.tree.command(
            name="notify-test", description="알림 채널로 테스트 알림을 보냅니다"
        )
        async def slash_notify_test(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            message = await asyncio.to_thread(_send_test_notification)
            await interaction.followup.send(message)

        @bot.tree.command(
            name="rescan",
            description="설정된 폴링 주기를 무시하고 모든 채널을 즉시 스캔합니다",
        )
        async def slash_rescan(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            await asyncio.to_thread(self._service.scan_now)
            await interaction.followup.send("🔍 전체 채널 즉시 스캔을 시작했습니다.")
