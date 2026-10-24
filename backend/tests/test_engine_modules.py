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


    def test_is_recording_follows_pipeline_state(self):
        class FakePipeline:
            state = RecordingState.RECORDING

        task = ChannelTask(channel_id="abc")
        task.pipeline = FakePipeline()
        assert task.is_recording is True

        FakePipeline.state = RecordingState.COMPLETED
        assert task.is_recording is False


    def test_tags_default_is_independent_per_instance(self):
        """가변 기본값이 인스턴스 간에 공유되면 안 된다."""
        a, b = ChannelTask(channel_id="a"), ChannelTask(channel_id="b")
        a.tags.append("게임")
        assert b.tags == []




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


    def test_youtube_engine_satisfies_protocol(self):
        from app.engine.youtube import YoutubeLiveEngine

        assert issubclass(YoutubeLiveEngine, PlatformEngine)
