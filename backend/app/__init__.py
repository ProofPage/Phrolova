import sys

# 윈도우에서 subprocess 연결 종료 시 무해한 파이프 리셋 예외 억제
if sys.platform == "win32":
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
