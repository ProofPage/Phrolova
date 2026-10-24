import asyncio
import json

import pytest

from app.api.vod import VodPrepareRequest, vod_capabilities
from app.core.logger import get_media_logger
from app.engine.episode_extractor import EpisodeSiteIE
from app.engine.episode_sites import EpisodeSiteError, extract_episode, load_catalog, parse_episode_url, validate_hls
from app.engine.platform_media import canonical_platform_video, media_platform
from app.engine.vod_preparation import canonical_prepared_url
from tests.test_episode_sites import FixtureClient

WORK='https://animaru1.com/content/42'
EPISODE=WORK+'/1.5'
API='https://api.storagewebtoon.store'
READER=API+'/api/v1/reader/v1/works/42'
PLAYER=API+'/api/v1/v1/anime/player/100'
MEDIA=API+'/api/v1/v1/anime/playlist/100/index.m3u8'
KEY=API+'/api/v1/v1/anime/key/100'
SUBTITLE='https://play.storagewebtoon.store/ani/42/401/subtitle.vtt'
DOMAINS=('api.storagewebtoon.store','play.storagewebtoon.store')


def fixture_client():
    data={'ok':True,'item':{'id':42,'title':'테스트 애니메이션','media_type':'ANIME','adult':False,'episode_count':3},
          'episodes':[{'id':403,'number':3,'title':'3','ready':False,'embed_url':''},
                      {'id':401,'number':1.5,'title':'1.5','ready':True,'embed_url':PLAYER},
                      {'id':400,'number':0,'title':'특별편','ready':True,'embed_url':PLAYER.replace('100','99')}]}
    page=("<video id='player' controls></video><script>var s='"+MEDIA+"';"
          "var tr=document.createElement('track');tr.kind='subtitles';tr.srclang='ko';tr.src='"+SUBTITLE+"';</script>")
    manifest=('#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXT-X-KEY:METHOD=AES-128,URI="'+KEY+'"\n'
              '#EXTINF:3.5,\nhttps://play.storagewebtoon.store/ani/42/401/VaSTCAY0CX.dat\n#EXT-X-ENDLIST\n')
    return FixtureClient({READER:json.dumps(data),PLAYER:page,MEDIA:manifest,KEY:bytes(range(16)),
                          SUBTITLE:'WEBVTT\n\n00:00.000 --> 00:02.000\nFixture subtitle\n'}),data


@pytest.mark.parametrize('suffix,episode', [('',None),('/1','1'),('/0','0'),('/1.50','1.5'),('/1.0','1')])
def test_routes_aliases_and_source_integration(suffix,episode):
    url=WORK+suffix
    route=parse_episode_url(url.replace('/content/','/contents/')+'/?ref=tracking#top')
    canonical=WORK+('/'+episode if episode is not None else '')
    assert route['url']==canonical and route['episode']==episode
    assert route['collection']==(episode is None) and media_platform(url)=='animaru'
    assert 'animaru' in get_media_logger(url).name
    assert VodPrepareRequest(urls=[url],source='animaru').source=='animaru'
    assert any(s['id']=='animaru' for s in asyncio.run(vod_capabilities())['sources'])
    if episode is not None:
        assert EpisodeSiteIE.suitable(canonical)
        assert canonical_platform_video(url)==canonical_prepared_url(url,'animaru')==canonical
    else:
        with pytest.raises(ValueError,match='회차'):canonical_platform_video(url)


@pytest.mark.parametrize('url',[
    'http://animaru1.com/content/42/1','https://animaru1.com.evil/content/42/1',
    'https://u:p@animaru1.com/content/42/1','https://animaru1.com:444/content/42/1',
    'https://animaru1.com/','https://animaru1.com/content/0/1','https://animaru1.com/content/42/01',
    'https://animaru1.com/content/42/-1','https://animaru1.com/content/42/1e2',
    'https://animaru1.com/content/42/1000000','https://animaru1.com/content/42/%0a',
    'https://animaru1.com/content/42/1/extra',
])
def test_invalid_urls(url):
    with pytest.raises(EpisodeSiteError):parse_episode_url(url)


def test_catalog_order_availability_and_actual_episode_numbers():
    client,data=fixture_client();catalog=load_catalog(WORK,client)
    assert catalog['title']=='테스트 애니메이션'
    assert [r['id'] for r in catalog['episodes']]==['0','1.5','3']
    assert [r['available'] for r in catalog['episodes']]==[True,True,False]
    assert catalog['episodes'][1]['title']=='1.5화'
    assert list(client.routes)==[READER,PLAYER,MEDIA,KEY,SUBTITLE]
    assert 'storagewebtoon' not in json.dumps(catalog)
    data['item']['episode_count']=10;client.routes[READER]=json.dumps(data)
    assert load_catalog(WORK,client)['incomplete'] is True
    assert len(load_catalog(EPISODE,client)['episodes'])==1
    with pytest.raises(EpisodeSiteError,match='등록되지'):load_catalog(WORK+'/2',client)
    with pytest.raises(EpisodeSiteError,match='준비되지'):extract_episode(WORK+'/3',client)


def test_native_guest_extraction_duration_key_and_subtitle():
    client,_=fixture_client();item=extract_episode(EPISODE,client)
    assert item['title']=='테스트 애니메이션 · 1.5화' and item['id']=='42-401'
    assert item['duration']==3.5 and item['url']==MEDIA and item['is_live'] is False
    assert item['subtitles']['ko'][0]['data'].startswith('WEBVTT')
    assert item['http_headers']['Referer']==PLAYER and item['http_headers']['Origin']==API
    assert client.calls[0][0]==READER and client.calls[0][1]['referer']==EPISODE
    assert next(kwargs for url,kwargs in client.calls if url==KEY)['prefix_bytes']==17


@pytest.mark.parametrize('field,value,message',[
    ('ok',False,'작품'),('id',43,'ID'),('media_type','WEBTOON','종류'),('adult',True,'권한'),
    ('title','','제목'),('episodes',[],'목록'),('number',False,'번호'),
    ('number',-1,'번호'),('number',float('nan'),'번호'),('embed_url',123,'주소'),
])
def test_changed_api_data_is_rejected(field,value,message):
    client,data=fixture_client()
    if field in ('ok','episodes'):data[field]=value
    elif field in ('number','embed_url'):data['episodes'][1][field]=value
    else:data['item'][field]=value
    client.routes[READER]=json.dumps(data)
    with pytest.raises(EpisodeSiteError,match=message):load_catalog(WORK,client)


def test_duplicate_episode_numbers_and_ids_are_errors():
    client,data=fixture_client();row=data['episodes'][1]
    data['episodes'].append({**row,'id':999})
    client.routes[READER]=json.dumps(data)
    with pytest.raises(EpisodeSiteError,match='중복'):load_catalog(WORK,client)
    data['episodes'][-1]={**row,'number':2};client.routes[READER]=json.dumps(data)
    with pytest.raises(EpisodeSiteError,match='중복'):load_catalog(WORK,client)


@pytest.mark.parametrize('url',[
    PLAYER.replace('api.storagewebtoon.store','api.storagewebtoon.store.evil'),
    PLAYER.replace('api.storagewebtoon.store','u:p@api.storagewebtoon.store'),
    PLAYER.replace('/anime/player/','/anime/admin/'),PLAYER+'?other=1',
])
def test_player_url_boundaries(url):
    client,data=fixture_client();data['episodes'][1]['embed_url']=url;client.routes[READER]=json.dumps(data)
    with pytest.raises(EpisodeSiteError):extract_episode(EPISODE,client)
    assert not any('evil' in u for u,_ in client.calls)


def test_player_and_playlist_id_checks():
    client,_=fixture_client();client.routes[PLAYER]=(PLAYER.replace('/100','/101'),client.routes[PLAYER])
    with pytest.raises(EpisodeSiteError,match='ID'):extract_episode(EPISODE,client)
    client,_=fixture_client();client.routes[PLAYER]=client.routes[PLAYER].replace('/playlist/100/','/playlist/101/')
    with pytest.raises(EpisodeSiteError,match='ID'):extract_episode(EPISODE,client)
    client,_=fixture_client();client.routes[PLAYER]=client.routes[PLAYER].replace("id='player'","id='advert'")
    with pytest.raises(EpisodeSiteError,match='본편'):extract_episode(EPISODE,client)
    client,_=fixture_client();client.routes[KEY]=b'nonstandard-key-response'
    with pytest.raises(EpisodeSiteError,match='표준 HLS 키'):extract_episode(EPISODE,client)


def test_subtitles_are_validated_without_losing_video_on_missing_optional_text():
    client,_=fixture_client();client.routes[SUBTITLE]='<html>Not a subtitle</html>'
    assert extract_episode(EPISODE,client)['subtitles']=={}
    client,_=fixture_client();client.routes[PLAYER]=client.routes[PLAYER].replace('/ani/42/401/','/ani/42/402/')
    with pytest.raises(EpisodeSiteError,match='자막'):extract_episode(EPISODE,client)
    client,_=fixture_client();client.routes[PLAYER]=client.routes[PLAYER].replace('play.storagewebtoon.store/ani','evil.invalid/ani')
    with pytest.raises(EpisodeSiteError):extract_episode(EPISODE,client)


@pytest.mark.parametrize('marker',[
    '#EXT-X-CUE-OUT:30','#EXT-X-DATERANGE:ID="ad"', '#EXT-OATCLS-SCTE35:AA',
    '#VAST:ad','#EXT-X-INTERSTITIAL:ad','#EXT-X-SESSION-KEY:METHOD=AES-128,URI="key"',
    '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key"',
])
def test_ad_tags_and_protected_keys_still_fail(marker):
    client,_=fixture_client();client.routes[MEDIA]=client.routes[MEDIA].replace('#EXTINF:3.5,',marker+'\n#EXTINF:3.5,')
    with pytest.raises(EpisodeSiteError):validate_hls(client,MEDIA,PLAYER,DOMAINS)


@pytest.mark.parametrize('name',['VaSTCAY0CX.dat','interstitialMovie.bin','SAMPLE-AES-token.xyz','scte35video.ts'])
def test_random_media_names_are_not_ad_markers(name):
    client,_=fixture_client();client.routes[MEDIA]=client.routes[MEDIA].replace('VaSTCAY0CX.dat',name)
    assert validate_hls(client,MEDIA,PLAYER,DOMAINS)[1].startswith('#EXTM3U')
