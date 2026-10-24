import asyncio
import base64
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad
import pytest

from app.api.vod import VodPrepareRequest, vod_capabilities
from app.core.logger import get_media_logger
from app.engine import ohli365
from app.engine.episode_extractor import EpisodeSiteIE
from app.engine.episode_sites import EpisodeSiteError, load_catalog, extract_episode, parse_episode_url
from app.engine.platform_media import media_platform, canonical_platform_video
from app.engine.vod_preparation import canonical_prepared_url
from tests.test_episode_sites import FixtureClient

WORK_ID = '11111111-1111-4111-8111-111111111111'
EP_ID = '22222222-2222-4222-8222-222222222222'
OTHER_ID = '33333333-3333-4333-8333-333333333333'
WORK = 'https://v2.ohli365.org/?title='+WORK_ID
EPISODE = WORK+'&episode='+EP_ID
API = 'https://v2.ohli365.org/api/home/playback'
PLAYER = 'https://megaplay.buzz/stream/ani/42/1/sub'
SOURCES = 'https://megaplay.buzz/stream/getSources?id=42&platform=OTHER'
PREFIX = '/anime/'+'a'*32+'/'+'b'*32+'/'
MEDIA = 'https://fetch.nexabloom.top'+PREFIX+'master.m3u8'
CHILD = MEDIA.replace('master.m3u8','index-f1.m3u8')
SUBTITLE = 'https://fixture.broforgotsave.online'+PREFIX+'subtitles/track_0_eng.vtt'


def page(data, *, split=True):
    flight = '0:'+json.dumps(data,ensure_ascii=False)+'\n'
    chunks = [flight[i:i+97] for i in range(0,len(flight),97)] if split else [flight]
    return ''.join('<script>self.__next_f.push('+json.dumps([1,chunk])+')</script>' for chunk in chunks)


def encrypted(url):
    raw = json.dumps({'file':url}).encode()
    data = AES.new(ohli365.METADATA_KEY,AES.MODE_CBC,ohli365.METADATA_IV).encrypt(pad(raw,16))
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def fixture_client(*, movie=False):
    data = {'anime':{'id':WORK_ID,'title':'테스트 작품','mediaType':'movie' if movie else 'tv','isDemo':False},
            'episodes':[] if movie else [{'id':EP_ID,'title':'첫 만남','number':1,'season':1,'duration':3}]}
    selected = WORK_ID if movie else EP_ID
    playback = {'sourceType':'iframe','sourceUrl':PLAYER,'responseId':'megaplay:'+selected,
                'episodeId':None if movie else EP_ID,'profileId':'public'}
    sources = {'enc':encrypted(MEDIA),'tracks':[{'kind':'captions','file':SUBTITLE,'label':'English'}]}
    manifest = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=1280x720\nindex-f1.m3u8\n'
    leaf = '#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:3,\nhttps://abc12.rotating-cdn.top'+PREFIX+'seg-f1-00000.jpg\n#EXT-X-ENDLIST\n'
    routes = {WORK:page(data), API:json.dumps(playback), PLAYER:'<div id="megaplay-player" data-id="42"></div>',
              SOURCES:json.dumps(sources), MEDIA:manifest, CHILD:leaf,
              SUBTITLE:'WEBVTT\n\n00:00.000 --> 00:03.000\nFixture subtitle\n'}
    return FixtureClient(routes), data, playback, sources


@pytest.mark.parametrize('suffix,collection', [('',True),('&episode='+EP_ID,False),('&episode=movie',False)])
def test_route_capabilities_and_preparation(suffix,collection):
    url = WORK+suffix
    route = parse_episode_url(url+'&utm_source=tracking#top')
    assert route['url'] == url and route['collection'] is collection
    assert route['site'] == media_platform(url) == 'ohli365'
    assert get_media_logger(url).name == 'phrolova.ohli365'
    assert VodPrepareRequest(urls=[url],source='ohli365').source == 'ohli365'
    assert any(s['id']=='ohli365' for s in asyncio.run(vod_capabilities())['sources'])
    assert EpisodeSiteIE.suitable(url) is not collection
    if collection:
        with pytest.raises(ValueError,match='회차'):canonical_platform_video(url)
    else:
        assert canonical_platform_video(url) == canonical_prepared_url(url,'ohli365') == url


@pytest.mark.parametrize('url', [
    'https://v2.ohli365.org/', WORK.replace('https:','http:'), WORK.replace('.org/','.org.evil/'),
    WORK.replace('v2.ohli365.org','u:p@v2.ohli365.org'), WORK.replace('.org/','.org:444/'),
    WORK.replace('v2.ohli365.org','v3.ohli365.org'), WORK.replace('/?','/watch?'),
    WORK+'&title='+WORK_ID, WORK+'&episode=', EPISODE+'&episode='+EP_ID,
    WORK.replace(WORK_ID,'1234'), WORK+'&episode=not-an-id', WORK.replace(WORK_ID,WORK_ID+'%0a'),
])
def test_bad_addresses_are_rejected(url):
    with pytest.raises(EpisodeSiteError):parse_episode_url(url)
    assert not EpisodeSiteIE.suitable(url)


def test_catalog_reads_json_chunks_and_preserves_registered_ids():
    client,data,_,_=fixture_client()
    catalog=load_catalog(WORK,client)
    assert catalog['source']=='ohli365' and catalog['title']=='테스트 작품'
    assert catalog['episodes'][0]['url']==EPISODE
    assert catalog['episodes'][0]['title']=='1화 · 첫 만남'
    data['episodes'].append({'id':OTHER_ID,'number':1,'season':2,'title':'두 번째 시즌','playable':False})
    client.routes[WORK]=page(data)
    rows=load_catalog(WORK,client)['episodes']
    assert [r['id'] for r in rows]==[EP_ID,OTHER_ID] and rows[1]['available'] is False
    assert rows[1]['title'].startswith('2기 1화')


@pytest.mark.parametrize('change', ['wrong_work','missing_title','demo','bad_episode','duplicate_episode','wrong_kind','empty'])
def test_catalog_identity_and_unavailable_data(change):
    client,data,_,_=fixture_client()
    if change=='wrong_work':data['anime']['id']=OTHER_ID
    elif change=='missing_title':data['anime']['title']=''
    elif change=='demo':data['anime']['isDemo']=True
    elif change=='bad_episode':data['episodes'][0]['number']=True
    elif change=='duplicate_episode':data['episodes'].append(copy.deepcopy(data['episodes'][0]))
    elif change=='wrong_kind':data['anime']['mediaType']='unknown'
    elif change=='empty':data['episodes']=[]
    client.routes[WORK]=page(data)
    with pytest.raises(EpisodeSiteError):load_catalog(WORK,client)


def test_unknown_episode_never_reaches_playback_api():
    client,_,_,_=fixture_client()
    with pytest.raises(EpisodeSiteError,match='등록되지'):extract_episode(WORK+'&episode='+OTHER_ID,client)
    assert not any(url==API for url,_ in client.calls)


def test_normal_playback_and_media_headers_and_subtitles():
    client,_,_,_=fixture_client()
    item=extract_episode(EPISODE,client)
    assert item['uploader']=='애니365' and item['subtitles']['en'][0]['data'].startswith('WEBVTT')
    assert item['http_headers']['Origin']=='https://megaplay.buzz'
    assert item['http_headers']['Referer']=='https://megaplay.buzz/'
    api=next(options for url,options in client.calls if url==API)
    assert api['json_body']=={'episodeId':EP_ID}
    assert api['headers']=={'Origin':'https://v2.ohli365.org'}
    assert all(options['headers']['Origin']=='https://megaplay.buzz'
               for url,options in client.calls if url in (MEDIA,CHILD,SUBTITLE))
    leaf=item['_ohli365_playlists'][CHILD]
    assert 'rotating-cdn.top' not in leaf and 'https://fetch.nexabloom.top'+PREFIX+'seg-f1-00000.jpg' in leaf
    assert not any('rotating-cdn.top' in url for url,_ in client.calls)


def test_public_movie_uses_anime_api_identity():
    client,_,_,_=fixture_client(movie=True)
    catalog=load_catalog(WORK,client)
    assert catalog['episodes'][0]['url']==WORK+'&episode=movie'
    extract_episode(WORK+'&episode=movie',client)
    assert next(o for u,o in client.calls if u==API)['json_body']=={'animeId':WORK_ID}
    with pytest.raises(EpisodeSiteError):extract_episode(EPISODE,client)


@pytest.mark.parametrize('filename',['seg-f1-v1-a1-00000.jpg','seg-1-f1-v1-a1.jpg'])
def test_variant_playlists_with_video_and_audio_track_suffixes(filename):
    client,_,_,_=fixture_client()
    child=CHILD.replace('index-f1','index-f1-v1-a1')
    client.routes[MEDIA]=client.routes[MEDIA].replace('index-f1','index-f1-v1-a1')
    client.routes[child]=client.routes.pop(CHILD).replace('seg-f1-00000.jpg',filename)
    item=extract_episode(EPISODE,client)
    assert 'index-f1-v1-a1.m3u8' in item['manifest']
    assert 'https://fetch.nexabloom.top'+PREFIX+filename in item['_ohli365_playlists'][child]


@pytest.mark.parametrize('field,value', [
    ('episodeId',OTHER_ID),('responseId','megaplay:'+OTHER_ID),('profileId','private'),
    ('sourceType','unknown'),('sourceUrl','https://127.0.0.1/stream/ani/42/1/sub'),
    ('sourceUrl',PLAYER.replace('.buzz/','.buzz.evil/')),('sourceUrl',PLAYER.replace('/42/','/ads/')),
])
def test_changed_playback_id_and_unrelated_player_are_rejected(field,value):
    client,_,playback,_=fixture_client();playback[field]=value;client.routes[API]=json.dumps(playback)
    with pytest.raises(EpisodeSiteError):extract_episode(EPISODE,client)
    assert not any('127.0.0.1' in url or '.evil' in url for url,_ in client.calls)


def test_captured_public_metadata_vector():
    vector=json.loads((Path(__file__).parent/'fixtures/ohli365-metadata.json').read_text(encoding='utf-8'))
    assert ohli365._source_metadata({'enc':vector['ciphertext']})==vector['file']


@pytest.mark.parametrize('value', [None,'','%%%%','AAAA','a'*65537],
                         ids=['null','empty','non-base64','truncated','oversized'])
def test_bad_encoded_metadata_is_a_useful_error(value):
    with pytest.raises(EpisodeSiteError,match='재생 주소'):ohli365._source_metadata({'enc':value})


@pytest.mark.parametrize('url', ['https://127.0.0.1/a.m3u8','https://fetch.nexabloom.top.evil/a.m3u8',
                                MEDIA.replace('https:','http:'),MEDIA.replace('fetch.','u:p@fetch.')])
def test_metadata_cannot_select_unrelated_hosts(url):
    with pytest.raises(EpisodeSiteError):ohli365._source_metadata({'enc':encrypted(url)})


@pytest.mark.parametrize('reference', [
    'https://127.0.0.1'+PREFIX+'seg-f1-00000.jpg',
    'https://abc12.rotating-cdn.top'+PREFIX.replace('a'*32,'c'*32)+'seg-f1-00000.jpg',
    'http://abc12.rotating-cdn.top'+PREFIX+'seg-f1-00000.jpg',
    'https://u:p@abc12.rotating-cdn.top'+PREFIX+'seg-f1-00000.jpg',
    'https://abc12.rotating-cdn.top'+PREFIX+'../admin',
])
def test_playlist_aliases_never_allow_other_identity_or_origin_requests(reference):
    client,_,_,_=fixture_client()
    client.routes[CHILD]=client.routes[CHILD].replace('https://abc12.rotating-cdn.top'+PREFIX+'seg-f1-00000.jpg',reference)
    with pytest.raises(EpisodeSiteError):extract_episode(EPISODE,client)
    assert all(urlsplit(url).hostname not in ('127.0.0.1','evil.example','abc12.rotating-cdn.top') for url,_ in client.calls)


def test_untrusted_alias_is_only_a_path_and_is_never_requested():
    client,_,_,_=fixture_client()
    client.routes[CHILD]=client.routes[CHILD].replace('abc12.rotating-cdn.top','untrusted.example')
    item=extract_episode(EPISODE,client)
    assert 'untrusted.example' not in item['_ohli365_playlists'][CHILD]
    assert all(urlsplit(url).hostname!='untrusted.example' for url,_ in client.calls)


@pytest.mark.parametrize('label,language', [('English','en'),(' Korean ','ko'),('Unknown','und')])
def test_hashed_subtitle_filename_uses_advertised_language(label,language):
    client,_,_,sources=fixture_client()
    subtitle=SUBTITLE.replace('track_0_eng','c'*32)
    sources['tracks'][0].update(file=subtitle,label=label)
    client.routes[SOURCES]=json.dumps(sources)
    client.routes[subtitle]=client.routes.pop(SUBTITLE)
    assert extract_episode(EPISODE,client)['subtitles'][language][0]['data'].startswith('WEBVTT')


@pytest.mark.parametrize('filename',['track_0_eng','c'*32])
def test_missing_optional_subtitle_keeps_video_but_wrong_identity_fails(filename):
    client,_,_,sources=fixture_client();client.routes[SUBTITLE]='<html>unavailable</html>'
    assert extract_episode(EPISODE,client)['subtitles']=={}
    client,_,_,sources=fixture_client()
    sources['tracks'][0]['file']=SUBTITLE.replace('track_0_eng',filename).replace('b'*32,'d'*32)
    client.routes[SOURCES]=json.dumps(sources)
    with pytest.raises(EpisodeSiteError,match='자막'):extract_episode(EPISODE,client)
