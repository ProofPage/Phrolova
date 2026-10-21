"""시작 화면과 실제 로그의 플랫폼·오류 분류가 서로 섞이지 않는지 검증한다."""
import importlib.util
import io
import logging
from pathlib import Path

import httpx
import pytest

from app.core.console import display_width
from app.core.logger import _AccessLogFilter, _attach_uvicorn_logging, _make_formatter, get_platform_logger, logger


@pytest.fixture
def desktop(monkeypatch):
    from app.engine.youtube_tools import youtube_tools
    monkeypatch.setattr(youtube_tools, "status", "ready")
    monkeypatch.setattr(youtube_tools, "message", "Deno·bgutil 준비 완료")
    spec = importlib.util.spec_from_file_location("console_run_test", Path(__file__).parents[1] / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_check_python_version", lambda: True)
    monkeypatch.setattr(module, "_get_streamlink_version", lambda: "8.6.2")
    monkeypatch.setattr(module, "_find_ytdlp", lambda: "C:/tools/yt-dlp.exe")
    monkeypatch.setattr(module.shutil, "get_terminal_size", lambda fallback: __import__('os').terminal_size((80, 24)))
    return module


def test_dependency_screen_wraps_paths_without_separator(desktop, monkeypatch, capsys):
    import app.engine.media_tools as media
    long_path = 'C:/Users/Administrator/AppData/Local/Microsoft/WinGet/Packages/' + '한글경로/' * 15 + 'ffprobe.exe'
    monkeypatch.setattr(media, "check_media_tool", lambda tool: dict(available=True, path=long_path, version="9.0.2"))
    assert desktop._run_dependency_check()
    output = capsys.readouterr().out
    assert "=" * 10 not in output
    assert "모든 항목 정상" in output
    assert all(display_width(line) <= 80 for line in output.splitlines())
    assert "FFprobe" in output and "Streamlink" in output
    assert all(line.startswith('         ') for line in output.splitlines() if '한글' in line)


def test_missing_optional_probe_is_warning_not_all_success(desktop, monkeypatch, capsys):
    import app.engine.media_tools as media
    monkeypatch.setattr(media, "check_media_tool", lambda tool: dict(available=tool == 'ffmpeg', path='ffmpeg', message='FFprobe 없음'))
    assert desktop._run_dependency_check()
    output = capsys.readouterr().out
    assert "주의 1건" in output and "모든 항목 정상" not in output
    assert "FFPROBE_PATH" in output


def test_youtube_setup_failure_is_warning_not_all_success(desktop, monkeypatch, capsys):
    import app.engine.media_tools as media
    from app.engine.youtube_tools import youtube_tools
    monkeypatch.setattr(media, "check_media_tool", lambda tool: dict(available=True, path=tool, version="9.0.2"))
    monkeypatch.setattr(youtube_tools, "status", "failed")
    monkeypatch.setattr(youtube_tools, "message", "Deno download failed")
    assert desktop._run_dependency_check()
    output = capsys.readouterr().out
    assert "YouTube" in output and "Deno download failed" in output
    assert "주의 1건" in output and "모든 항목 정상" not in output


def access_record(status):
    return logging.LogRecord('uvicorn.access', logging.INFO, '', 1, '%s - "%s %s HTTP/%s" %d',
                             ('127.0.0.1:12', 'GET', '/api/platforms/status', '1.1', status), None)


@pytest.mark.parametrize('status,visible,level', [(200,False,'INFO'),(304,False,'INFO'),(404,True,'WARNING'),(503,True,'ERROR')])
def test_http_failures_visible_and_classified_without_changing_shared_record(status, visible, level):
    record = access_record(status)
    assert _AccessLogFilter().filter(record) is visible
    text = _make_formatter().format(record)
    assert level in text and 'HTTP' in text
    assert record.levelno == logging.INFO
    assert _AccessLogFilter(debug=True).filter(record)


def test_normal_server_start_is_not_named_error():
    record = logging.LogRecord('uvicorn.error', logging.INFO, '', 1, 'Application startup complete.', (), None)
    text = _make_formatter().format(record)
    assert 'SERVER' in text and 'INFO' in text
    assert 'uvicorn.error' not in text


def test_third_party_lowercase_level_names_do_not_break_log_viewer():
    record = logging.LogRecord('phrolova.cime', logging.ERROR, '', 1, 'failed', (), None)
    record.levelname = 'error'
    assert '| ERROR ' in _make_formatter().format(record)
    assert record.levelname == 'error'


def test_exception_details_are_redacted_in_both_handlers():
    import sys
    try:
        raise RuntimeError('https://user:password@example.com/video?token=private Cookie: session=secret')
    except RuntimeError:
        record = logging.LogRecord('phrolova.youtube.recording', logging.ERROR, '', 1, 'record failed', (), sys.exc_info())
    for formatter in (_make_formatter(),_make_formatter(console=True)):
        output = formatter.format(record)
        assert 'RuntimeError' in output and 'YOUTUBE/RECORDING' in output
        assert all(word not in output for word in ('password','private','secret'))
    assert record.exc_text is None


@pytest.mark.parametrize('threshold', [logging.INFO, logging.WARNING])
def test_shared_handlers_write_http_errors_once(tmp_path, threshold):
    names = ('uvicorn', 'uvicorn.access', 'uvicorn.error', 'uvicorn.asgi')
    originals = {name:(logging.getLogger(name).handlers[:], logging.getLogger(name).filters[:], logging.getLogger(name).level, logging.getLogger(name).propagate) for name in names}
    output = io.StringIO()
    target = logging.getLogger('console_diagnostics_isolated')
    console = logging.StreamHandler(output)
    file = logging.FileHandler(tmp_path/'service.log',encoding='utf-8')
    for handler in (console,file):
        handler.setFormatter(_make_formatter())
    target.handlers = [console,file]
    target.setLevel(threshold)
    try:
        _attach_uvicorn_logging(target)
        _attach_uvicorn_logging(target)
        logging.getLogger('uvicorn.access').handle(access_record(200))
        logging.getLogger('uvicorn.access').handle(access_record(500))
        logging.getLogger('uvicorn.error').info('started')
        file.flush()
        for text in (output.getvalue(),(tmp_path/'service.log').read_text(encoding='utf-8')):
            assert text.count('500') == 1 and '200' not in text
            assert text.count('started') == (1 if threshold == logging.INFO else 0)
    finally:
        file.close()
        target.handlers = []
        for name,(handlers,filters,level,propagate) in originals.items():
            item = logging.getLogger(name)
            item.handlers, item.filters = handlers, filters
            item.setLevel(level)
            item.propagate = propagate


def test_scan_all_channels_is_system_work_not_external_platform():
    assert get_platform_logger(None, 'live').name == 'phrolova.live'


def test_pipeline_loggers_are_per_channel_and_platform():
    from app.engine.pipeline import YtdlpLivePipeline
    a,b = YtdlpLivePipeline('same'),YtdlpLivePipeline('same')
    a._logger = get_platform_logger('chzzk','recording')
    b._logger = get_platform_logger('cime','recording')
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(_make_formatter())
    logger.addHandler(handler)
    try:
        a._logger.warning('[same] first')
        b._logger.warning('[same] second')
    finally:
        logger.removeHandler(handler)
    lines = output.getvalue().splitlines()
    assert 'CHZZK/RECORDING' in lines[0] and 'CIME/RECORDING' in lines[1]


@pytest.fixture
def update_http(monkeypatch):
    import app.engine.updater as updater
    original = httpx.AsyncClient
    def use(handler):
        monkeypatch.setattr(updater.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler),**kwargs))
    return use


@pytest.mark.asyncio
@pytest.mark.parametrize('status,headers,code', [(404,{},'release_unavailable'),(403,{'x-ratelimit-remaining':'0'},'rate_limit'),(429,{},'rate_limit'),(502,{},'http_error')])
async def test_update_http_failure_never_claims_latest_or_no_releases(update_http, status, headers, code):
    from app.engine.updater import UpdaterService
    update_http(lambda request:httpx.Response(status,headers=headers))
    service = UpdaterService()
    result = await service.check_update_now()
    assert result['check_error'] == {'code':code,'status':status}
    assert result['checked_at'] is None
    assert service.get_cached_info()['check_error'] == result['check_error']


@pytest.mark.asyncio
async def test_update_timeout_cache_and_recovery(update_http):
    from app.engine.updater import UpdaterService
    service = UpdaterService()
    update_http(lambda request:httpx.Response(200,json={'tag_name':'v9.0.0'}))
    good = await service.check_update_now()
    def timeout(request):
        raise httpx.ReadTimeout('timeout',request=request)
    update_http(timeout)
    stale = await service.check_update_now()
    assert stale['check_error']['code'] == 'timeout'
    assert stale['latest_version'] == good['latest_version']
    assert stale['checked_at'] == good['checked_at']
    update_http(lambda request:httpx.Response(200,json={'tag_name':'v9.0.0'}))
    assert 'check_error' not in await service.check_update_now()
    assert not service.get_cached_info().get('check_error')


def test_check_python_version_requires_3148_standard_gil(monkeypatch):
    import sys
    spec = importlib.util.spec_from_file_location("console_run_real", Path(__file__).parents[1] / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(sys, "version_info", (3, 14, 8, "final", 0))
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: True, raising=False)
    assert module._check_python_version() is True

    # Free-threaded Python 3.14 (GIL disabled) rejected
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: False, raising=False)
    assert module._check_python_version() is False

    # Older Python versions rejected
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: True, raising=False)
    monkeypatch.setattr(sys, "version_info", (3, 12, 10, "final", 0))
    assert module._check_python_version() is False
    monkeypatch.setattr(sys, "version_info", (3, 14, 7, "final", 0))
    assert module._check_python_version() is False
