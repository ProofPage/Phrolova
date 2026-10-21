import pytest

from app.engine.missav import main_playlist, parse_missav_url
from app.engine.episode_sites import EpisodeSiteError

MEDIA = 'https://surrit.com/00000000-0000-4000-8000-000000000001/playlist.m3u8'


@pytest.mark.parametrize('url', [
    'https://missav123.com/dm270/ko', 'https://missav123.com/ko',
    'https://missav123.com/en/sample', 'https://missav.live/ko/sample',
    'https://missav123.com.evil/ko/sample', 'http://missav123.com/ko/sample',
    'https://user:password@missav123.com/ko/sample',
    'https://127.0.0.1/ko/sample', 'https://missav123.com:444/ko/sample',
    'https://missav123.com/ko/%2fprivate',
])
def test_reject_unverified_urls(url):
    with pytest.raises(EpisodeSiteError):
        parse_missav_url(url)


def test_single_video_url():
    route = parse_missav_url('https://www.missav123.com/ko/neutral-sample/?tracking=1')
    assert route['url'] == 'https://missav123.com/ko/neutral-sample'
    assert route['site'] == 'missav' and not route['collection']


def packed(source):
    # Neutral Dean Edwards dictionary-substitution fixture, no JS execution.
    return ("<script>eval(function(p,a,c,k,e,d){return p;}("
            f"'0=\\'{source}\\';',2,1,'source'.split('|'),0,{{}}))</script>")


def test_packed_main_not_preview_or_ad():
    html = (f'<video src="https://ads.invalid/preview.mp4"></video>'
            + packed(MEDIA))
    assert main_playlist(html) == MEDIA


@pytest.mark.parametrize('url', [
    MEDIA.replace('surrit.com', 'surrit.com.evil'),
    MEDIA.replace('surrit.com', '127.0.0.1'),
    MEDIA.replace('surrit.com', 'user:password@surrit.com'),
    MEDIA.replace('/playlist.m3u8', '/preview.m3u8'),
])
def test_untrusted_main(url):
    with pytest.raises(EpisodeSiteError):
        main_playlist(packed(url))


def test_ambiguous_or_missing_main():
    for html in ('<video src="https://ads.invalid/ad.mp4"></video>',
                 packed(MEDIA) + packed(MEDIA.replace('000000000001', '000000000002'))):
        with pytest.raises(EpisodeSiteError):
            main_playlist(html)


@pytest.mark.asyncio
async def test_queue_three_instances(monkeypatch, tmp_path):
    import asyncio
    import json
    from pathlib import Path
    from unittest.mock import Mock, AsyncMock
    from app.engine.vod import VodEngine, VodDownloadState
    from app.engine.platform_media import platform_ydl
    from app.core.config import get_settings
    from app.api.vod import VodPrepareRequest, vod_capabilities
    from app.engine import missav
    assert VodPrepareRequest(urls=['https://missav123.com/ko/Neutral'], source='missav').source == 'missav'
    assert {'id': 'missav', 'label': 'MissAV'} in (await vod_capabilities())['sources']
    instances, deliveries = [], []
    plain = (b'\x47' + b'\0'*187)*4
    def extract(route, client):
        identity = f'00000000-0000-4000-8000-{len(deliveries)+1:012d}'
        master = f'https://surrit.com/{identity}/playlist.m3u8'
        variants = [f'https://surrit.com/{identity}/{q}p/video.m3u8' for q in (360, 720)]
        playlists = {master: '#EXTM3U\n' + ''.join(
            f'#EXT-X-STREAM-INF:BANDWIDTH={q*1000},RESOLUTION={640 if q==360 else 1280}x{q}\n{v}\n'
            for q,v in zip((360,720),variants))}
        resources = {master:'master'}
        for v in variants:
            segment = v.replace('video.m3u8','video0.jpeg')
            resources.update({v:'variant', segment:'segment'})
            playlists[v] = f'#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\n{segment}\n#EXT-X-ENDLIST\n'
        delivery = dict(identity=identity, resources=resources, playlists=playlists, referer=route['url'])
        deliveries.append(delivery)
        return dict(id='Neutral',title='Neutral',url=master,manifest=playlists[master],
                    subtitles={},http_headers={},_missav_delivery=delivery)
    def factory(url, opts):
        ydl = platform_ydl(url, opts)
        instances.append(ydl)
        return ydl
    class Client:
        def request(self, address, domains, **kwargs):
            kwargs['validator'](address)
            assert instances[-1]._missav_delivery is deliveries[-1]
            assert address.endswith('/360p/video0.jpeg')
            return address, plain
        def close(self): pass
    monkeypatch.setattr(missav, 'extract_missav_episode', extract)
    monkeypatch.setattr('app.engine.vod.platform_ydl', factory)
    monkeypatch.setattr('app.engine.missav_downloader.SiteClient', Client)
    engine = VodEngine()
    monkeypatch.setattr(get_settings(), 'vod_download_dir', str(tmp_path))
    monkeypatch.setattr(engine, '_build_ytdlp_options', lambda task, **kw: {
        'quiet':True,'fixup':'never','format':'best[height<=360]',
        'outtmpl':str(tmp_path/'neutral.%(ext)s')})
    monkeypatch.setattr(engine, '_inspect_chzzk_download', AsyncMock())
    monkeypatch.setattr(engine, '_notify', Mock())
    result = engine.prepare_vods(['https://missav123.com/ko/Neutral'],source='missav')
    await asyncio.gather(*engine._metadata_tasks)
    task = engine._tasks[result['results'][0]['task_id']]
    assert task.metadata['qualities'] == [{'value':'720p','label':'720p'},{'value':'360p','label':'360p'}]
    engine.set_prepared_quality(task.task_id,'360p')
    engine.start_prepared(task.task_id)
    await task.download_task
    assert task.state == VodDownloadState.COMPLETED, task.error_message
    assert Path(task.output_path).read_bytes() == plain
    assert len(instances) == len(deliveries) == 3
    assert len({id(x) for x in instances}) == 3
    assert 'surrit.com' not in json.dumps(engine.get_task_status(task.task_id))


@pytest.mark.parametrize('target', ['https://127.0.0.1/private','https://surrit.com.evil/private',
                                  'https://user:pass@surrit.com/private'])
def test_transport_redirect_rejected(target):
    import httpx
    from yt_dlp.networking import Request
    from yt_dlp.utils import ExtractorError
    from app.engine.episode_sites import SiteClient
    from app.engine.missav_downloader import MissAVYoutubeDL
    from unittest.mock import patch
    identity = '00000000-0000-4000-8000-000000000001'
    segment = MEDIA.replace('playlist.m3u8','720p/video0.jpeg')
    calls = []
    client = SiteClient()
    client.http.close()
    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(302,headers={'location':target})
    client.http = httpx.Client(transport=httpx.MockTransport(respond))
    with patch('app.engine.missav_downloader.SiteClient',return_value=client):
        with MissAVYoutubeDL({'quiet':True}) as ydl:
            ydl.configure_missav(dict(identity=identity,resources={segment:'segment'},playlists={},referer='https://missav123.com/ko/neutral'))
            with pytest.raises(ExtractorError):
                ydl.urlopen(Request(segment))
    assert calls == [segment]


@pytest.mark.parametrize('status,headers', [(403,{'cf-mitigated':'challenge'}),(429,{})])
def test_request_failure_no_retry(status,headers):
    import httpx
    from app.engine.episode_sites import SiteClient, extract_episode
    calls = []
    client = SiteClient()
    client.http.close()
    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(status,headers=headers)
    client.http = httpx.Client(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(EpisodeSiteError,match=str(status)):
            extract_episode('https://missav123.com/ko/neutral',client)
    finally: client.close()
    assert len(calls) == 1


def test_observed_manifest_protocol_and_named_source_only():
    from unittest.mock import Mock
    from app.engine.missav import extract_missav_episode
    page = 'https://missav123.com/ko/neutral'
    variant = MEDIA.replace('playlist.m3u8','720p/video.m3u8')
    client = Mock()
    client.request.side_effect = [
        (page,'<title>Neutral</title><video src="https://ads.invalid/a.m3u8"></video>'+packed(MEDIA)),
        (MEDIA,'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=1280x720\n720p/video.m3u8\n'),
        (variant,'#EXTM3U\n#EXTINF:4,\nvideo0.jpeg\n#EXT-X-ENDLIST\n')]
    item = extract_missav_episode(parse_missav_url(page),client)
    assert item['url'] == MEDIA
    assert item['_missav_delivery']['resources'][variant.replace('video.m3u8','video0.jpeg')] == 'segment'
    assert client.request.call_count == 3


@pytest.mark.parametrize('line',[
    'https://127.0.0.1/private', '../other/video0.jpeg',
    'https://surrit.com/00000000-0000-4000-8000-000000000002/720p/video0.jpeg',
    '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key"',
    '#EXT-X-KEY:METHOD=AES-128,URI="https://127.0.0.1/key"',
    '#EXT-X-DATERANGE:ID="ad"',
])
def test_manifest_rejects_foreign_resources_and_protection(line):
    from unittest.mock import Mock
    from app.engine.missav import extract_missav_episode
    page = 'https://missav123.com/ko/neutral'
    variant = MEDIA.replace('playlist.m3u8','720p/video.m3u8')
    client=Mock()
    client.request.side_effect=[
        (page,'<title>Neutral</title>'+packed(MEDIA)),
        (MEDIA,'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\n720p/video.m3u8\n'),
        (variant,f'#EXTM3U\n{line}\n#EXTINF:4,\nvideo0.jpeg\n#EXT-X-ENDLIST\n')]
    with pytest.raises(EpisodeSiteError):
        extract_missav_episode(parse_missav_url(page),client)
    assert client.request.call_count == 3


@pytest.mark.asyncio
async def test_prepare_api(monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from unittest.mock import AsyncMock
    from app.api import vod
    from app.engine.vod import VodEngine
    engine=VodEngine()
    monkeypatch.setattr(engine,'_save_history',lambda:None)
    monkeypatch.setattr(engine,'get_video_info',AsyncMock(return_value=dict(
        id='Neutral',title='Neutral',formats=[dict(height=720,width=1280,vcodec='h264')])))
    monkeypatch.setattr(vod,'_preparation_service',lambda:engine)
    app=FastAPI()
    app.include_router(vod.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/api/vod/prepare',json=dict(source='missav',urls=[
            'https://missav123.com/ko/Neutral','https://www.missav123.com/ko/Neutral?tracking=1',
            'https://missav123.com/dm270/ko']))
        assert response.status_code == 200
        rows=response.json()['results']
        assert rows[1]['duplicate'] and 'error' in rows[2]
        await asyncio.gather(*engine._metadata_tasks)
        task=engine._tasks[rows[0]['task_id']]
        assert task.phase=='ready' and task.quality=='720p'
        assert (await client.get('/api/vod/capabilities')).json()['sources'][-1]['id']=='external'


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[403,429])
async def test_queue_access_failure_stops_without_auto_retry(monkeypatch,status):
    import asyncio
    from unittest.mock import AsyncMock
    from app.engine.vod import VodEngine, VodDownloadState
    engine=VodEngine()
    monkeypatch.setattr(engine,'_save_history',lambda:None)
    monkeypatch.setattr(engine,'_cleanup_partial_files',AsyncMock(return_value=True))
    monkeypatch.setattr(engine,'get_video_info',AsyncMock(return_value=dict(
        title='Neutral',formats=[dict(height=720,width=1280,vcodec='h264')])))
    transfer=AsyncMock(side_effect=ValueError(f'MissAV 사이트 접근을 확인하세요. (HTTP {status})'))
    monkeypatch.setattr(engine,'_download_external',transfer)
    result=engine.prepare_vods(['https://missav123.com/ko/neutral'],source='missav')
    await asyncio.gather(*engine._metadata_tasks)
    task=engine._tasks[result['results'][0]['task_id']]
    engine.start_prepared(task.task_id)
    await task.download_task
    assert task.state==VodDownloadState.ERROR
    assert str(status) in task.error_message
    assert transfer.await_count==1 and task.retry_count==0


@pytest.mark.parametrize('prefix',[b'<html>Challenge</html>',b'\0'*8+(b'\x47'+b'\0'*187)*4])
def test_segment_body_not_stripped_or_accepted_as_html(monkeypatch,prefix):
    from yt_dlp.networking import Request
    from yt_dlp.utils import ExtractorError
    from app.engine.missav_downloader import MissAVYoutubeDL
    segment=MEDIA.replace('playlist.m3u8','720p/video0.jpeg')
    class Client:
        def request(self,address,domains,**kwargs):
            kwargs['validator'](address)
            return address,prefix
        def close(self): pass
    monkeypatch.setattr('app.engine.missav_downloader.SiteClient',Client)
    with MissAVYoutubeDL({'quiet':True}) as ydl:
        ydl.configure_missav(dict(identity='00000000-0000-4000-8000-000000000001',
                                 resources={segment:'segment'},playlists={},referer='https://missav123.com/ko/neutral'))
        with pytest.raises(ExtractorError,match='MPEG-TS'):
            ydl.urlopen(Request(segment))


def test_parse_missav_url_allows_ads_slug_without_generic_ad_path_rejection():
    from app.engine.missav import parse_missav_url
    url = 'https://missav123.com/ko/ads/'
    parsed = parse_missav_url(url)
    assert parsed['url'] == 'https://missav123.com/ko/ads'
    assert parsed['episode'] == 'ads'
