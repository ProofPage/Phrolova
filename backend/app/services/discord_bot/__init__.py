"""Discord 봇.

한 파일에 819줄이 있었다. 그중 인가 판정은 성격이 다르다 — 여기가 뚫리면 봇을
초대한 서버의 아무나 남의 녹화를 제어할 수 있어서 전용 테스트도 따로 있다.
그 부분만 떼어냈다.

임베드 조립은 옮기지 않았다. discord를 쓰기 때문에, 옮기면 try/except ImportError
가드를 두 파일에 복사해야 하고 discord.py 없이도 모듈이 뜨는 구조가 흔들린다.

_is_authorized는 테스트가 모듈 속성으로 직접 부르므로 여기서도 내준다.
"""

from app.services.discord_bot.authorization import (
    _DENIED_MESSAGE,
    _is_authorized,
    _parse_id,
    _parse_id_list,
)
from app.services.discord_bot.service import DiscordBotService, HAS_DISCORD

# discord.py가 없으면 원본에서도 이 이름들이 네임스페이스에 없었다.
# 테스트가 discord_bot.app_commands 로 접근하므로 그 표면을 그대로 둔다.
if HAS_DISCORD:
    from app.services.discord_bot.service import app_commands, commands, discord

__all__ = [
    "DiscordBotService",
    "HAS_DISCORD",
    "_DENIED_MESSAGE",
    "_is_authorized",
    "_parse_id",
    "_parse_id_list",
]
