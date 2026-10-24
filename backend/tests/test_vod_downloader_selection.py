"""선택 도구 설치 여부가 기본 HLS 다운로드를 깨뜨리지 않아야 한다."""
from app.core.config import Settings
from app.engine.vod import VodEngine, VodDownloadTask
from yt_dlp.downloader import get_suitable_downloader
from yt_dlp.downloader.hls import HlsFD


def test_optional_downloader_does_not_break_native_hls(monkeypatch, tmp_path):
    monkeypatch.setattr(Settings, "resolve_nm3u8dl_path", lambda _: "C:/tools/N_m3u8DL-RE.exe")
    engine = VodEngine()
    task = VodDownloadTask(
        url="https://vod.sooplive.com/player/210593175",
        output_dir=str(tmp_path),
    )
    options = engine._build_ytdlp_options(task)
    selected = get_suitable_downloader(
        {"url": "https://cdn.example/video.m3u8", "protocol": "m3u8_native",
         "is_live": False, "to_stdout": False},
        options,
    )
    assert selected is HlsFD
