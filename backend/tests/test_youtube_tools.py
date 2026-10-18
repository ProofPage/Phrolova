import hashlib
import io
import json
import logging
import zipfile
from unittest.mock import Mock

import pytest

from app.engine import youtube_tools as tools
from app.engine.youtube_support import require_runtime_cli_options, youtube_options
from app.core.config import get_settings


def manager(tmp_path, monkeypatch):
    result = tools.YouTubeTools()
    result.root = lambda: tmp_path
    bundle = tmp_path / "install-fixture"
    (bundle / "server/node_modules").mkdir(parents=True)
    (bundle / "server/src").mkdir()
    (bundle / "server/src/main.ts").write_text("// fixture")
    result.executable(bundle).write_bytes(b"deno fixture")
    (bundle / "plugins").mkdir()
    (bundle / "plugins/bgutil.zip").write_bytes(b"plugin fixture")
    monkeypatch.setattr(result, "activate_plugins", Mock())
    monkeypatch.setattr(result, "ping", lambda: True)
    return result, bundle


def test_first_setup_records_success_and_following_start_skips_install(tmp_path, monkeypatch):
    result, bundle = manager(tmp_path, monkeypatch)
    monkeypatch.setattr(result, "load_bundle", Mock(side_effect=FileNotFoundError()))
    install = Mock(return_value=bundle)
    monkeypatch.setattr(result, "install", install)
    result.prepare()
    assert result.status == "ready"
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["directory"] == bundle.name
    monkeypatch.setattr(result, "load_bundle", Mock(return_value=bundle))
    result.status = "not_started"
    result.prepare()
    install.assert_called_once()
    assert result.status == "ready"


def test_failed_setup_is_not_marked_successful(tmp_path, monkeypatch):
    result, bundle = manager(tmp_path, monkeypatch)
    monkeypatch.setattr(result, "load_bundle", Mock(side_effect=FileNotFoundError()))
    monkeypatch.setattr(result, "install", Mock(side_effect=RuntimeError("download failed")))
    result.prepare()
    assert result.status == "failed"
    assert not (tmp_path / "state.json").exists()
    assert "download failed" in result.message
    result.prepare()
    result.install.assert_called_once()


def test_corrupted_install_is_not_trusted(tmp_path, monkeypatch):
    result, bundle = manager(tmp_path, monkeypatch)
    (tmp_path / "state.json").write_text(json.dumps({
        "directory": bundle.name, "version": tools.PROVIDER_VERSION,
        "deno_version": tools.DENO_VERSION, "deno_hash": "0" * 64}))
    with pytest.raises(ValueError):
        result.load_bundle()


def test_zip_traversal_is_rejected(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("../outside", "unsafe")
    with pytest.raises(ValueError):
        tools.unpack(data.getvalue(), tmp_path)
    assert not (tmp_path.parent / "outside").exists()


def test_download_hash_mismatch_is_rejected(monkeypatch):
    from contextlib import contextmanager
    @contextmanager
    def stream(*args, **kwargs):
        yield type("Response", (), {"raise_for_status": lambda self: None,
                                   "iter_bytes": lambda self: [b"wrong"]})()
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.stream = stream
    monkeypatch.setattr(tools.httpx, "Client", lambda **kw: client)
    with pytest.raises(ValueError, match="SHA-256"):
        tools.download("https://github.com/example/archive.zip", "0" * 64)


def test_external_provider_option_is_shared_between_python_and_cli(monkeypatch):
    get_settings().youtube_po_token_provider_url = "http://127.0.0.1:9876"
    assert youtube_options()["extractor_args"]["youtubepot-bgutilhttp"]["base_url"] == ["http://127.0.0.1:9876"]
    assert "youtubepot-bgutilhttp:base_url=http://127.0.0.1:9876" in require_runtime_cli_options()


def test_stop_does_not_terminate_an_existing_external_server():
    instance = tools.YouTubeTools()
    instance.stop_process()
    assert instance.process is None


@pytest.mark.parametrize("provider", [None, "", tools.LOCAL_URL, tools.LOCAL_URL + "/"])
def test_owned_server_binds_loopback_and_is_reaped(tmp_path, monkeypatch, provider):
    result, bundle = manager(tmp_path, monkeypatch)
    get_settings().youtube_po_token_provider_url = provider
    monkeypatch.setattr(result, "load_bundle", lambda: bundle)
    process = Mock()
    process.poll.return_value = None
    spawned = Mock(return_value=process)
    monkeypatch.setattr(tools.subprocess, "Popen", spawned)
    monkeypatch.setattr(result, "ping", lambda: spawned.called)
    result.prepare()
    assert result.status == "ready"
    command = spawned.call_args.args[0]
    assert command[-2:] == ["--host", "127.0.0.1"]
    assert result.process_log is not None
    result.stop_process()
    process.terminate.assert_called_once()
    process.wait.assert_called_once()
    assert result.process is None and result.process_log is None


@pytest.mark.asyncio
async def test_custom_provider_can_be_cleared_and_persisted(tmp_path, monkeypatch):
    from app.api.settings import media
    from app.core.config import Settings
    saved = {}
    monkeypatch.setattr(media, "_update_env_file", lambda values, **kw: saved.update(values))
    get_settings().youtube_po_token_provider_url = "http://127.0.0.1:9876"
    await media.update_download_settings(media.DownloadSettingsUpdateRequest(
        max_record_retries=get_settings().max_record_retries, youtube_po_token_provider_url=""))
    assert saved["YOUTUBE_PO_TOKEN_PROVIDER_URL"] == ""
    assert not get_settings().youtube_po_token_provider_url
    assert not Settings(_env_file=None, youtube_po_token_provider_url=saved["YOUTUBE_PO_TOKEN_PROVIDER_URL"]).youtube_po_token_provider_url


def test_concurrent_startup_installs_only_once(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    result, bundle = manager(tmp_path, monkeypatch)
    get_settings().youtube_po_token_provider_url = None
    monkeypatch.setattr(result, "load_bundle", Mock(side_effect=FileNotFoundError()))
    monkeypatch.setattr(result, "install", Mock(return_value=bundle))
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: result.prepare(), range(2)))
    result.install.assert_called_once()
    assert result.status == "ready"


@pytest.fixture
def shared_tool_log():
    from app.core.logger import logger
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    logger.addHandler(handler)
    try:
        yield output
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_cached_setup_reaches_shared_log_and_skips_download(tmp_path, monkeypatch, shared_tool_log):
    result, bundle = manager(tmp_path, monkeypatch)
    monkeypatch.setattr(result, "load_bundle", lambda: bundle)
    download = Mock(side_effect=AssertionError("cached setup must not download"))
    monkeypatch.setattr(tools, "download", download)
    get_settings().youtube_po_token_provider_url = None
    result.prepare()
    text = shared_tool_log.getvalue()
    for message in ("YouTube 보조 도구 검사 중", "재설치 생략", "플러그인 로드·확인 중",
                    "중복 실행 생략", "Deno·bgutil 서버 연결 설정·PO Token 플러그인 준비 완료"):
        assert text.count(message) == 1
    assert result.status == "ready"
    download.assert_not_called()


def test_install_reports_each_download_and_dependency_stage(tmp_path, monkeypatch, shared_tool_log):
    result = tools.YouTubeTools()
    result.root = lambda: tmp_path
    get_settings().youtube_po_token_provider_url = None
    monkeypatch.setattr(tools, "target", lambda: "x86_64-pc-windows-msvc")
    monkeypatch.setattr(tools, "download", Mock(return_value=b"verified archive"))

    def unpack(data, bundle, prefix=""):
        result.executable(bundle).write_bytes(b"deno fixture")
        (bundle / "server/node_modules").mkdir(parents=True, exist_ok=True)
        (bundle / "server/src").mkdir(exist_ok=True)
        (bundle / "server/src/main.ts").write_text("// fixture")

    monkeypatch.setattr(tools, "unpack", unpack)
    monkeypatch.setattr(result, "run", Mock())
    monkeypatch.setattr(result, "activate_plugins", Mock())
    monkeypatch.setattr(result, "ping", lambda: True)
    result.prepare()
    text = shared_tool_log.getvalue()
    positions = [text.index(f"[{stage}/6]") for stage in range(1, 7)]
    assert positions == sorted(positions)
    assert all(text.count(f"[{stage}/6]") == 1 for stage in range(1, 7))
    assert "240초" in text
    assert result.status == "ready"
    assert (tmp_path / "state.json").is_file()
    assert result.run.call_args_list[-1].args[0][-1] == "--version"


def test_failure_reports_stage_through_shared_log_without_success(tmp_path, monkeypatch, shared_tool_log):
    result, bundle = manager(tmp_path, monkeypatch)
    monkeypatch.setattr(result, "load_bundle", lambda: bundle)
    monkeypatch.setattr(result, "activate_plugins", Mock(side_effect=RuntimeError("plugin load failed")))
    result.prepare()
    text = shared_tool_log.getvalue()
    assert result.status == "failed"
    assert "플러그인 로드·확인 중" in result.message
    assert "plugin load failed" in result.message
    assert "YouTube 도구 준비 실패" in text
    assert "다른 플랫폼은 계속 실행합니다" in text
    assert "준비 완료" not in text
    assert not (tmp_path / "state.json").exists()


def test_external_provider_is_not_reported_as_health_checked(tmp_path, monkeypatch, shared_tool_log):
    result, bundle = manager(tmp_path, monkeypatch)
    monkeypatch.setattr(result, "load_bundle", lambda: bundle)
    get_settings().youtube_po_token_provider_url = "http://127.0.0.1:9876"
    ping = Mock(side_effect=AssertionError("external provider must not use local ping"))
    monkeypatch.setattr(result, "ping", ping)
    result.prepare()
    text = shared_tool_log.getvalue()
    assert result.status == "ready"
    assert "사용자 지정 PO Token 서버 설정 유지" in text
    assert "응답 확인 완료" not in text
    assert result.process is None
    ping.assert_not_called()


@pytest.mark.asyncio
async def test_slow_setup_does_not_block_event_loop(tmp_path, monkeypatch):
    import asyncio
    import threading
    result = tools.YouTubeTools()
    started, release = threading.Event(), threading.Event()

    def prepare():
        started.set()
        assert release.wait(5)

    monkeypatch.setattr(result, "prepare", prepare)
    task = asyncio.create_task(result.ready())
    try:
        assert await asyncio.to_thread(started.wait, 5)
        await asyncio.wait_for(asyncio.sleep(0), 1)
        assert not task.done()
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_server_startup_waits_for_youtube_preparation(monkeypatch):
    import asyncio
    from fastapi import FastAPI
    from app.main import lifespan
    from app.engine import media_tools
    started, release = asyncio.Event(), asyncio.Event()

    async def ready():
        started.set()
        await release.wait()

    monkeypatch.setattr(tools.youtube_tools, "ready", ready)
    check = Mock(side_effect=RuntimeError("startup checkpoint"))
    monkeypatch.setattr(media_tools, "check_media_tool", check)
    startup = asyncio.create_task(lifespan(FastAPI()).__aenter__())
    await started.wait()
    try:
        check.assert_not_called()
        assert not startup.done()
    finally:
        release.set()
        with pytest.raises(RuntimeError, match="startup checkpoint"):
            await startup
    check.assert_called_once()
