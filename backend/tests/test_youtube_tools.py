import hashlib
import io
import json
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


def test_owned_server_binds_loopback_and_is_reaped(tmp_path, monkeypatch):
    result, bundle = manager(tmp_path, monkeypatch)
    get_settings().youtube_po_token_provider_url = None
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
