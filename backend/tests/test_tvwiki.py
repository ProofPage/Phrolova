import asyncio
import base64
from html import escape
import json

from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad
import httpx
import pytest

from app.api.vod import vod_capabilities, VodPrepareRequest
from app.engine.episode_sites import EpisodeSiteError, SiteClient, checked_url, load_catalog, parse_episode_url, extract_episode
from app.engine.tvwiki import CATEGORIES
from app.engine.platform_media import canonical_platform_video, media_platform
from app.engine.vod_preparation import canonical_prepared_url
from tests.test_episode_sites import FixtureClient

WORK = 'https://tvwiki54.net/drama/42'
EPISODE = WORK + '/11'
PLAYER = 'https://player.bunny-frame.online/v/fixture?t=123&sig=signature'
MEDIA = 'https://every9.poorcdn.com/v/fixture/index.m3u8'


def fixture_client(media=MEDIA, *, native=False, register_host='every9.poorcdn.com'):
    material, wrap_key, iv = bytes(range(32)), b'w'*16, b'i'*16
    config = dict(wrappedKey=AES.new(wrap_key,AES.MODE_CBC,iv).encrypt(pad(material,16)).hex(),
        wrapNonce='nonce',wrapSession='session',wrapIssuedAt=123,wrapSignature='signature',
        urlPayload=AES.new(material[:16],AES.MODE_CBC,material[16:]).encrypt(pad(media.encode(),16)).hex())
    native_url=media.replace('index.m3u8','native.m3u8')
    if native:
        config['directPayload']=AES.new(material[:16],AES.MODE_CBC,material[16:]).encrypt(pad(native_url.encode(),16)).hex()
    script = 'const ART_CONFIG = {\n' + ''.join(f'{key}: {json.dumps(value)},\n' for key,value in config.items()) + '\n};'
    if native:
        for key,value in dict(CAST_CONTENT_ID='content-id',CAST_AUTH_TOKEN='native-session',CAST_TIMESTAMP=123,CAST_REGISTER_URL=register_host).items():
            script+=f'\nwindow.{key} = {json.dumps(value)};'
    key_part, shared = b'a'*16, b'b'*16
    key = bytes(a^b for a,b in zip(key_part,shared))
    block = base64.b64encode(AES.new(key,AES.MODE_CBC,iv).encrypt(pad(script.encode(),16))).decode()
    player = ('<script>window._fixture={k:"'+key_part.hex()+'",t:"'+'f'*32+'",b:[]};'
              '_fixture.b.push({c:"'+block+'",v:"'+iv.hex()+'"});</script>')
    page = '<title>테스트 작품 다시보기 - 티비위키</title>'
    page += '<a class="title ep-link" href="/drama/42/12">테스트 작품 2화</a>'
    page += '<a class="img ep-link" href="/drama/42/11"></a>'
    page += '<a class="title ep-link" href="/drama/42/11">테스트 작품 1화</a>'
    page += '<script>totalEpisodes: 2,</script>'
    frame = '<iframe id="view_iframe" data-session1="'+escape(json.dumps({'idx':'11','s':'guest'}),quote=True)+'"></iframe>'
    client = FixtureClient({WORK:page, EPISODE:page+frame,
        'https://tvwiki54.net/api/create_session.php':json.dumps({'success':True,'player_url':PLAYER.split('?')[0],'t':123,'sig':'signature'}),
        PLAYER:player,
        'https://player.bunny-frame.online/api/key-share.php':json.dumps({'ok':True,'k2':shared.hex()}),
        'https://player.bunny-frame.online/wrap_key.php':json.dumps({'a':wrap_key[:8].hex(),'b':wrap_key[8:].hex(),'c':iv[:8].hex(),'d':iv[8:].hex()}),
        media:'#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:3,\nsegment.ts\n#EXT-X-ENDLIST\n'})
    if native:
        client.routes[native_url]=client.routes[media].replace('#EXTINF:3,','#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n#EXTINF:3,')
        client.routes['https://every9.poorcdn.com/v/cast-register']=json.dumps({'ok':True})
        client.routes['https://every9.poorcdn.com/v/fixture/key.bin']=bytes(range(16))
    return client


@pytest.mark.parametrize('category', CATEGORIES)
def test_tvwiki_routes_and_platform(category):
    for suffix,collection in [('',True),('/11',False)]:
        url=f'https://tvwiki54.net/{category}/42'+suffix
        result=parse_episode_url(url+'/?utm=test#fragment')
        assert result['url']==url and result['collection']==collection
        assert result['site']==media_platform(url)=='tvwiki'
        if not collection:
            assert canonical_platform_video(url)==canonical_prepared_url(url,'tvwiki')==url


@pytest.mark.parametrize('url', ['https://tvwiki54.net/', 'http://tvwiki54.net/drama/42/11',
    'https://tvwiki54.net.evil/drama/42/11','https://evil.tvwiki54.net/drama/42/11',
    'https://u:p@tvwiki54.net/drama/42/11','https://tvwiki54.net:444/drama/42/11',
    'https://tvwiki54.net/notice/42/11','https://tvwiki54.net/drama/42/11/extra',
    'https://tvwiki54.net/drama/42/%0a','https://tvwiki54.net/drama/42/0'])
def test_tvwiki_rejects_invalid_routes(url):
    with pytest.raises(EpisodeSiteError):parse_episode_url(url)


def test_catalog_selection_and_guest_player_flow():
    client=fixture_client()
    catalog=load_catalog(WORK,client)
    assert catalog['source']=='tvwiki' and catalog['title']=='테스트 작품'
    assert [row['id'] for row in catalog['episodes']]==['11','12']
    assert load_catalog(EPISODE,client)['episodes']==catalog['episodes'][:1]
    item=extract_episode(EPISODE,client)
    assert item['url']==MEDIA and item['title']=='테스트 작품 1화'
    assert item['manifest'].startswith('#EXTM3U') and item['uploader']=='티비위키'
    session=next(kwargs for url,kwargs in client.calls if url.endswith('/create_session.php'))
    assert session['json_body']=={'idx':'11','s':'guest'}
    assert session['headers']=={'Origin':'https://tvwiki54.net'}
    assert item['http_headers']['Referer']==PLAYER
    assert not any(kwargs.get('json_body') for url,kwargs in client.calls if url==MEDIA)


def test_missing_episode_or_wrong_identity_cannot_select_another_video():
    client=fixture_client()
    with pytest.raises(EpisodeSiteError,match='회차.*선택'):extract_episode(WORK,client)
    client.routes[EPISODE]=client.routes[EPISODE].replace('&quot;11&quot;','&quot;12&quot;')
    with pytest.raises(EpisodeSiteError,match='식별'):extract_episode(EPISODE,client)
    assert not any(url.endswith('/create_session.php') for url,_ in client.calls)


@pytest.mark.parametrize('player', ['https://evil.example/v/fixture','https://player.bunny-frame.online.evil/v/fixture',
    'http://player.bunny-frame.online/v/fixture','https://player.bunny-frame.online/ads/fixture'])
def test_session_cannot_redirect_to_unverified_player(player):
    client=fixture_client()
    client.routes['https://tvwiki54.net/api/create_session.php']=json.dumps({'success':True,'player_url':player,'t':123,'sig':'signature'})
    with pytest.raises(EpisodeSiteError):extract_episode(EPISODE,client)
    assert not any(url.startswith(player) for url,_ in client.calls)


def test_media_host_and_protected_manifest_are_validated():
    client=fixture_client(media='https://every9.poorcdn.com.evil/v/index.m3u8')
    with pytest.raises(EpisodeSiteError,match='주소'):extract_episode(EPISODE,client)
    client=fixture_client();client.routes[MEDIA]=client.routes[MEDIA].replace('#EXTINF:3,','#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key"\n#EXTINF:3,')
    with pytest.raises(EpisodeSiteError,match='보호'):extract_episode(EPISODE,client)


def test_json_guest_request_and_denied_response():
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json={'success':True}) if len(requests)==1 else httpx.Response(403,text='Access denied')
    client=SiteClient();client.http.close();client.http=httpx.Client(transport=httpx.MockTransport(handler))
    try:
        client.json('https://tvwiki54.net/api/create_session.php',('tvwiki54.net',),json_body={'idx':'11'})
        assert requests[0].method=='POST' and json.loads(requests[0].content)=={'idx':'11'}
        assert requests[0].headers['content-type']=='application/json'
        with pytest.raises(EpisodeSiteError,match='HTTP 403'):
            client.request(PLAYER,('player.bunny-frame.online',))
        assert len(requests)==2
    finally:client.close()


def test_capabilities_and_prepare_schema_include_tvwiki():
    sources=asyncio.run(vod_capabilities())['sources']
    assert {'id':'tvwiki','label':'platform.tvwiki'} in sources
    assert VodPrepareRequest(urls=[EPISODE],source='tvwiki').source=='tvwiki'


def test_native_player_rendition_and_normal_session_are_used():
    client=fixture_client(native=True)
    item=extract_episode(EPISODE,client)
    assert item['url']==MEDIA.replace('index.m3u8','native.m3u8')
    assert item['duration']==3
    registration=next(kwargs for url,kwargs in client.calls if url.endswith('/cast-register'))
    assert registration['json_body']=={'c':'content-id','auth':'native-session','t':123}
    assert registration['headers']=={'Origin':'https://player.bunny-frame.online'}
    assert not any(url==MEDIA for url,_ in client.calls)
    key_options=next(kwargs for url,kwargs in client.calls if url.endswith('/key.bin'))
    assert key_options['binary'] is True


def test_native_session_cannot_send_its_token_to_another_host():
    client=fixture_client(native=True,register_host='untrusted.example')
    with pytest.raises(EpisodeSiteError,match='호스트'):extract_episode(EPISODE,client)
    assert not any(url.endswith('/cast-register') for url,_ in client.calls)


def test_browser_specific_key_response_is_not_misreported_as_a_downloadable_video():
    client=fixture_client(native=True)
    client.routes['https://every9.poorcdn.com/v/fixture/key.bin']=b'{"browser-only-key":"unsupported"}'
    with pytest.raises(EpisodeSiteError,match='표준 HLS 키'):extract_episode(EPISODE,client)


def test_cdn_fallback_is_limited_to_advertised_resources_and_keeps_headers_scoped(monkeypatch):
    import io
    import yt_dlp
    from yt_dlp.networking import Request, Response
    from yt_dlp.networking.exceptions import HTTPError
    from app.engine.tvwiki_downloader import TVWikiYoutubeDL
    resource='https://c9.cedarshore437.site/v/fixture/segment.ts?signature=fixture'
    origin='https://every9.poorcdn.com'
    calls=[]
    def urlopen(ydl,request):
        calls.append(request)
        if request.url.startswith(origin):return Response(io.BytesIO(b'video'),request.url,{},status=200)
        raise HTTPError(Response(io.BytesIO(b'blocked'),request.url,{},status=403))
    monkeypatch.setattr(yt_dlp.YoutubeDL,'urlopen',urlopen)
    monkeypatch.setattr(yt_dlp.YoutubeDL,'process_ie_result',lambda self,info,*args,**kwargs:info)
    with TVWikiYoutubeDL({'quiet':True}) as ydl:
        info={'_tvwiki_delivery':{'origin':origin,'resources':[resource]}}
        ydl.process_ie_result(info)
        for _ in range(2):
            response=ydl.urlopen(Request(resource,headers={'Cookie':'private','Authorization':'private','Range':'bytes=0-99'}))
            assert response.read()==b'video';response.close()
        assert len(calls)==3
        assert calls[1].url==origin+'/v/fixture/segment.ts?signature=fixture'
        assert 'Cookie' not in calls[1].headers and 'Authorization' not in calls[1].headers
        assert calls[1].headers['Range']=='bytes=0-99'
        for request in [Request(resource.replace('segment.ts','unlisted.ts')),Request(resource,data=b'private')]:
            with pytest.raises(HTTPError):ydl.urlopen(request)
        assert len(calls)==5


@pytest.mark.parametrize('delivery',[
    {'origin':'http://every9.poorcdn.com','resources':[]},
    {'origin':'https://every9.poorcdn.com.evil','resources':[]},
    {'origin':'https://every9.poorcdn.com','resources':['https://127.0.0.1/private']},
    {'origin':'https://every9.poorcdn.com/v/other','resources':[]},
])
def test_untrusted_origin_delivery_context_is_rejected(delivery):
    from app.engine.tvwiki_downloader import TVWikiYoutubeDL
    with TVWikiYoutubeDL({'quiet':True}) as ydl:
        with pytest.raises(ValueError):ydl.process_ie_result({'_tvwiki_delivery':delivery})
