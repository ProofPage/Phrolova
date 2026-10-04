"""
test_engine_modules.py
Conductor에서 분리한 모듈들의 단위 테스트.

분리 전에는 이 로직들이 1200줄짜리 Conductor 안에 묶여 있어
전체 감시 루프를 띄우지 않고는 검증할 수 없었다.
"""

import asyncio
import json

import pytest

from app.core import http as http_module
from app.engine.base import Platform, PlatformEngine
from app.engine.channel import ChannelTask
from app.engine.events import EventBus
from app.engine.pipeline import RecordingState
from app.engine.spaces_recorder import SpacesRecorder


class TestEventBus:
    def test_publish_reaches_all_subscribers(self):
        bus = EventBus()
        a, b = asyncio.Queue(), asyncio.Queue()
        bus.subscribe(a)
        bus.subscribe(b)

        bus.publish("status_update", [{"channel_id": "abc"}])

        for queue in (a, b):
            raw = queue.get_nowait()
            assert raw.startswith("data: ")
            assert raw.endswith("\n\n")
            payload = json.loads(raw[len("data: ") :])
            assert payload["type"] == "status_update"
            assert payload["data"][0]["channel_id"] == "abc"

    def test_publish_without_data_omits_field(self):
        bus = EventBus()
        queue = asyncio.Queue()
        bus.subscribe(queue)

        bus.publish("shutdown")

        payload = json.loads(queue.get_nowait()[len("data: ") :])
        assert payload == {"type": "shutdown"}

    def test_unsubscribe_stops_delivery(self):
        bus = EventBus()
        queue = asyncio.Queue()
        bus.subscribe(queue)
        bus.unsubscribe(queue)

        bus.publish("status_update", [])

        assert queue.empty()

    def test_duplicate_subscribe_delivers_once(self):
        bus = EventBus()
        queue = asyncio.Queue()
        bus.subscribe(queue)
        bus.subscribe(queue)

        bus.publish("status_update", [])

        assert queue.qsize() == 1

    def test_full_queue_does_not_raise(self):
        """느린 구독자 하나가 녹화 루프를 막으면 안 된다."""
        bus = EventBus()
        slow = asyncio.Queue(maxsize=1)
        healthy = asyncio.Queue()
        bus.subscribe(slow)
        bus.subscribe(healthy)

        bus.publish("status_update", [])
        bus.publish("status_update", [])  # slow는 가득 참

        assert healthy.qsize() == 2

    def test_unserializable_payload_does_not_raise(self):
        """직렬화 실패가 호출부로 전파되면 안 된다."""
        bus = EventBus()
        queue = asyncio.Queue()
        bus.subscribe(queue)

        bus.publish("status_update", [{"bad": {1, 2, 3}}])  # set은 JSON 불가

        assert queue.empty()

    def test_publish_with_no_subscribers_is_noop(self):
        EventBus().publish("status_update", [])

    def test_subscriber_count(self):
        bus = EventBus()
        assert bus.subscriber_count == 0
        bus.subscribe(asyncio.Queue())
        assert bus.subscriber_count == 1


class TestChannelTask:
    def test_display_name_prefers_channel_name(self):
        task = ChannelTask(channel_id="abc123", channel_name="테스트 채널")
        assert task.display_name == "테스트 채널"

    def test_display_name_falls_back_to_id(self):
        assert ChannelTask(channel_id="abc123").display_name == "abc123"

    def test_is_recording_false_when_idle(self):
        assert ChannelTask(channel_id="abc").is_recording is False

    def test_is_recording_true_for_spaces_process(self):
        task = ChannelTask(channel_id="user", platform=Platform.X_SPACES)
        task.spaces_process = object()  # 프로세스 핸들 존재만 확인한다
        assert task.is_recording is True

    def test_is_recording_follows_pipeline_state(self):
        class FakePipeline:
            state = RecordingState.RECORDING

        task = ChannelTask(channel_id="abc")
        task.pipeline = FakePipeline()
        assert task.is_recording is True

        FakePipeline.state = RecordingState.COMPLETED
        assert task.is_recording is False

    def test_clear_space_capture_resets_all_fields(self):
        task = ChannelTask(channel_id="user", platform=Platform.X_SPACES)
        task.master_url = "https://master"
        task.master_url_captured_at = "2026-01-01T00:00:00"
        task.captured_m3u8_url = "https://m3u8"
        task.captured_m3u8_at = "2026-01-01T00:00:00"
        task.master_url_file = "C:/urls/a.txt"
        task._current_space_id = "1abcDEF"

        task.clear_space_capture()

        assert task.master_url is None
        assert task.master_url_captured_at is None
        assert task.captured_m3u8_url is None
        assert task.captured_m3u8_at is None
        assert task.master_url_file is None
        assert task._current_space_id is None

    def test_tags_default_is_independent_per_instance(self):
        """가변 기본값이 인스턴스 간에 공유되면 안 된다."""
        a, b = ChannelTask(channel_id="a"), ChannelTask(channel_id="b")
        a.tags.append("게임")
        assert b.tags == []


class TestSpacesRecorder:
    def test_save_master_url_file_writes_url(self, tmp_path, monkeypatch):
        from app.core.config import get_settings

        settings = get_settings()
        original = settings.download_dir
        settings.download_dir = str(tmp_path)
        try:
            task = ChannelTask(
                channel_id="someone",
                platform=Platform.X_SPACES,
                channel_name="someone",
                title="테스트 스페이스",
            )
            url = "https://prod-fastly.video.pscp.tv/master_playlist.m3u8"

            path = SpacesRecorder.save_master_url_file(task, url, "1abcDEF")

            assert path is not None
            content = (tmp_path / "x_spaces_urls").glob("*.txt")
            saved = next(content).read_text(encoding="utf-8")
            assert url in saved
            assert "테스트 스페이스" in saved
            assert "1abcDEF" in saved
        finally:
            settings.download_dir = original

    def test_save_master_url_file_sanitizes_channel_name(self, tmp_path):
        """파일명에 쓸 수 없는 문자가 채널명에 있어도 저장에 성공해야 한다."""
        from app.core.config import get_settings

        settings = get_settings()
        original = settings.download_dir
        settings.download_dir = str(tmp_path)
        try:
            task = ChannelTask(
                channel_id="user",
                platform=Platform.X_SPACES,
                channel_name='bad/name:with*chars?',
            )
            path = SpacesRecorder.save_master_url_file(task, "https://m", "sid")
            assert path is not None
        finally:
            settings.download_dir = original

    def test_finalize_part_file_renames(self, tmp_path):
        final = tmp_path / "space.m4a"
        part = tmp_path / "space.m4a.part"
        part.write_bytes(b"audio")

        SpacesRecorder._finalize_part_file(str(final), "test")

        assert final.exists()
        assert not part.exists()

    def test_finalize_part_file_keeps_existing_final(self, tmp_path):
        """최종 파일이 이미 있으면 .part로 덮어쓰지 않는다."""
        final = tmp_path / "space.m4a"
        part = tmp_path / "space.m4a.part"
        final.write_bytes(b"complete")
        part.write_bytes(b"partial")

        SpacesRecorder._finalize_part_file(str(final), "test")

        assert final.read_bytes() == b"complete"

    def test_finalize_part_file_handles_none(self):
        SpacesRecorder._finalize_part_file(None, "test")

    @pytest.mark.asyncio
    async def test_start_without_space_id_raises(self):
        recorder = SpacesRecorder(lambda: None)
        task = ChannelTask(channel_id="user", platform=Platform.X_SPACES)

        with pytest.raises(ValueError):
            await recorder.start(task)

    @pytest.mark.asyncio
    async def test_stop_without_process_is_noop(self):
        recorder = SpacesRecorder(lambda: None)
        await recorder.stop(ChannelTask(channel_id="user"), label="test")


class TestSharedHttpClient:
    @pytest.mark.asyncio
    async def test_returns_same_client_within_one_loop(self):
        """폴링마다 새 클라이언트를 만들면 TLS 핸드셰이크가 반복된다."""
        try:
            first = http_module.get_http_client()
            second = http_module.get_http_client()
            assert first is second
        finally:
            await http_module.close_http_client()

    @pytest.mark.asyncio
    async def test_recreates_after_close(self):
        first = http_module.get_http_client()
        await http_module.close_http_client()
        second = http_module.get_http_client()
        try:
            assert first is not second
            assert not second.is_closed
        finally:
            await http_module.close_http_client()

    @pytest.mark.asyncio
    async def test_sets_browser_user_agent(self):
        try:
            client = http_module.get_http_client()
            assert "Mozilla/5.0" in client.headers["User-Agent"]
        finally:
            await http_module.close_http_client()


class TestPlatformEngineProtocol:
    """base.PlatformEngine이 실제로 지켜지는지 확인한다.

    이 프로토콜은 지금까지 어디서도 참조되지 않아, 엔진이 규약을 어겨도
    드러나는 곳이 없었다. CI에는 파이썬 타입 체커가 없으므로
    @runtime_checkable을 이용해 여기서 직접 확인한다.

    메서드만 있는 프로토콜이라 인스턴스를 만들지 않고 issubclass로 볼 수 있다 —
    엔진 생성자가 무엇을 하든 테스트가 영향을 받지 않는다.
    """

    def test_chzzk_engine_satisfies_protocol(self):
        from app.engine.downloader import ChzzkLiveEngine

        assert issubclass(ChzzkLiveEngine, PlatformEngine)

    def test_twitcasting_engine_satisfies_protocol(self):
        from app.engine.twitcasting import TwitcastingEngine

        assert issubclass(TwitcastingEngine, PlatformEngine)

    def test_youtube_engine_satisfies_protocol(self):
        from app.engine.youtube import YoutubeLiveEngine

        assert issubclass(YoutubeLiveEngine, PlatformEngine)

    def test_x_spaces_is_deliberately_outside_the_protocol(self):
        """X Spaces는 스트림 URL이 아니라 space_id로 녹화해 규약을 따르지 않는다.

        Conductor가 별도 경로로 처리한다는 사실을 여기에 고정해 둔다. 나중에
        누군가 get_stream_url을 얹으면 이 테스트가 그 변화를 알려준다.
        """
        from app.engine.x_spaces import XSpacesEngine

        assert not issubclass(XSpacesEngine, PlatformEngine)
