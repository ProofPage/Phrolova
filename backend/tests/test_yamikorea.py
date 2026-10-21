from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.engine.episode_sites import EpisodeSiteError, SiteClient, extract_episode, load_catalog
from app.engine.platform_media import canonical_platform_video, media_platform, platform_ydl
from app.engine.vod_preparation import canonical_prepared_url

PAGE = 'https://ym-05.com/videos/neutral-sample/'
MEDIA = 'https://media.ym-05.com/data/file/videos/sample.mp4'
PREFIX = b'\x00\x00\x00\x20ftypisom' + b'\0' * 20


def fixture_client(body=None, prefix=PREFIX):
    client = Mock()
    client.request.side_effect = [(PAGE, body or (
        f'<meta property="og:title" content="Neutral sample"><video>'
        f'<source src="{MEDIA}" type="video/mp4"></video>'
        '<video src="https://ym-05.com/data/preroll/24.mov"></video>'
        '<video src="https://media.ym-05.com/data/file/videos/thumb/sample.preview.mp4"></video>'
        '<track src="https://media.ym-05.com/data/file/videos/thumb/sample.vtt">')),
        (MEDIA, prefix)]
    return client


def test_native_main_media_only():
    client = fixture_client()
    item = extract_episode(PAGE, client)
    assert item['url'] == MEDIA and item['title'] == 'Neutral sample'
    assert item['ext'] == 'mp4' and item['subtitles'] == {}
    assert 'duration' not in item and 'height' not in item
    assert client.request.call_args.kwargs['prefix_bytes'] == 32
    assert client.request.call_args.kwargs['headers'] == {'Range': 'bytes=0-31'}


def test_ad_first_preview_then_main():
    body = ('<title>Neutral main title</title>'
            '<video src="https://ym-05.com/data/preroll/24.mov"></video>'
            '<video src="https://media.ym-05.com/data/file/videos/thumb/sample.preview.mp4"></video>'
            f'<video><source src="{MEDIA}" type="video/mp4"></video>'
            '<track src="https://media.ym-05.com/data/file/videos/thumb/sample.vtt">')
    item = extract_episode(PAGE, fixture_client(body))
    assert item['url'] == MEDIA and item['title'] == 'Neutral main title'
    assert item['subtitles'] == {} and 'duration' not in item


@pytest.mark.parametrize('body', [
    '<title>Neutral</title><video src="https://ym-05.com/data/preroll/24.mov"></video>',
    '<title>Neutral</title><video src="https://media.ym-05.com/data/file/videos/thumb/sample.preview.mp4"></video>',
    '{"title":"Neutral","source":"https://media.ym-05.com/data/file/videos/sample.mp4"}',
    '<title>Neutral</title>',
])
def test_no_main_video_fails_actionably(body):
    client = fixture_client(body)
    with pytest.raises(EpisodeSiteError, match='본편'):
        extract_episode(PAGE, client)
    assert client.request.call_count == 1


@pytest.mark.parametrize('target', [
    'https://127.0.0.1/private',
    'https://media.ym-05.com.evil/data/file/videos/sample.mp4',
    'https://user:secret@media.ym-05.com/data/file/videos/sample.mp4',
])
def test_redirect_validation_before_request(target):
    requests = []
    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={'location': target})
    client = SiteClient()
    client.http.close()
    client.http = httpx.Client(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(EpisodeSiteError):
            client.request(MEDIA, ('media.ym-05.com',), binary=True, prefix_bytes=32)
        assert requests == [MEDIA]
    finally:
        client.close()


@pytest.mark.parametrize('url', [
    'http://ym-05.com/videos/test/', 'https://ym-06.com/videos/test/',
    'https://ym-05.com.evil/videos/test/', 'https://127.0.0.1/videos/test/',
    'https://user:secret@ym-05.com/videos/test/', 'https://ym-05.com:444/videos/test/',
    'https://ym-05.com/videos/', 'https://ym-05.com/models/test/',
    'https://ym-05.com/videos/%2fprivate/', 'https://ym-05.com/videos/%252fprivate/',
    'https://ym-05.com/videos/../', 'https://ym-05.com/videos/test/extra/',
])
def test_invalid_urls(url):
    with pytest.raises(ValueError):
        canonical_prepared_url(url, 'yamikorea')


def test_routing_and_extractor():
    assert media_platform(PAGE) == 'yamikorea'
    assert canonical_platform_video(PAGE.replace('ym-05', 'www.ym-05') + '?tracking=1') == PAGE
    assert canonical_prepared_url(PAGE, 'auto') == PAGE
    with platform_ydl(PAGE, {'quiet': True}) as ydl:
        assert ydl._ies['EpisodeSite'].suitable(PAGE)
    with pytest.raises(EpisodeSiteError, match='개별'):
        load_catalog(PAGE, Mock())


@pytest.mark.parametrize('prefix', [b'', b'<html>Denied</html>', b'{"error":403}', b'not an mp4 response'])
def test_invalid_media_body(prefix):
    with pytest.raises(EpisodeSiteError, match='MP4'):
        extract_episode(PAGE, fixture_client(prefix=prefix))


@pytest.mark.parametrize('source', [
    'https://127.0.0.1/data/file/videos/sample.mp4',
    'https://user:pass@media.ym-05.com/data/file/videos/sample.mp4',
    'https://media.ym-05.com.evil/data/file/videos/sample.mp4',
    'https://media.ym-05.com/data/file/videos/thumb/sample.mp4',
])
def test_untrusted_sources_not_requested(source):
    client = fixture_client(f'<title>Neutral</title><video src="{source}"></video>')
    with pytest.raises(EpisodeSiteError):
        extract_episode(PAGE, client)
    assert client.request.call_count == 1


@pytest.mark.parametrize('status', [401, 403, 404, 429, 500])
def test_status_errors(status):
    client = SiteClient()
    client.http.close()
    client.http = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, content=b'{}')))
    try:
        with pytest.raises(EpisodeSiteError):
            extract_episode(PAGE, client)
    finally:
        client.close()


@pytest.mark.asyncio
async def test_queue_metadata_and_duplicate(monkeypatch):
    import asyncio
    from app.engine.vod import VodEngine
    engine = VodEngine()
    info = dict(id='neutral-sample', title='Neutral', duration=None,
                formats=[{'format_id': 'original', 'ext': 'mp4'}])
    monkeypatch.setattr(engine, 'get_video_info', AsyncMock(return_value=info))
    result = engine.prepare_vods([PAGE, PAGE + '?tracking=1'], source='yamikorea')
    await asyncio.gather(*engine._metadata_tasks)
    assert result['results'][1]['duplicate']
    task = engine._tasks[result['results'][0]['task_id']]
    assert task.phase == 'ready' and task.title == 'Neutral'
    assert task.download_task is None
