import asyncio
import sys

# 윈도우에서 subprocess 지원을 위해 가장 먼저 설정
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        from asyncio.proactor_events import _ProactorBasePipeTransport
        _orig_call_connection_lost = _ProactorBasePipeTransport._call_connection_lost

        def _silent_call_connection_lost(self, exc):
            if isinstance(exc, (ConnectionResetError, ConnectionAbortedError)) or (
                isinstance(exc, OSError) and getattr(exc, "winerror", None) in (10053, 10054)
            ):
                exc = None
            try:
                return _orig_call_connection_lost(self, exc)
            except (ConnectionResetError, ConnectionAbortedError, OSError):
                pass

        _ProactorBasePipeTransport._call_connection_lost = _silent_call_connection_lost
    except (ImportError, AttributeError):
        pass
