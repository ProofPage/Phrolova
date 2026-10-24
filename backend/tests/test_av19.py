import hashlib
import json
import subprocess
from unittest.mock import Mock

import httpx
import pytest
from yt_dlp.networking import Request
from yt_dlp.utils import ExtractorError

from app.engine import av19
from app.engine.av19_downloader import AV19YoutubeDL
from app.engine.episode_sites import EpisodeSiteError, SiteClient, extract_episode, load_catalog
from app.engine.platform_media import media_platform, platform_ydl
from app.engine.vod_preparation import canonical_prepared_url

PAGE = 'https://av19t.com/nsub/152'
IDENTITY = '0' * 32
MANIFEST = f'https://jp2.vdnext.com/cast2/{IDENTITY}/v.html?tok=neutral&exp=9999999999'
KEY = f'https://jp.tavireo.store/v/session?v={IDENTITY}&p=0&t=neutral&e=9999999999'
SEGMENT = f'https://jp.tavireo.store/cast2/{IDENTITY}/000000.gif'
PLAYER = 'https://p.nnvivi.site/player.php?k=' + IDENTITY
PLAYLIST = f'#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXT-X-KEY:METHOD=AES-128,URI="{KEY}"\n#EXTINF:4,\n{SEGMENT}\n#EXT-X-ENDLIST\n'


@pytest.mark.parametrize('category', ['nsub', 'korea', 'bj'])
def test_routes(category):
    url = f'https://www.av19t.com/{category}/152/?tracking=1'
    assert canonical_prepared_url(url, 'av19') == f'https://av19t.com/{category}/152'
    assert media_platform(url) == 'av19'
    with platform_ydl(url, {'quiet': True}) as ydl:
        assert isinstance(ydl, AV19YoutubeDL)
        assert ydl._ies['EpisodeSite'].suitable(url)
    with pytest.raises(EpisodeSiteError):
        load_catalog(url, Mock())


@pytest.mark.parametrize('url', [
    'http://av19t.com/nsub/1', 'https://av19t.com/nsub', 'https://av19t.com/nsub/0',
    'https://av19t.com/nsub/%31', 'https://av19t.com/catalog/1',
    'https://av19t.com:444/nsub/1', 'https://user@av19t.com/nsub/1',
    'https://127.0.0.1/nsub/1', 'https://av19t.com.evil/nsub/1',
])
def test_invalid_routes(url):
    with pytest.raises(ValueError):
        canonical_prepared_url(url, 'av19')


@pytest.mark.parametrize('path', ['korea/104856', 'bj/40043'])
def test_observed_version11_categories_route_to_native_extractor(path):
    url = 'https://av19t.com/' + path
    assert canonical_prepared_url(url, 'av19') == url
    with platform_ydl(url, {'quiet': True}) as ydl:
        assert ydl._ies['EpisodeSite'].suitable(url)
    with pytest.raises(EpisodeSiteError):
        av19.parse_av19_url('https://av19t.com.evil/' + path)


@pytest.mark.parametrize('category', ['korea', 'bj'])
def test_observed_version11_envelope_uses_verified_session_decoder(monkeypatch, category):
    module = b'neutral module'
    monkeypatch.setattr(av19, 'WASM_SHA384', hashlib.sha384(module).hexdigest())
    run = Mock(return_value=Mock(returncode=0, stdout=b'0'*16))
    monkeypatch.setattr(av19.subprocess, 'run', run)
    monkeypatch.setattr('app.engine.youtube_support.runtime_options', lambda: {'js_runtimes': {'node': {'path': 'node'}}})
    # Neutral field-only fixtures for both inspected players; no real session data.
    fields = dict(version=11, key_length=16, encrypted_key='neutral',
                  bytecode_cipher='neutral', bytecode_nonce='neutral', session_seed='neutral')
    if category == 'bj':
        fields = dict(reversed(list(fields.items())))
    assert av19.decode_key(module, json.dumps(fields).encode()) == b'0'*16
    assert run.call_count == 1
    for field in ('encrypted_key', 'bytecode_cipher', 'bytecode_nonce', 'session_seed'):
        malformed = {**fields, field: []}
        with pytest.raises(EpisodeSiteError):
            av19.decode_key(module, json.dumps(malformed).encode())


@pytest.mark.parametrize('host', [
    'k.vdnext.com.evil', 'jp2.vdnext.com.evil',
    'frostspring616.site', 'hazelglade859.site', 'hazelhaven847.site',
    'linencove681.site', 'mapleglade323.site', 'oakwood896.site',
    'frostspring616.site.evil',
])
def test_manifest_role_and_host_lookalikes_are_rejected(host):
    with pytest.raises(EpisodeSiteError):
        av19.resource_url(f'https://{host}/cast2/{IDENTITY}/v.html?tok=neutral&exp=9999999999',
                          IDENTITY, 'manifest')


@pytest.mark.parametrize('host', av19.KR_SEGMENTS)
def test_version11_resource_family_and_hostile_paths(host):
    address = MANIFEST.replace('jp2.vdnext.com', 'k.vdnext.com')
    key = KEY.replace('jp.tavireo.store', 'k.vdnext.com')
    segment = f'https://{host}/s/cast2/{IDENTITY}/MWQ1OS12MDA0MDA.json'
    body = PLAYLIST.replace(KEY, key).replace(SEGMENT, segment)
    assert av19.validate_manifest(body, address, IDENTITY)[segment] == 'segment'
    for target in [segment.replace(host, host+'.evil'), segment.replace(IDENTITY, '1'*32),
                   segment.replace('MWQ1OS12MDA0MDA', 'malformed'),
                   segment+'?redirect=https://127.0.0.1/', segment.replace('https://', 'https://user@'),
                   SEGMENT]:
        with pytest.raises(EpisodeSiteError):
            av19.validate_manifest(body.replace(segment, target), address, IDENTITY)
    with pytest.raises(EpisodeSiteError):
        av19.validate_manifest(body, MANIFEST, IDENTITY)


@pytest.mark.parametrize('title', ['Neutral', ''])
def test_extract_neutral(monkeypatch, title):
    module = b'neutral module'
    monkeypatch.setattr(av19, 'WASM_SHA384', hashlib.sha384(module).hexdigest())
    client = Mock()
    config = json.dumps(MANIFEST)
    player = f'Level5Player.play({{url: {config}, wasmBin: "/assets/core?v=1", wasmSha384Hex: "{av19.WASM_SHA384}"}})'
    client.request.side_effect = [
        (PAGE, f'<title>{title}</title><iframe id="videoIframe" src="{PLAYER}"></iframe>'),
        (PLAYER, player), ('https://p.nnvivi.site/assets/core?v=1', module),
        (MANIFEST, PLAYLIST),
    ]
    if not title:
        with pytest.raises(EpisodeSiteError, match='제목'):
            extract_episode(PAGE, client)
        return
    item = extract_episode(PAGE, client)
    assert item['title'] == 'Neutral' and item['manifest'] == PLAYLIST
    assert item['_av19_delivery']['resources'][KEY] == 'key'
    assert all('validator' in call.kwargs for call in client.request.call_args_list)


@pytest.mark.parametrize('body', ['<html>Denied</html>', '{}', '#EXTM3U\n#EXT-X-ENDLIST'])
def test_invalid_manifest(body):
    with pytest.raises(EpisodeSiteError):
        av19.validate_manifest(body, MANIFEST, IDENTITY)


@pytest.mark.parametrize('target', [
    'https://127.0.0.1/private', 'https://jp.tavireo.store.evil/private',
    'https://jp.tavireo.store/private', 'https://user@jp.tavireo.store/v/session',
])
def test_redirects_blocked_before_second_request(target):
    seen = []
    client = SiteClient()
    client.http.close()
    def respond(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={'Location': target})
    client.http = httpx.Client(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(EpisodeSiteError):
            client.request(SEGMENT, av19.MEDIA, validator=lambda u: av19.resource_url(u, IDENTITY, 'segment'))
        assert seen == [SEGMENT]
    finally:
        client.close()


@pytest.mark.parametrize('status', [401, 403, 404, 429, 500])
def test_status_failures(status):
    client = SiteClient()
    client.http.close()
    client.http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status)))
    try:
        with pytest.raises(EpisodeSiteError):
            extract_episode(PAGE, client)
    finally:
        client.close()


@pytest.mark.parametrize('body', [
    '<title>Neutral</title>', '<title>Neutral</title><iframe src="https://ads.example/"></iframe>',
    '<iframe id="videoIframe" src="https://127.0.0.1/private"></iframe>',
])
def test_missing_or_ad_iframe(body):
    client = Mock()
    client.request.return_value = PAGE, body
    with pytest.raises(EpisodeSiteError):
        extract_episode(PAGE, client)
    assert client.request.call_count == 1


def test_network_failure():
    client = SiteClient()
    client.http.close()
    def fail(request):
        raise httpx.ReadTimeout('neutral timeout')
    client.http = httpx.Client(transport=httpx.MockTransport(fail))
    try:
        with pytest.raises(EpisodeSiteError):
            extract_episode(PAGE, client)
    finally:
        client.close()


def test_decode_boundary(monkeypatch):
    module = b'neutral'
    monkeypatch.setattr(av19, 'WASM_SHA384', hashlib.sha384(module).hexdigest())
    monkeypatch.setattr('app.engine.youtube_support.runtime_options', lambda: {'js_runtimes': {'node': {'path': 'node'}}})
    run = Mock(return_value=Mock(returncode=0, stdout=b'0'*16))
    monkeypatch.setattr(av19.subprocess, 'run', run)
    payload = json.dumps(dict(version=10, key_length=16, total_layers=10, layers=[{}]*10)).encode()
    assert av19.decode_key(module, payload) == b'0'*16
    assert run.call_args.kwargs['timeout'] == 10
    for invalid in [b'{}', b'not JSON', b'{"version":11}', b'x'*65537]:
        with pytest.raises(EpisodeSiteError):
            av19.decode_key(module, invalid)
    run.side_effect = subprocess.TimeoutExpired('node', 10)
    with pytest.raises(EpisodeSiteError):
        av19.decode_key(module, payload)


def test_native_hls_download_and_key_cache(monkeypatch, tmp_path):
    from Cryptodome.Cipher import AES
    from Cryptodome.Util.Padding import pad
    key = b'0'*16
    plain = (b'\x47' + b'\0'*187)*4
    cipher = AES.new(key, AES.MODE_CBC, iv=b'\0'*16).encrypt(pad(plain, 16))
    requests = []
    class Client:
        def request(self, address, domains, **kwargs):
            kwargs['validator'](address)
            requests.append(address)
            return address, {MANIFEST: PLAYLIST.encode(), KEY: b'neutral session', SEGMENT: cipher}[address]
        def close(self):
            pass
    monkeypatch.setattr('app.engine.av19_downloader.SiteClient', Client)
    monkeypatch.setattr('app.engine.av19_downloader.decode_key', lambda m, p: key)
    with AV19YoutubeDL({'quiet': True, 'fixup': 'never', 'outtmpl': str(tmp_path/'sample.%(ext)s'),
                       'hls_prefer_native': True, 'allowed_extensions': {'gif', 'ts', 'html'}}) as ydl:
        ydl.configure_av19(dict(resources=av19.validate_manifest(PLAYLIST, MANIFEST, IDENTITY),
                                identity=IDENTITY, module=b'neutral', referer=PLAYER))
        ydl.process_ie_result(dict(id='neutral', title='Neutral', formats=[
            dict(url=MANIFEST, ext='mp4', protocol='m3u8_native', format_id='hls')]), download=True)
        assert (tmp_path/'sample.mp4').read_bytes() == plain
        assert ydl.urlopen(Request(KEY)).read() == key
        with pytest.raises(ExtractorError):
            ydl.urlopen(Request('https://127.0.0.1/private'))
    assert requests.count(KEY) == 1


def test_log_masking():
    logger = Mock()
    for url in [PAGE, 'https://ym-05.com/videos/neutral/']:
        with platform_ydl(url, {'quiet': True, 'logger': logger}) as ydl:
            ydl.params['logger'].debug(KEY)
    assert all('neutral' not in c.args[0] for c in logger.debug.call_args_list)


def test_bridge_rejects_tampered_module():
    from pathlib import Path
    from app.engine.youtube_support import runtime_options
    node = runtime_options()['js_runtimes']['node']['path']
    payload = json.dumps({'module': 'AGFzbQEAAAA=', 'session': json.dumps(
        dict(version=10, key_length=16, total_layers=10, layers=[{}]*10))}).encode()
    result = subprocess.run([node, str(Path(av19.__file__).with_name('av19_key.cjs'))],
                            input=payload, capture_output=True, timeout=10)
    assert result.returncode == 1 and result.stdout == b'' and result.stderr == b''


@pytest.mark.asyncio
async def test_queue_metadata_duplicate_and_api(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from app.engine.vod import VodEngine
    from app.api.vod import VodPrepareRequest, vod_capabilities
    assert VodPrepareRequest(urls=[PAGE], source='av19').source == 'av19'
    sources = (await vod_capabilities())['sources']
    assert len(sources) == 25
    assert {'id': 'berriz', 'label': 'platform.berriz'} in sources
    assert {'id': 'av19', 'label': 'AV19'} in sources
    engine = VodEngine()
    monkeypatch.setattr(engine, 'get_video_info', AsyncMock(return_value=dict(
        id='nsub-152', title='Neutral', formats=[{'ext': 'mp4', 'format_id': 'hls'}])))
    result = engine.prepare_vods([PAGE, PAGE+'?tracking=1'], source='av19')
    await asyncio.gather(*engine._metadata_tasks)
    assert result['results'][1]['duplicate']
    task = engine._tasks[result['results'][0]['task_id']]
    assert task.phase == 'ready' and task.title == 'Neutral' and task.download_task is None


@pytest.mark.asyncio
@pytest.mark.parametrize('category', ['nsub', 'korea', 'bj'])
async def test_prepared_queue_refreshes_delivery_in_download_instance(monkeypatch, tmp_path, category):
    import asyncio
    from pathlib import Path
    from unittest.mock import AsyncMock
    from Cryptodome.Cipher import AES
    from Cryptodome.Util.Padding import pad
    from app.engine.vod import VodEngine, VodDownloadState
    from app.core.config import get_settings

    key = b'0' * 16
    plain = (b'\x47' + b'\0' * 187) * 4
    cipher = AES.new(key, AES.MODE_CBC, iv=b'\0'*16).encrypt(pad(plain, 16))
    deliveries, instances, decoded = [], [], []
    def extract(route, client):
        # Every metadata refresh issues different signed URLs and module state.
        index = len(deliveries) + 1
        address = MANIFEST.replace('tok=neutral', f'tok=neutral{index}')
        key_url = KEY.replace('t=neutral', f't=neutral{index}')
        playlist = PLAYLIST.replace(KEY, key_url)
        delivery = dict(module=f'neutral-module-{index}'.encode(), identity=IDENTITY,
                        referer=PLAYER, resources=av19.validate_manifest(playlist, address, IDENTITY))
        deliveries.append(delivery)
        return dict(id='nsub-152', title='Neutral', url=address, manifest=playlist,
                    webpage_url=PAGE, subtitles={}, http_headers={'Referer': PLAYER},
                    _av19_delivery=delivery)
    def factory(url, options):
        ydl = platform_ydl(url, options)
        instances.append(ydl)
        return ydl
    class Client:
        def request(self, address, domains, **kwargs):
            kwargs['validator'](address)
            assert address in deliveries[-1]['resources']
            if address == SEGMENT:
                return address, cipher
            if '/v/session?' in address:
                return address, b'neutral-session'
            raise AssertionError('Validated playlist must not be refetched: its key URL may rotate')
        def close(self):
            pass
    def decode(module, payload):
        assert instances[-1]._av19_delivery is deliveries[-1]
        decoded.append(module)
        return key
    monkeypatch.setattr(av19, 'extract_av19_episode', extract)
    monkeypatch.setattr('app.engine.vod.platform_ydl', factory)
    monkeypatch.setattr('app.engine.av19_downloader.SiteClient', Client)
    monkeypatch.setattr('app.engine.av19_downloader.decode_key', decode)
    engine = VodEngine()
    get_settings().vod_download_dir = str(tmp_path)
    monkeypatch.setattr(engine, '_build_ytdlp_options', lambda *a, **kw: {
        'quiet': True, 'fixup': 'never', 'outtmpl': str(tmp_path/'neutral.%(ext)s')})
    monkeypatch.setattr(engine, '_inspect_chzzk_download', AsyncMock())
    monkeypatch.setattr(engine, '_notify', Mock())
    result = engine.prepare_vods([PAGE.replace('/nsub/', f'/{category}/')], source='av19')
    await asyncio.gather(*engine._metadata_tasks)
    task = engine._tasks[result['results'][0]['task_id']]
    assert task.phase == 'ready'
    engine.start_prepared(task.task_id)
    await task.download_task
    assert task.state == VodDownloadState.COMPLETED, task.error_message
    assert Path(task.output_path).read_bytes() == plain
    assert len(instances) == len(deliveries) == 3
    assert instances[0] is not instances[1] and instances[1] is not instances[2]
    assert decoded == [b'neutral-module-3']
    public = json.dumps(engine.get_task_status(task.task_id))
    assert all(secret not in public for secret in ('tok=', 't=neutral', 'neutral-module', 'neutral-session', '_av19_delivery'))
