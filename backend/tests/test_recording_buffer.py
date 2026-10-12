"""Disk buffer bounds, ownership, checksum and actual Streamlink handoff."""
from datetime import timedelta

import pytest

from app.engine.recording_buffer import BufferFull, MediaBuffer
from tests.test_chzzk_continuity import CDN, START, INITIALIZATION, MEDIA
from app.engine.chzzk_stream import ChzzkHLSStream
from streamlink import Streamlink


def metadata(index=0):
    return dict(at=(START + timedelta(seconds=index * 4)).isoformat(), duration=4,
                number=index, discontinuity=False, discontinuity_id=0, cdn='korean', mode='hls')


def test_checksum_rejects_changed_payload_and_keeps_unrelated_files(tmp_path):
    unrelated = tmp_path / '원본.ts'
    unrelated.write_bytes(b'original')
    buffer = MediaBuffer(tmp_path, 1, '1080p')
    row = buffer.store(metadata(), INITIALIZATION, MEDIA[0])
    assert buffer.load(row) == (INITIALIZATION, MEDIA[0])
    (tmp_path / (row['key'] + '.bin')).write_bytes(b'x' * row['size'])
    with pytest.raises(ValueError, match='Corrupt'):
        buffer.load(row)
    assert unrelated.read_bytes() == b'original'


@pytest.mark.parametrize('reason', ['already_output', 'time_limit', 'byte_limit', 'count_limit'])
def test_buffer_limits_are_distinct(tmp_path, reason):
    buffer = MediaBuffer(tmp_path, 1, '1080p', max_bytes=700, max_seconds=8)
    if reason == 'already_output':
        buffer.discard_before(START + timedelta(seconds=4))
    elif reason == 'time_limit':
        buffer.note_pending(START - timedelta(seconds=8))
    elif reason == 'byte_limit':
        buffer.used = 700
    else:
        buffer.rows = {str(i): dict(at=START.isoformat()) for i in range(2048)}
    assert buffer.rejection_reason(START, 4) == reason


def test_shutdown_fences_store_and_reopens_for_same_session(tmp_path):
    buffer = MediaBuffer(tmp_path, 1, '1080p')
    row = buffer.store(metadata(), INITIALIZATION, MEDIA[0])
    buffer.close()
    with pytest.raises(OSError, match='closed'):
        buffer.store(metadata(1), INITIALIZATION, MEDIA[1])
    reopened = MediaBuffer(tmp_path, 1, '1080p')
    assert reopened.load(row) == (INITIALIZATION, MEDIA[0])
    other = MediaBuffer(tmp_path, 2, '1080p')
    assert not other.entries()


def test_storage_failure_rolls_back_only_owned_temporary_files(tmp_path, monkeypatch):
    from pathlib import Path
    buffer = MediaBuffer(tmp_path, 1, '1080p')
    original = tmp_path / '녹화 원본.ts'
    original.write_bytes(b'original')
    def disk_full(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(Path, 'replace', disk_full)
    with pytest.raises(OSError, match='disk full'):
        buffer.store(metadata(), INITIALIZATION, MEDIA[0])
    assert buffer.used == 0 and not buffer.entries()
    assert list(tmp_path.iterdir()) == [original]


def test_metadata_never_contains_signed_urls_and_directory_traversal_rejected(tmp_path):
    buffer = MediaBuffer(tmp_path, 1, '1080p')
    row = buffer.store(metadata(), INITIALIZATION, MEDIA[0])
    raw = (tmp_path / (row['key'] + '.json')).read_text()
    assert 'http' not in raw and 'Cookie' not in raw
    row['key'] = '../outside'
    with pytest.raises(ValueError):
        buffer.load(row)


def test_recovery_uses_disk_when_missing_from_all_cdn_windows(tmp_path):
    buffer = MediaBuffer(tmp_path, 1, '1080p')
    buffer.store(metadata(1), INITIALIZATION, MEDIA[1])
    with CDN() as cdn:
        cdn.playlist('primary', indices=(0, 2, 3))
        session = Streamlink()
        session.set_option('stream-segment-threads', 2)
        stream = ChzzkHLSStream(session, cdn.url('primary'), 'same', live_id=1,
            source_paths=[(cdn.url('primary'), False)], buffer_dir=str(tmp_path),
            resume={'live_id': 1, 'rendition': '1080p', 'from': (START + timedelta(seconds=4)).isoformat()})
        stream.continuity.provider = lambda: (1, [(cdn.url('primary'), False)])
        reader = stream.open()
        try:
            result = bytearray()
            while data := reader.read(128 * 1024):
                result.extend(data)
        finally:
            reader.close()
            session.http.close()
        assert bytes(result) == INITIALIZATION + b''.join(MEDIA[1:])
        assert cdn.hits['/primary/1080p/1.m4v'] == 0
