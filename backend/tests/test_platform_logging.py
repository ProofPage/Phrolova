"""공용 로그와 플랫폼 로그가 같은 파일에 한 번씩 기록되는지 검증한다."""

import io
import logging

import pytest

from app.core.logger import get_media_logger, logger


@pytest.mark.parametrize("url, platform", [
    ("https://www.youtube.com/watch?v=TFZx21dqXP8", "youtube"),
    ("https://youtu.be/TFZx21dqXP8", "youtube"),
    ("https://chzzk.naver.com/video/123", "chzzk"),
    ("https://twitcasting.tv/user/movie/123", "twitcasting"),
    ("https://x.com/i/spaces/123", "x_spaces"),
    ("https://example.com/video", "external"),
    ("https://youtube.com.example.com/video", "external"),
])
def test_platform_records_reach_shared_handler_once(url, platform):
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(logging.Formatter("%(name)s | %(message)s"))
    logger.addHandler(handler)
    try:
        get_media_logger(url).info("다운로드 작업 추가")
    finally:
        logger.removeHandler(handler)
    assert output.getvalue() == f"phrolova.{platform} | 다운로드 작업 추가\n"
    assert not get_media_logger(url).handlers


def test_common_logger_uses_app_name():
    assert logger.name == "phrolova"


@pytest.mark.asyncio
async def test_clear_log_keeps_shared_platform_handler_working(tmp_path, monkeypatch):
    from logging.handlers import TimedRotatingFileHandler
    from app.api import system

    path = tmp_path / "service.log"
    handler = TimedRotatingFileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(name)s | %(message)s"))
    monkeypatch.setattr(system, "_get_log_dir", lambda: tmp_path)
    original_handlers = logger.handlers
    logger.handlers = [handler]
    try:
        get_media_logger("https://youtube.com/watch?v=TFZx21dqXP8").info("old")
        result = await system.clear_system_logs()
        get_media_logger("https://youtube.com/watch?v=TFZx21dqXP8").info("new")
        handler.flush()
        content = path.read_text(encoding="utf-8")
        assert result["cleared_files"] == 1
        assert "old" not in content
        assert content.count("phrolova.youtube | new") == 1
    finally:
        logger.handlers = original_handlers
        handler.close()
