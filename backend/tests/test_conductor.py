"""
test_conductor.py
채널 등록/제거, 자동녹화 토글, persistence 저장/로드, get_all_status() 응답 형식 테스트
"""

import pytest
from unittest.mock import Mock, patch
from app.engine.conductor import Conductor, ChannelTask
from app.engine.base import Platform


class TestChannelTask:
    """ChannelTask 데이터 클래스 테스트"""

    def test_default_values(self):
        """기본값 확인"""
        task = ChannelTask(channel_id="test_channel")

        assert task.channel_id == "test_channel"
        assert task.auto_record is True
        assert task.pipeline is None
        assert task.chat_archiver is None
        assert task.monitor_task is None
        assert task.is_live is False
        assert task.channel_name is None
        assert task.title is None
        assert task.category is None
        assert task.viewer_count == 0
        assert task.thumbnail_url is None
        assert task.profile_image_url is None

    def test_custom_values(self):
        """커스텀 값 설정"""
        task = ChannelTask(
            channel_id="custom_channel",
            auto_record=False,
            is_live=True,
            channel_name="타냐 TV",
            title="오늘의 방송",
            viewer_count=1234,
        )

        assert task.channel_id == "custom_channel"
        assert task.auto_record is False
        assert task.is_live is True
        assert task.channel_name == "타냐 TV"
        assert task.title == "오늘의 방송"
        assert task.viewer_count == 1234


class TestConductor:
    """Conductor 클래스 테스트"""

    @pytest.fixture
    def isolated_conductor(self):
        """빈 임시 저장소를 쓰는 Conductor (conftest의 isolated_database가 격리한다)."""
        return Conductor()

    def test_initial_state(self, isolated_conductor):
        """초기 상태 확인"""
        conductor = isolated_conductor

        assert conductor.is_running is False
        assert conductor.channel_count == 0

    def test_add_channel(self, isolated_conductor):
        """채널 등록"""
        conductor = isolated_conductor
        key = Conductor.make_composite_key(Platform.CHZZK, "test_channel_1")

        conductor.add_channel(channel_id="test_channel_1", auto_record=True)

        assert conductor.channel_count == 1
        assert key in conductor._channels
        assert conductor._channels[key].auto_record is True

    def test_add_multiple_channels(self, isolated_conductor):
        """여러 채널 등록"""
        conductor = isolated_conductor

        conductor.add_channel(channel_id="channel_1")
        conductor.add_channel(channel_id="channel_2")
        conductor.add_channel(channel_id="channel_3", auto_record=False)

        assert conductor.channel_count == 3
        assert conductor._channels[Conductor.make_composite_key(Platform.CHZZK, "channel_1")].auto_record is True
        assert conductor._channels[Conductor.make_composite_key(Platform.CHZZK, "channel_2")].auto_record is True
        assert conductor._channels[Conductor.make_composite_key(Platform.CHZZK, "channel_3")].auto_record is False

    def test_add_duplicate_channel(self, isolated_conductor):
        """중복 채널 등록 (무시됨)"""
        conductor = isolated_conductor
        key = Conductor.make_composite_key(Platform.CHZZK, "test_channel")

        conductor.add_channel(channel_id="test_channel", auto_record=True)
        conductor.add_channel(channel_id="test_channel", auto_record=False)

        assert conductor.channel_count == 1
        # 중복 등록은 무시되므로 첫 번째 값 유지
        assert conductor._channels[key].auto_record is True

    @pytest.mark.asyncio
    async def test_remove_channel(self, isolated_conductor):
        """채널 제거"""
        conductor = isolated_conductor
        key = Conductor.make_composite_key(Platform.CHZZK, "test_channel")

        conductor.add_channel(channel_id="test_channel")
        assert conductor.channel_count == 1

        await conductor.remove_channel(key)

        assert conductor.channel_count == 0
        assert key not in conductor._channels

    @pytest.mark.asyncio
    async def test_remove_nonexistent_channel(self, isolated_conductor):
        """존재하지 않는 채널 제거 시도"""
        conductor = isolated_conductor

        # 예외 발생 없이 경고 로그만 출력
        await conductor.remove_channel(Conductor.make_composite_key(Platform.CHZZK, "nonexistent"))

        assert conductor.channel_count == 0

    @pytest.mark.asyncio
    async def test_toggle_auto_record(self, isolated_conductor):
        """자동 녹화 토글"""
        conductor = isolated_conductor
        key = Conductor.make_composite_key(Platform.CHZZK, "test_channel")

        conductor.add_channel(channel_id="test_channel", auto_record=True)

        # True → False (is_live=False이므로 즉시 녹화 시작 없음)
        new_value = await conductor.toggle_auto_record(key)
        assert new_value is False
        assert conductor._channels[key].auto_record is False

        # False → True
        new_value = await conductor.toggle_auto_record(key)
        assert new_value is True
        assert conductor._channels[key].auto_record is True

    @pytest.mark.asyncio
    async def test_toggle_auto_record_nonexistent(self, isolated_conductor):
        """존재하지 않는 채널의 자동 녹화 토글 시도"""
        conductor = isolated_conductor

        # Conductor.toggle_auto_record는 ValueError 발생
        with pytest.raises(ValueError, match="찾을 수 없습니다"):
            await conductor.toggle_auto_record(Conductor.make_composite_key(Platform.CHZZK, "nonexistent"))

    def test_get_all_status_empty(self, isolated_conductor):
        """빈 채널 목록 상태 조회"""
        conductor = isolated_conductor

        status = conductor.get_all_status()

        assert status == []

    def test_get_all_status_with_channels(self, isolated_conductor):
        """채널 상태 조회"""
        conductor = isolated_conductor

        conductor.add_channel(channel_id="channel_1", auto_record=True)
        conductor.add_channel(channel_id="channel_2", auto_record=False)

        status = conductor.get_all_status()

        assert len(status) == 2

        # 첫 번째 채널
        ch1 = next(ch for ch in status if ch["channel_id"] == "channel_1")
        assert ch1["auto_record"] is True
        assert ch1["is_live"] is False
        assert ch1["recording"] is None
        assert ch1["chat_archiving"] is None

        # 두 번째 채널
        ch2 = next(ch for ch in status if ch["channel_id"] == "channel_2")
        assert ch2["auto_record"] is False

    def test_get_all_status_response_format(self, isolated_conductor):
        """get_all_status() 응답 형식 검증"""
        conductor = isolated_conductor

        conductor.add_channel(channel_id="test_channel")

        status = conductor.get_all_status()

        assert isinstance(status, list)
        assert len(status) == 1

        channel_status = status[0]

        # 필수 필드 확인
        assert "channel_id" in channel_status
        assert "auto_record" in channel_status
        assert "is_live" in channel_status
        assert "recording" in channel_status
        assert "chat_archiving" in channel_status
        assert "channel_name" in channel_status
        assert "title" in channel_status
        assert "category" in channel_status
        assert "viewer_count" in channel_status
        assert "thumbnail_url" in channel_status
        assert "profile_image_url" in channel_status

    def test_persistence_save_and_load(self):
        """채널 데이터가 저장소에 남아 새 Conductor에서 복원된다."""
        conductor1 = Conductor()
        conductor1.add_channel(channel_id="channel_1", auto_record=True)
        conductor1.add_channel(channel_id="channel_2", auto_record=False)

        # 새 인스턴스 = 앱 재시작. 생성자에서 저장소를 읽는다.
        conductor2 = Conductor()

        key1 = Conductor.make_composite_key(Platform.CHZZK, "channel_1")
        key2 = Conductor.make_composite_key(Platform.CHZZK, "channel_2")

        assert conductor2.channel_count == 2
        assert conductor2._channels[key1].auto_record is True
        assert conductor2._channels[key2].auto_record is False

    def test_persistence_empty_store(self):
        """빈 저장소에서 시작해도 예외 없이 빈 상태가 된다."""
        conductor = Conductor()
        assert conductor.channel_count == 0

    def test_persistence_restores_tags_and_capture_state(self):
        """태그와 X Spaces 캡처 정보가 재시작 후에도 복원된다."""
        conductor1 = Conductor()
        conductor1.add_channel(
            channel_id="someone", auto_record=True, platform=Platform.X_SPACES
        )
        key = Conductor.make_composite_key(Platform.X_SPACES, "someone")
        conductor1.set_channel_tags(key, ["스페이스"])

        task = conductor1._channels[key]
        task.master_url = "https://master.example/playlist.m3u8"
        task.master_url_captured_at = "2026-01-01T00:00:00"
        conductor1._save_capture_state(key)

        conductor2 = Conductor()
        restored = conductor2._channels[key]

        assert restored.tags == ["스페이스"]
        assert restored.master_url == "https://master.example/playlist.m3u8"

    def test_removed_channel_does_not_come_back(self):
        """제거한 채널이 재시작 후 되살아나면 안 된다."""
        import asyncio

        conductor1 = Conductor()
        conductor1.add_channel(channel_id="temp_channel")
        key = Conductor.make_composite_key(Platform.CHZZK, "temp_channel")
        asyncio.run(conductor1.remove_channel(key))

        assert Conductor().channel_count == 0

    def test_live_detections_survive_restart(self):
        """라이브 감지 통계가 재시작으로 초기화되면 안 된다."""
        conductor1 = Conductor()
        conductor1.add_channel(channel_id="channel_1")
        key = Conductor.make_composite_key(Platform.CHZZK, "channel_1")
        conductor1._history_repo.record_detection(key, day="2026-01-01")

        counts = Conductor().get_live_detections()
        # 30일 창을 벗어난 날짜라 0건이지만, 기록 자체는 저장소에 남아 있다.
        assert isinstance(counts, dict)
        assert conductor1._history_repo.detection_counts(days=36500)[key] == 1


class TestGlobalTagDeletion:
    """태그를 전역에서 지우면 붙어 있던 채널에서도 떨어져야 한다.

    화면에 삭제 버튼이 생기면서 실제로 눌리는 경로가 됐다. 메모리에서만 지우고
    저장소를 놓치면 재시작할 때 태그가 되살아난다 — 그 경계를 여기서 잡는다.
    """

    def _conductor_with_tagged_channels(self):
        conductor = Conductor()
        conductor.add_channel(channel_id="ch_a", auto_record=True)
        conductor.add_channel(channel_id="ch_b", auto_record=True)
        key_a = Conductor.make_composite_key(Platform.CHZZK, "ch_a")
        key_b = Conductor.make_composite_key(Platform.CHZZK, "ch_b")
        conductor.set_channel_tags(key_a, ["게임", "저녁방송"])
        conductor.set_channel_tags(key_b, ["게임"])
        return conductor, key_a, key_b

    def test_tag_is_stripped_from_every_channel(self):
        conductor, key_a, key_b = self._conductor_with_tagged_channels()

        assert conductor.remove_tag_from_all_channels("게임") is True

        assert conductor._channels[key_a].tags == ["저녁방송"]
        assert conductor._channels[key_b].tags == []

    def test_removal_survives_restart(self):
        """저장소까지 반영돼야 재시작 후에도 태그가 돌아오지 않는다."""
        conductor, key_a, key_b = self._conductor_with_tagged_channels()
        conductor.remove_tag_from_all_channels("게임")

        restarted = Conductor()  # 새 인스턴스 = 앱 재시작

        assert restarted._channels[key_a].tags == ["저녁방송"]
        assert restarted._channels[key_b].tags == []

    def test_other_tags_are_left_alone(self):
        conductor, key_a, _ = self._conductor_with_tagged_channels()

        conductor.remove_tag_from_all_channels("게임")

        assert "저녁방송" in conductor._channels[key_a].tags

    def test_unused_tag_reports_no_change(self):
        """아무 채널도 쓰지 않는 태그를 지우면 채널 쪽은 건드리지 않는다."""
        conductor, key_a, key_b = self._conductor_with_tagged_channels()

        assert conductor.remove_tag_from_all_channels("아무도안씀") is False

        assert conductor._channels[key_a].tags == ["게임", "저녁방송"]
        assert conductor._channels[key_b].tags == ["게임"]


class TestRecordingCookie:
    """치지직 녹화에는 대체 쿠키 파일을 전달하지 않는다."""


    @pytest.fixture
    def lent_cookies(self, monkeypatch):
        """파이프라인이 받은 대체 쿠키 파일과 그 순간의 내용을 기록한다."""
        from pathlib import Path

        seen = []

        class FakePipeline:
            def __init__(self, channel_id):
                self.channel_id = channel_id

            async def start_recording(self, **kwargs):
                lent = kwargs.get("fallback_cookie_file")
                seen.append((lent, Path(lent).read_text(encoding="utf-8") if lent else None))
                return "live.ts"

            def get_status(self):
                # 상태 방송(_broadcast_status)이 부른다.
                return {"is_recording": True, "state": "recording"}

        monkeypatch.setattr("app.engine.conductor.YtdlpLivePipeline", FakePipeline)
        return seen

    async def _start(self, monkeypatch, platform, channel_id):
        from unittest.mock import AsyncMock

        conductor = Conductor()
        monkeypatch.setattr(conductor, "_start_chat_archiver", AsyncMock())
        conductor.add_channel(channel_id=channel_id, platform=platform)
        key = Conductor.make_composite_key(platform, channel_id)
        await conductor._start_recording(key, is_retry=True)
        return conductor._channels[key]


    @pytest.mark.asyncio
    async def test_chzzk_gets_nothing(self, lent_cookies, monkeypatch):
        seen = lent_cookies

        task = await self._start(monkeypatch, Platform.CHZZK, "abcdef0123456789abcdef0123456789")

        assert task.last_error is None
        assert seen == [(None, None)]
