import asyncio
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.engine import episode_sites as sites
from app.engine.episode_sites import EpisodeSiteError, parse_episode_url, load_catalog, extract_episode, _key_attributes
from app.engine.platform_media import media_platform, platform_ydl
from app.engine.vod import VodEngine, VodDownloadTask
from app.core.config import get_settings
from tests.test_new_platforms import local_hls

WORK='https://linkani.tv/ani/42/'
EP='https://linkani.tv/watch/42/a1/k1/'
MEDIA='https://aniplayer1.site/master.m3u8'
OHLI='https://www.ohli24.net/1/work.html'
OHLI_EP='https://www.ohli24.net/2/episode.html'
HASH='a'*32


@pytest.mark.parametrize('url,site,collection',[
    ('https://anilife1.tv/content/1?ref=x','anilife',True),
    ('https://anilife01.tv/content/1/ep-1','anilife',False),
    (WORK,'linkani',True),(EP,'linkani',False),(OHLI,'ohli24',True),
    ('https://www.ohli24.net/2/한글.html','ohli24',True)])
def test_urls(url,site,collection):
    route=parse_episode_url(url)
    assert route['site']==media_platform(url)==site and route['collection']==collection
    assert '?' not in route['url'] and route['url'].isascii()


@pytest.mark.parametrize('url',[
    'http://linkani.tv/ani/1','https://linkani.tv.evil/ani/1','https://u:p@linkani.tv/ani/1',
    'https://linkani.tv:444/ani/1','https://linkani.tv/ads/1','https://linkani.tv/ani/x',
    'https://linkani.tv/ani/1/%0a','https://www.ohli24.net/1/x.html/evil',
    'https://anilife01.tv/content/1/bad.episode','https://anilife01.tv/content/1/a\\b'])
def test_reject_bad_urls(url):
    with pytest.raises(EpisodeSiteError):parse_episode_url(url)


class FixtureClient:
    def __init__(self, routes):self.routes=routes;self.calls=[]
    def request(self,url,domains,**kwargs):
        sites.checked_url(url,domains,subdomains=kwargs.get('subdomains',False))
        self.calls.append((url,kwargs))
        value=self.routes[url]
        return value if isinstance(value,tuple) else (url,value)
    def json(self,url,domains,**kwargs):
        import json
        final,text=self.request(url,domains,**kwargs)
        return final,json.loads(text)


def link_fixture(media=MEDIA,player=None):
    body='<h1 class="detail-info-title">Fixture work</h1><a class="ep" href="/watch/42/a1/k1/">Episode 1</a>'
    episode=('<video id="linktv-video"><source src="'+media+'" type="application/x-mpegURL"></video>') if player is None else player
    return FixtureClient({WORK:body,EP:episode,MEDIA:'#EXTM3U\n#EXTINF:3,\nseg.ts\n#EXT-X-ENDLIST\n'})


def test_catalog_and_episode_identification():
    client=link_fixture()
    result=load_catalog(WORK,client)
    assert result['title']=='Fixture work' and len(result['episodes'])==1
    assert result['episodes'][0]['url']==EP
    item=extract_episode(EP,client)
    assert item['url']==MEDIA and item['http_headers']['Referer']==EP
    client.routes[WORK]=client.routes[WORK].replace('/watch/42/','/watch/43/')
    with pytest.raises(EpisodeSiteError,match='다른 작품'):load_catalog(WORK,client)


def test_partial_catalog_is_explicit_not_fabricated():
    client=link_fixture();client.routes[WORK]=client.routes[WORK].replace('/k1/','/k9/')
    result=load_catalog(WORK,client)
    assert result['incomplete'] and [r['id'] for r in result['episodes']]==['a1-k9']


def test_json_player_is_parsed_without_execution():
    import json
    player=dict(flag='play',id=42,sid=1,nid=1,encrypt=0,trysee=0,points=0,actual_url=MEDIA,url=MEDIA)
    player['from']='sub'
    client=link_fixture(player='<script>var player_aaaa='+json.dumps(player)+';</script>')
    assert extract_episode(EP,client)['url']==MEDIA
    player['points']=1
    client.routes[EP]='<script>var player_aaaa='+json.dumps(player)+';</script>'
    with pytest.raises(EpisodeSiteError,match='권한'):extract_episode(EP,client)
    client.routes[EP]='<script>var player_aaaa=(()=>{throw new Error()})();</script>'
    with pytest.raises(EpisodeSiteError,match='JSON'):extract_episode(EP,client)


def test_anilife_catalog_media_and_subtitle():
    import json
    work='https://anilife01.tv/content/1';ep=work+'/one'
    catalog={'item':{'id':1,'title':'Work','episodes':[{'key':'one','title':'One','number':1,'sourceType':'anilife','playbackUrl':'/api/playback/1/one'}]}}
    client=FixtureClient({ep:'page','https://anilife01.tv/api/anime/1':json.dumps(catalog),
        'https://anilife01.tv/api/playback/1/one':json.dumps({'videoUrl':MEDIA,'subtitleUrl':'https://aniplayer1.site/sub.vtt'}),
        MEDIA:'#EXTM3U\n#EXTINF:3,\nseg.ts\n#EXT-X-ENDLIST',
        'https://aniplayer1.site/sub.vtt':'WEBVTT\n\n00:00.000 --> 00:02.000\nSubtitle\n'})
    item=extract_episode(ep,client)
    assert item['subtitles']['ko'][0]['data'].startswith('WEBVTT')
    catalog['item']['episodes'][0]['playable']=False
    client.routes['https://anilife01.tv/api/anime/1']=json.dumps(catalog)
    with pytest.raises(EpisodeSiteError,match='재생 파일'):extract_episode(ep,client)


def test_ohli_normal_player_issuance_and_identity():
    import json
    player='https://michealcdn.com/video/'+HASH
    manifest='https://michealcdn.com/stream/master.m3u8'
    client=FixtureClient({OHLI:'<h2>Work</h2><div class="eps-item"><a href="/2/episode.html">1화</a></div>',
        OHLI_EP:'<h2>Episode</h2><ul class="page-breadcrumb"><li><a href="/">Home</a></li><li><a href="/ing">Category</a></li><li><span><a href="/1/work.html">Work</a></span></li></ul><iframe id="video" src="'+player+'"></iframe>',
        player:'<script src="/player/assets/scripts.php?v=1"></script>',
        'https://michealcdn.com/player/assets/scripts.php?v=1':'/player/index.php?data= &do=getVideo',
        'https://michealcdn.com/player/index.php?data='+HASH+'&do=getVideo':json.dumps({'hls':True,'securedLink':manifest}),
        manifest:'#EXTM3U\n#EXTINF:3,\nhttps://hol1ncloud2-nocdn.xyz/seg.ts\n#EXT-X-ENDLIST'})
    assert load_catalog(OHLI,client)['episodes'][0]['id']=='2'
    item=extract_episode(OHLI_EP,client)
    assert item['http_headers']['Referer']==player
    assert next(opts['form'] for url,opts in client.calls if 'form' in opts)=={'hash':HASH,'r':OHLI_EP}
    assert extract_episode(OHLI,client)['id']=='2'
    client.routes[OHLI]+='<div class="eps-item"><a href="/3/other.html">2화</a></div>'
    with pytest.raises(EpisodeSiteError,match='선택'):extract_episode(OHLI,client)


@pytest.mark.parametrize('line',[
    '#EXT-X-KEY:METHOD=NONE',
    '#EXT-X-KEY:METHOD=AES-128,URI="key.bin"',
    '#EXT-X-KEY:METHOD=AES-128,URI="key.bin",KEYFORMAT="identity",KEYFORMATVERSIONS="1",IV=0x'+'0'*32])
def test_plain_aes_identity_is_accepted(line):_key_attributes(line)


@pytest.mark.parametrize('attrs',[
    'METHOD=SAMPLE-AES,URI="key"','METHOD=AES-128,URI="key",KEYFORMAT="com.apple.streamingkeydelivery"',
    'METHOD=AES-128,URI="key",IV=0x1','METHOD=AES-128,URI="key",URI="other"',
    'METHOD=AES-128,URI=key','METHOD=NONE,URI="key"','METHOD=AES-128,URI="key",',
    'METHOD=AES-128,URI="key",UNKNOWN=x','METHOD=AES-128,URI="key",KEYFORMATVERSIONS="2"'])
def test_bad_or_protected_keys_are_rejected(attrs):
    with pytest.raises(EpisodeSiteError):_key_attributes('#EXT-X-KEY:'+attrs)


@pytest.mark.parametrize('body',[
    '#EXTM3U\n#EXTINF:3,\nseg.ts',
    '#EXTM3U\n#EXTINF:3,\nhttps://127.0.0.1/seg.ts\n#EXT-X-ENDLIST',
    '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="https://evil.example/key"\n#EXTINF:3,\nseg.ts\n#EXT-X-ENDLIST',
    '#EXTM3U\n#EXT-X-DATERANGE:ID="ad"\nseg.ts\n#EXT-X-ENDLIST',
    '#EXTM3U\n#EXTINF:3,\n/ads/seg.ts\n#EXT-X-ENDLIST'])
def test_manifest_boundaries(body):
    client=FixtureClient({MEDIA:body})
    with pytest.raises(EpisodeSiteError):sites.validate_hls(client,MEDIA,EP,sites.SITES['linkani']['media'])


def test_redirect_is_checked_before_next_request():
    calls=[]
    def handle(request):
        calls.append(str(request.url));return httpx.Response(302,headers={'location':'https://evil.example/stolen'})
    client=sites.SiteClient();client.http.close();client.http=httpx.Client(transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(EpisodeSiteError):client.request(WORK,('linkani.tv',))
        assert calls==[WORK]
    finally:client.close()


def test_unicode_referer_is_encoded():
    seen=[]
    def handle(request):
        seen.append(request.headers['referer']);return httpx.Response(200,text='ok')
    client=sites.SiteClient();client.http.close();client.http=httpx.Client(transport=httpx.MockTransport(handle))
    try:
        client.request('https://www.ohli24.net/1/한글.html',('www.ohli24.net',))
        assert '%ED' in seen[0] and seen[0].isascii()
    finally:client.close()


def test_catalog_api_errors_and_no_queue_mutation(monkeypatch):
    from app.api.vod import router
    app=FastAPI();app.include_router(router)
    monkeypatch.setattr(sites,'load_catalog',lambda url:load_catalog(url,link_fixture()))
    with TestClient(app) as client:
        response=client.post('/api/vod/catalog',json={'url':WORK})
        assert response.status_code==200 and response.json()['episodes'][0]['url']==EP
        assert client.post('/api/vod/catalog',json={'url':'https://evil.example/'}).status_code==400


@pytest.mark.asyncio
@pytest.mark.parametrize('encrypted',[False,True])
async def test_real_upstream_download_and_inspection(local_hls,monkeypatch,encrypted):
    base,directory=local_hls
    from app.engine import episode_extractor
    from app.engine.media_inspection import probe_media
    if encrypted:
        key=directory/'key.bin';key.write_bytes(bytes(range(16)))
        keyinfo=directory/'key-info.txt';keyinfo.write_text('key.bin\n'+str(key)+'\n')
        subprocess.run([shutil.which('ffmpeg'),'-v','error','-i',str(directory/'720/index.m3u8'),'-c','copy',
            '-hls_key_info_file',str(keyinfo),'-hls_time','1','-hls_list_size','0',str(directory/'encrypted.m3u8')],check=True)
        manifest=base+'/encrypted.m3u8'
    else:manifest=base+'/720/index.m3u8'
    import httpx
    text=httpx.get(manifest).text
    if encrypted:text=text.replace('#EXT-X-KEY:METHOD=AES-128,', '#EXT-X-KEY:KEYFORMAT="identity",KEYFORMATVERSIONS="1",METHOD=AES-128,')
    monkeypatch.setattr(episode_extractor,'extract_episode',lambda url,client=None:dict(id='one',title='Episode download',uploader='Linkani',
        webpage_url=EP,url=manifest,manifest=text,subtitles={'ko':[{'ext':'vtt','data':'WEBVTT\n\n00:00.000 --> 00:02.000\nSubtitle\n'}]},http_headers={},is_live=False))
    engine=VodEngine();info=await engine.get_video_info(EP)
    assert info['formats']
    out=directory/'saved';out.mkdir()
    task=VodDownloadTask(url=EP,prepared=True,quality='best',output_dir=str(out))
    engine._tasks[task.task_id]=task
    try:
        await engine._download_external(task.task_id,task)
        assert task.state.value=='completed' and task.inspection_state=='passed'
        assert probe_media(task.output_path)['streams']=={'video','audio'}
        assert list(out.glob('*.vtt'))
        assert engine.get_task_status(task.task_id)['platform']=='linkani'
    finally:await engine.shutdown()
