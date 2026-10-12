"""Phrolova reproductions of reference issues #190, #318, #336, #323."""

from datetime import datetime
from pathlib import Path
import pytest
import io
import struct

from app.engine.vod import VodEngine, VodDownloadTask, VodDownloadState
from app.engine.vod_preparation import quality_options


def test_portrait_quality_is_short_edge_and_real_selector():
    info = {'url': 'https://chzzk.naver.com/video/1', 'formats': [
        {'height': 1920, 'width': 1080, 'format_id': 'portrait', 'vcodec': 'h264'},
        {'height': 1280, 'width': 720, 'format_id': 'small', 'vcodec': 'h264'}]}
    assert quality_options(info) == [{'value': '1080p', 'label': '1080p'}, {'value': '720p', 'label': '720p'}]
    task = VodDownloadTask(url=info['url'], prepared=True, quality='720p', metadata={'portrait_qualities': [720, 1080]})
    assert '[width=720]' in VodEngine()._build_ytdlp_options(task)['format']


def test_interrupted_vod_restores_stable_resume_identity(tmp_path):
    engine = VodEngine()
    task = VodDownloadTask(url='https://chzzk.naver.com/video/2', output_dir=str(tmp_path),
                           state=VodDownloadState.DOWNLOADING, filename_started_at=datetime(2026, 10, 10))
    task.resolved_filename = str(tmp_path / '이전 시도.mp4')
    task.expected_part_file = task.resolved_filename + '.part'
    task.filename_template = '{title} {download_date}'
    Path(task.expected_part_file).write_bytes(b'resumable')
    engine._tasks[task.task_id] = task
    engine._save_history()
    restored = VodEngine()._tasks[task.task_id]
    assert restored.resolved_filename == task.resolved_filename
    assert restored.expected_part_file == task.expected_part_file
    assert restored.filename_started_at == task.filename_started_at
    assert Path(restored.expected_part_file).read_bytes() == b'resumable'


def test_path_budget_includes_collisions_and_fragment_suffix(tmp_path):
    from app.core.vod_filename import bounded_vod_path
    path = bounded_vod_path(tmp_path / ('한글 제목 ' * 100 + '.mp4'), collision=123)
    assert path.stem.endswith('(123)')
    assert len(path.name.encode('utf-8')) + 40 < 255
    if __import__('os').name == 'nt':
        assert len(str(path)) + 30 < 260


def test_same_size_variants_keep_highest_bitrate_selection():
    import yt_dlp
    task = VodDownloadTask(url='https://chzzk.naver.com/video/1', prepared=True, quality='720p')
    engine = VodEngine()
    selector = engine._build_ytdlp_options(task)['format']
    formats = [dict(format_id='slow', height=720, width=1280, tbr=1600, vcodec='h264', acodec='aac', url='https://example.test/a', ext='mp4'),
               dict(format_id='fast', height=720, width=1280, tbr=3200, vcodec='h264', acodec='aac', url='https://example.test/b', ext='mp4')]
    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
        result = list(ydl.build_format_selector(selector)({'formats': formats, 'incomplete_formats': False, 'has_merged_format': True}))
    assert result[0]['format_id'] == 'fast'


@pytest.mark.parametrize('kind', ['hls', 'dash'])
def test_declared_length_matched_but_truncated_boxes_never_append(kind):
    import yt_dlp
    from yt_dlp.utils import DownloadError
    from app.engine.vod_integrity import VerifiedHlsFD, VerifiedDashFD
    stream = io.BytesIO()
    # HTTP Content-Length can match this short body; the mdat declares more.
    broken = struct.pack('>I4s', 8, b'moof') + struct.pack('>I4s', 1000, b'mdat') + b'x' * 10
    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
        downloader = (VerifiedHlsFD if kind == 'hls' else VerifiedDashFD)(ydl, {})
        with pytest.raises(DownloadError, match='잘렸거나'):
            downloader._append_fragment({'dest_stream': stream}, broken)
    assert stream.closed


@pytest.mark.parametrize('status', [403, 404, 500])
def test_thousand_failed_segments_stop_with_bounded_requests(tmp_path, status):
    from tests.test_chzzk_continuity import CDN, INITIALIZATION
    from app.engine.chzzk_cdn import ChzzkCdnYoutubeDL
    from yt_dlp.utils import DownloadError
    with CDN() as cdn:
        prefix = '/primary/1080p/'
        cdn.assets[prefix + 'init.mp4'] = INITIALIZATION
        cdn.assets[prefix + 'list.m3u8'] = ('#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXT-X-MAP:URI="init.mp4"\n' +
            ''.join(f'#EXTINF:4,\n{i}.m4v\n' for i in range(1000)) + '#EXT-X-ENDLIST\n').encode()
        for i in range(1000):
            cdn.statuses[prefix + f'{i}.m4v'] = status
        options = dict(quiet=True, no_warnings=True, socket_timeout=2, retries=0,
                       fragment_retries=1, skip_unavailable_fragments=False, concurrent_fragment_downloads=2)
        with ChzzkCdnYoutubeDL(options) as ydl:
            with pytest.raises(DownloadError, match=str(status)):
                ydl.dl(str(tmp_path / 'failed.mp4'), dict(url=cdn.url('primary'), protocol='m3u8_native', ext='mp4'))
        assert sum(count for path, count in cdn.hits.items() if path.endswith('.m4v')) <= 6
        assert not (tmp_path / 'failed.mp4').exists()


@pytest.mark.parametrize('status', [403, 404])
@pytest.mark.parametrize('all_failed', [False, True])
def test_initialization_http_failure_keeps_http_category(tmp_path, status, all_failed):
    from tests.test_chzzk_continuity import CDN
    from app.engine.chzzk_cdn import ChzzkCdnYoutubeDL
    from yt_dlp.utils import DownloadError
    with CDN() as cdn:
        cdn.playlist('primary')
        cdn.statuses['/primary/1080p/init.mp4'] = status
        if all_failed:
            for i in range(4):
                cdn.statuses[f'/primary/1080p/{i}.m4v'] = status
        with ChzzkCdnYoutubeDL(dict(quiet=True, retries=0, fragment_retries=1,
                skip_unavailable_fragments=False, concurrent_fragment_downloads=2)) as ydl:
            with pytest.raises(DownloadError, match=str(status)):
                ydl.dl(str(tmp_path/'init-failed.mp4'), dict(url=cdn.url('primary'), protocol='m3u8_native', ext='mp4'))
        assert cdn.hits['/primary/1080p/init.mp4'] <= 2
        assert not (tmp_path/'init-failed.mp4').exists()


def test_master_stream_inf_without_uri_is_rejected_without_index_error():
    import yt_dlp
    from yt_dlp.extractor.common import InfoExtractor
    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
        extractor = InfoExtractor(ydl)
        formats, subtitles = extractor._parse_m3u8_formats_and_subtitles(
            '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=3200000,RESOLUTION=1280x720\n',
            'https://example.test/master.m3u8', ext='mp4')
    assert not formats and not subtitles


def test_dash_audio_without_dimensions_is_not_video_quality():
    import yt_dlp
    from yt_dlp.extractor.common import InfoExtractor
    import xml.etree.ElementTree as ET
    document = ET.fromstring('''<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" mediaPresentationDuration="PT4S">
        <Period><AdaptationSet mimeType="video/mp4" codecs="avc1.640028"><Representation id="v" width="1280" height="720" bandwidth="3200000"><BaseURL>v.mp4</BaseURL></Representation></AdaptationSet>
        <AdaptationSet mimeType="audio/mp4" codecs="mp4a.40.2"><Representation id="a" bandwidth="128000"><BaseURL>a.mp4</BaseURL></Representation></AdaptationSet></Period></MPD>''')
    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
        formats, _ = InfoExtractor(ydl)._parse_mpd_formats_and_subtitles(document, mpd_url='https://example.test/master.mpd')
    assert quality_options({'formats': formats}) == [{'value': '720p', 'label': '720p'}]


@pytest.mark.parametrize('kinds', [(b'moof', b'moof', b'mdat'), (b'mdat', b'moof'),
                                  (b'moof', b'mdat', b'moof')])
def test_each_fragment_requires_its_own_media_payload(kinds):
    from app.engine.chzzk_continuity import validate_media, Unavailable
    with pytest.raises(Unavailable):
        validate_media(b''.join(struct.pack('>I4s', 8, kind) for kind in kinds))


def test_event_boxes_between_complete_fragment_pairs_are_valid():
    from app.engine.chzzk_continuity import validate_media
    kinds = (b'emsg', b'moof', b'emsg', b'mdat', b'emsg', b'moof', b'mdat')
    validate_media(b''.join(struct.pack('>I4s', 8, kind) for kind in kinds))


def test_http_success_with_structurally_truncated_segment_never_completes(tmp_path):
    from tests.test_chzzk_continuity import CDN
    from app.engine.chzzk_cdn import ChzzkCdnYoutubeDL
    from yt_dlp.utils import DownloadError
    with CDN() as cdn:
        cdn.playlist('primary')
        cdn.assets['/primary/1080p/0.m4v'] = (
            struct.pack('>I4s', 8, b'moof') + struct.pack('>I4s', 1000, b'mdat') + b'x' * 10)
        with ChzzkCdnYoutubeDL(dict(quiet=True, retries=0, fragment_retries=0,
                skip_unavailable_fragments=False, concurrent_fragment_downloads=2)) as ydl:
            with pytest.raises(DownloadError, match='잘렸거나'):
                ydl.dl(str(tmp_path / 'truncated.mp4'),
                       dict(url=cdn.url('primary'), protocol='m3u8_native', ext='mp4'))
        assert not (tmp_path / 'truncated.mp4').exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('error_number', [13, 28])
async def test_output_os_error_finishes_and_preserves_partial_file(tmp_path, monkeypatch, error_number):
    import asyncio
    from unittest.mock import AsyncMock
    from app.core.config import get_settings
    get_settings().keep_download_parts = True
    engine = VodEngine()
    task = VodDownloadTask(url='https://chzzk.naver.com/video/1', output_dir=str(tmp_path), max_retries=2)
    partial = tmp_path / '보관할 원본.mp4.part'
    partial.write_bytes(b'already downloaded')
    task.expected_part_file = str(partial)
    engine._tasks[task.task_id] = task
    downloader = AsyncMock(side_effect=OSError(error_number, 'output unavailable'))
    monkeypatch.setattr(engine, '_download_external', downloader)
    assert await asyncio.wait_for(engine._attempt_download(task.task_id), 1)
    assert not await asyncio.wait_for(engine._attempt_download(task.task_id), 1)
    assert task.state == VodDownloadState.ERROR and task.retry_count == 2
    assert task.error_message and downloader.await_count == 2
    assert partial.read_bytes() == b'already downloaded'
