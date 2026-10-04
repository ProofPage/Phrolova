import asyncio
import sys

# 윈도우에서 subprocess 지원을 위해 가장 먼저 설정
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
