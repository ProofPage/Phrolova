import base64
import json
import shutil
import subprocess
from urllib.parse import quote, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.logger import get_media_logger
from app.engine import episode_sites as sites
from app.engine.episode_sites import EpisodeSiteError, SiteClient, extract_episode, load_catalog, parse_episode_url
from app.engine.platform_media import canonical_platform_video, media_platform
from app.engine.vod_preparation import canonical_prepared_url
from tests.test_episode_sites import FixtureClient
from tests.test_new_platforms import local_hls

WORK = 'https://tvchak208.com/index.php/vod/detail/id/123703.html'
EPISODE = 'https://tvchak208.com/index.php/vod/play/id/123703/sid/1/nid/1.html'
SECOND = EPISODE.replace('nid/1.html', 'nid/2.html')
MEDIA = 'https://bodaponi.b-cdn.net/fixture.1080p.mp4'
PREFIX = b'\x00\x00\x00\x20ftypisom' + b'\x00'*20


def fixture_client(*, encoding=0, media=MEDIA):
    catalog = ('<h1>테스트 작품</h1><div id="playsx"><ul class="content_playlist">'
               '<li><a href="'+SECOND+'">제2화</a></li><li><a href="'+EPISODE+'">제1화</a></li>'
               '</ul></div><a href="https://ads.invalid/">ad</a>')
    value = quote(media, safe='') if encoding else media
    if encoding == 2:
        value = base64.b64encode(value.encode()).decode()
    player = dict(flag='play', id='123703', sid=1, nid=1, encrypt=encoding,
                  trysee=0, points=0, url=value, url_next='https://ads.invalid/not-this.mp4')
    player['from'] = 'mp4'
    page = catalog+'<script>var player_aaaa='+json.dumps(player)+';</script>'
    return FixtureClient({WORK:catalog, EPISODE:page, MEDIA:PREFIX}), player


@pytest.mark.parametrize('url,collection', [(WORK, True), (EPISODE, False), (SECOND, False)])
def test_routes_capabilities_and_log_scope(url, collection):
    from app.api.vod import VodPrepareRequest, vod_capabilities
    import asyncio
    route = parse_episode_url(url+'?ref=tracking#top')
    assert route['url']==url and route['collection']==collection
    assert media_platform(url)=='tvchak'
    assert 'tvchak' in get_media_logger(url).name
    assert VodPrepareRequest(urls=[url],source='tvchak').source=='tvchak'
    assert any(s['id']=='tvchak' for s in asyncio.run(vod_capabilities())['sources'])
    if not collection:
        assert canonical_platform_video(url)==canonical_prepared_url(url,'tvchak')==url
    else:
        with pytest.raises(ValueError,match='회차'): canonical_platform_video(url)


@pytest.mark.parametrize('url', [
    WORK.replace('https:', 'http:'), WORK.replace('.com/', '.com.evil/'),
    WORK.replace('tvchak208.com', 'u:p@tvchak208.com'), WORK.replace('.com/', '.com:444/'),
    WORK.replace('123703', '0'), WORK.replace('detail', 'type'), WORK+'/extra',
    EPISODE.replace('nid/1', 'nid/0'), EPISODE.replace('sid/1', 'sid/-1'),
    WORK.replace('.html', '%0a.html'), 'https://tvchak208.com/',
])
def test_invalid_addresses(url):
    with pytest.raises(EpisodeSiteError): parse_episode_url(url)


def test_catalog_uses_only_actual_work_links_and_selected_source():
    client, _ = fixture_client()
    catalog = load_catalog(WORK,client)
    assert catalog['title']=='테스트 작품'
    assert [r['url'] for r in catalog['episodes']]==[EPISODE,SECOND]
    assert [r['url'] for r in load_catalog(EPISODE,client)['episodes']]==[EPISODE]
    client.routes[WORK] = client.routes[WORK].replace('nid/2.html','nid/9.html').replace('제2화','제9화')
    assert [r['number'] for r in load_catalog(WORK,client)['episodes']]==[1,9]
    client.routes[WORK] = client.routes[WORK].replace('id/123703','id/123704')
    with pytest.raises(EpisodeSiteError,match='다른 작품'): load_catalog(WORK,client)


@pytest.mark.parametrize('encoding',[0,1,2])
def test_player_data_and_mp4_probe(encoding):
    client,_ = fixture_client(encoding=encoding)
    item = extract_episode(EPISODE,client)
    assert item['url']==MEDIA and item['ext']=='mp4' and 'manifest' not in item
    assert item['title']=='테스트 작품 · 제1화' and item['is_live'] is False
    assert item['http_headers']['Referer'].startswith('https://ckp2.wiselife.blog/chak/chaktt.php?url=')
    probe = client.calls[-1]
    assert probe[0]==MEDIA and probe[1]['prefix_bytes']==4096
    assert probe[1]['headers']=={'Range':'bytes=0-4095'}
    assert not any('ads.invalid' in url for url,_ in client.calls)


@pytest.mark.parametrize('field,value,message',[
    ('id','42','ID'),('sid',2,'ID'),('nid',2,'ID'),('flag','advertisement','ID'),
    ('trysee',1,'권한'),('points',1,'권한'),('trysee',False,'권한'),
    ('is_ad',True,'본편'),('from','unknown','본편'),('encrypt',False,'형식'),
    ('encrypt',3,'주소'),('url','https://127.0.0.1/a.mp4','HTTPS'),
    ('url','https://bodaponi.b-cdn.net.evil/a.mp4','HTTPS'),
    ('url','https://u:p@bodaponi.b-cdn.net/a.mp4','HTTPS'),
    ('url','https://bodaponi.b-cdn.net/ads/a.mp4','HTTPS'),
])
def test_reject_changed_player_identity_and_non_media(field,value,message):
    client,player = fixture_client();player[field]=value
    client.routes[EPISODE]=client.routes[WORK]+'<script>player_aaaa='+json.dumps(player)+';</script>'
    with pytest.raises(EpisodeSiteError,match=message): extract_episode(EPISODE,client)


def test_missing_episode_redirects_and_invalid_mp4():
    client,_=fixture_client()
    client.routes[EPISODE]=(SECOND,client.routes[EPISODE])
    with pytest.raises(EpisodeSiteError,match='ID'): extract_episode(EPISODE,client)
    client,_=fixture_client();client.routes[MEDIA]=b'<html>Login required</html>'
    with pytest.raises(EpisodeSiteError,match='MP4'): extract_episode(EPISODE,client)
    client,_=fixture_client();client.routes[EPISODE]=client.routes[EPISODE].replace('nid/1.html','nid/3.html')
    with pytest.raises(EpisodeSiteError,match='요청한 회차'): extract_episode(EPISODE,client)


def test_hls_branch_remains_native_and_validated():
    media=MEDIA.replace('.mp4','.m3u8')
    client,_=fixture_client(media=media)
    client.routes[media]='#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:3,\nsegment.ts\n#EXT-X-ENDLIST\n'
    item=extract_episode(EPISODE,client)
    assert item['manifest'].startswith('#EXTM3U') and item['url']==media
    client.routes[media]=client.routes[media].replace('segment.ts','https://evil.invalid/segment.ts')
    with pytest.raises(EpisodeSiteError): extract_episode(EPISODE,client)


def test_tvchak_cookie_registration_scope_removal_and_denied_live(monkeypatch,tmp_path):
    from app.api import platforms
    from app.engine.platform_auth import platform_cookie_jar
    monkeypatch.setattr(platforms,'_COOKIE_SAVE_PATH',tmp_path/'unused.txt')
    app=FastAPI();app.include_router(platforms.router)
    with TestClient(app) as client:
        path='/api/platforms/tvchak/cookie'
        assert client.get(path).status_code==200
        invalid=b'# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tother\tsecret\n'
        assert client.post(path,files={'file':('cookies.txt',invalid)}).status_code==400
        valid=b'# Netscape HTTP Cookie File\n.tvchak208.com\tTRUE\t/\tTRUE\t0\tsession\tfixture\n'
        response=client.post(path,files={'file':('cookies.txt',valid+invalid.split(b'\n',1)[1])})
        assert response.status_code==200 and response.json()['configured'] and response.json()['valid']
        assert 'fixture' not in response.text and 'secret' not in response.text
        assert {c.domain for c in platform_cookie_jar('tvchak')}=={'.tvchak208.com'}
        assert client.get('/api/platforms/tvchak/123/qualities').status_code==400
        assert client.delete(path).json()['configured'] is False
        assert not platform_cookie_jar('tvchak')


@pytest.mark.parametrize('headers,body',[
    ({'x-amzn-waf-action':'challenge'},b'<html>browser check</html>'),
    ({'x-amzn-waf-action':'captcha'},b''), ({},b''),
])
def test_access_checks_are_errors_not_empty_catalogs(headers,body):
    client=SiteClient();client.http.close()
    client.http=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(202,headers=headers,content=body)))
    try:
        with pytest.raises(EpisodeSiteError,match='접속 확인') as error:
            client.request(WORK,sites.SITES['tvchak']['hosts'])
        assert error.value.status==202
    finally: client.close()


def test_cookie_domains_and_probe_bounds(monkeypatch,tmp_path):
    file=tmp_path/'tvchak.txt'
    file.write_text('# Netscape HTTP Cookie File\n.tvchak208.com\tTRUE\t/\tTRUE\t0\tsession\tfixture\n')
    monkeypatch.setattr(get_settings(),'tvchak_cookie_file',str(file))
    received=[]
    def handle(req):
        received.append((req.url.host,req.headers.get('cookie')))
        return httpx.Response(200,content=PREFIX+b'x'*100000)
    client=SiteClient();client.http.close();client.http=httpx.Client(transport=httpx.MockTransport(handle))
    try:
        client.request(WORK,sites.SITES['tvchak']['hosts'])
        _,data=client.request(MEDIA,sites.SITES['tvchak']['media'],binary=True,prefix_bytes=4096)
        assert len(data)==4096 and received==[('tvchak208.com','session=fixture'),('bodaponi.b-cdn.net',None)]
        with pytest.raises(ValueError): client.request(MEDIA,sites.SITES['tvchak']['media'],prefix_bytes=4096)
        with pytest.raises(ValueError): client.request(MEDIA,sites.SITES['tvchak']['media'],binary=True,prefix_bytes=1000000)
    finally: client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[202,401,403])
async def test_access_denial_does_not_repeat_downloads(monkeypatch,status):
    from unittest.mock import AsyncMock
    from app.engine.vod import VodEngine, VodDownloadTask, NonRetryableDownloadError
    engine=VodEngine()
    operation=AsyncMock(side_effect=RuntimeError(f'사이트 접속 확인이 필요합니다. (HTTP {status})'))
    monkeypatch.setattr(engine,'_download_with_ytdlp',operation)
    task=VodDownloadTask(url=EPISODE)
    try:
        with pytest.raises(NonRetryableDownloadError,match='접속 확인'):
            await engine._download_external(task.task_id,task)
        assert operation.await_count==1
    finally: await engine.shutdown()


@pytest.mark.asyncio
async def test_actual_direct_mp4_queue_download_and_inspection(local_hls,monkeypatch):
    from app.engine import episode_extractor
    from app.engine.media_inspection import probe_media
    from app.engine.vod import VodEngine, VodDownloadTask
    base,directory=local_hls
    mp4=directory/'direct.mp4'
    subprocess.run([shutil.which('ffmpeg'),'-v','error','-i',str(directory/'720/index.m3u8'),
                    '-c','copy','-movflags','+faststart',str(mp4)],check=True)
    original=episode_extractor.extract_episode
    def extract(url,client):
        item=original(url,fixture_client()[0])
        item['url']=base+'/direct.mp4';item['http_headers']={}
        return item
    monkeypatch.setattr(episode_extractor,'extract_episode',extract)
    engine=VodEngine()
    try:
        info=await engine.get_video_info(EPISODE)
        assert info['formats']
        output=directory/'saved';output.mkdir()
        task=VodDownloadTask(url=EPISODE,prepared=True,quality='1080p',output_dir=str(output))
        engine._tasks[task.task_id]=task
        await engine._prepare_metadata(task)
        assert task.phase=='ready' and task.quality=='best'
        await engine._download_external(task.task_id,task)
        assert task.state.value=='completed' and task.inspection_state=='passed'
        assert probe_media(task.output_path)['streams']=={'video','audio'}
        assert engine.get_task_status(task.task_id)['platform']=='tvchak'
    finally: await engine.shutdown()
