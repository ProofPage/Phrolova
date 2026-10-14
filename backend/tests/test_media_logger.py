import logging

import pytest
from yt_dlp.extractor.bunnycdn import BunnyCdnIE
from yt_dlp.utils import DownloadError

from app.engine.platform_media import platform_ydl


def test_optional_extractor_notices_do_not_count_as_warnings(caplog):
    caplog.set_level(logging.INFO, logger='media-notice-test')
    with platform_ydl('https://example.com/video', {
        'logger': logging.getLogger('media-notice-test'), 'no_warnings': True,
    }) as ydl:
        ydl.report_warning('[generic] Falling back on generic information extractor')
        ydl.report_warning('[BunnyCdn] unable to extract JSON-LD ; please report this issue on https://example.com/?token=SECRET')
    assert [record.levelno for record in caplog.records] == [logging.INFO, logging.INFO]
    assert '일반 추출기' in caplog.text and 'JSON-LD' in caplog.text
    assert 'SECRET' not in caplog.text


@pytest.mark.parametrize('message', [
    '[BunnyCdn] HTTP Error 403: Forbidden',
    '[BunnyCdn] unable to extract JSON-LD and media formats',
    '[OtherSite] unable to extract JSON-LD',
    '[download] fragment not found',
])
def test_other_extractor_warnings_keep_severity_and_redaction(message, caplog):
    caplog.set_level(logging.INFO, logger='media-warning-test')
    with platform_ydl('https://example.com/video', {
        'logger': logging.getLogger('media-warning-test'),
    }) as ydl:
        ydl.report_warning(message + ' https://example.com/?token=SECRET')
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert message in caplog.text and 'SECRET' not in caplog.text


def test_bunny_without_json_ld_still_extracts_media(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger='bunny-metadata-test')
    with platform_ydl('https://example.com/video', {
        'logger': logging.getLogger('bunny-metadata-test'), 'skip_download': True,
    }) as ydl:
        extractor = BunnyCdnIE(ydl)
        monkeypatch.setattr(extractor, '_download_webpage', lambda *args, **kwargs:
            '<video id="main-video" data-plyr-config=\'{"title":"Fixture"}\'>'
            '<source src="https://example.com/fixture.mp4" type="video/mp4"></video>')
        info = extractor._real_extract('https://iframe.mediadelivery.net/embed/1/12345678-1234-1234-1234-123456789012')
        assert info['title'] == 'Fixture'
        assert info['formats'][0]['url'] == 'https://example.com/fixture.mp4'
    assert any('JSON-LD' in record.message for record in caplog.records)
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


def test_real_extractor_failure_still_raises_and_logs_error(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger='bunny-failure-test')
    url = 'https://iframe.mediadelivery.net/embed/1/12345678-1234-1234-1234-123456789012'
    with platform_ydl(url, {'logger': logging.getLogger('bunny-failure-test')}) as ydl:
        extractor = BunnyCdnIE(ydl)
        monkeypatch.setattr(extractor, '_download_webpage', lambda *args, **kwargs: '<title>403</title>')
        ydl.add_info_extractor(extractor)
        with pytest.raises(DownloadError, match='inaccessible'):
            ydl.extract_info(url, download=False)
    assert any(record.levelno == logging.ERROR for record in caplog.records)
