"""Observed AV19 Level5/session-v10/v11 player; no remote JavaScript execution.

The signed v.html is a VOD media playlist. Its AES-128 key URI returns a v10
JSON envelope, decoded by the player's pinned WASM decode_session export.
Segments are ordinary AES-CBC MPEG-TS (including those named .gif).
The korea/bj version-11 bytecode envelope uses the same pinned decode_session
export. Its /s/cast2 resources are also standard AES-CBC TS, not executable JS.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qs, urljoin, urlsplit

from yt_dlp.utils import parse_m3u8_attributes

from app.core.http import USER_AGENT
from app.engine.episode_sites import Document, EpisodeSiteError, checked_url

PLAYER = 'p.nnvivi.site'
JP_SEGMENTS = ('jp.tavireo.store', 'jp.navoriq.store', 'jp.kisoraq.site', 'jp.velunio.site')
KR_SEGMENTS = ('frostspring616.site', 'hazelglade859.site', 'hazelhaven847.site',
               'linencove681.site', 'mapleglade323.site', 'oakwood896.site')
MANIFEST_HOSTS = ('jp2.vdnext.com', 'k.vdnext.com')
MEDIA = (*MANIFEST_HOSTS, *JP_SEGMENTS, *KR_SEGMENTS)
SEGMENT_EXTENSIONS = {'json', 'woff', 'woff2', 'txt', 'vtt', 'srt', 'js', 'css', 'svg', 'webp', 'xml'}
WASM_SHA384 = '11ba14e9a68f13eaac9a5664056209bfd11302382e4c18bfe8f629af4ed0d7e80a69cc9b72fd339a0b8ee8d5461e0a72'


def parse_av19_url(value):
    value = checked_url(value, ('av19t.com', 'www.av19t.com'))
    parts = urlsplit(value)
    match = re.fullmatch(r'/(korea|bj|nsub)/([1-9]\d*)/?', parts.path)
    if not match:
        raise EpisodeSiteError('AV19 개별 영상 주소(/korea|bj|nsub/{id})를 입력하세요.')
    identity = '-'.join(match.groups())
    return dict(site='av19', work=identity, episode=identity, collection=False,
                url=f'https://av19t.com/{match[1]}/{match[2]}')


def player_url(value):
    value = checked_url(value, (PLAYER,))
    parts = urlsplit(value)
    if parts.path != '/player.php' or not re.fullmatch(r'k=[0-9a-f]{32}', parts.query) or parts.fragment:
        raise EpisodeSiteError('AV19 본편 플레이어 주소를 확인할 수 없습니다.')
    return value


def resource_url(value, identity, kind, *, manifest_host=None):
    value = checked_url(value, MEDIA)
    p = urlsplit(value)
    query = parse_qs(p.query, keep_blank_values=True)
    valid = not p.fragment and all(len(v) == 1 for v in query.values())
    valid &= manifest_host in (None, *MANIFEST_HOSTS)
    if kind == 'manifest':
        valid &= p.hostname in MANIFEST_HOSTS and p.path == f'/cast2/{identity}/v.html'
        valid &= manifest_host is None or p.hostname == manifest_host
        valid &= set(query) == {'tok', 'exp'}
        valid &= bool(re.fullmatch(r'[A-Za-z0-9_-]{1,128}', query.get('tok', [''])[0]))
        valid &= query.get('exp', [''])[0].isdigit()
    elif kind == 'key':
        hosts = JP_SEGMENTS if manifest_host == MANIFEST_HOSTS[0] else ('k.vdnext.com',) if manifest_host == MANIFEST_HOSTS[1] else (*JP_SEGMENTS, 'k.vdnext.com')
        valid &= p.hostname in hosts and p.path == '/v/session'
        valid &= set(query) == {'v', 'p', 't', 'e'} and query.get('v') == [identity]
        valid &= query.get('p', [''])[0].isdigit() and query.get('e', [''])[0].isdigit()
        valid &= bool(re.fullmatch(r'[A-Za-z0-9_-]{1,128}', query.get('t', [''])[0]))
    elif kind == 'segment':
        valid &= not p.query
        if p.hostname in JP_SEGMENTS:
            valid &= manifest_host in (None, MANIFEST_HOSTS[0])
            valid &= bool(re.fullmatch(r'/cast2/' + re.escape(identity) + r'/\d{6}\.gif', p.path))
        elif p.hostname in KR_SEGMENTS:
            valid &= manifest_host in (None, MANIFEST_HOSTS[1])
            match = re.fullmatch(r'/s/cast2/' + re.escape(identity) + r'/([A-Za-z0-9_-]{15})\.([a-z0-9]+)', p.path)
            valid &= bool(match and match[2] in SEGMENT_EXTENSIONS)
            if match:
                try:
                    name = base64.b64decode(match[1] + '=', altchars=b'-_', validate=True).decode('ascii')
                    valid &= bool(re.fullmatch(r'[0-9a-f]{4}-v\d{5}', name))
                except (ValueError, UnicodeError):
                    valid = False
        else:
            valid = False
    else:
        valid = False
    if not valid:
        raise EpisodeSiteError('AV19 영상 리소스 주소를 확인할 수 없습니다.')
    return value


def validate_manifest(text, address, identity):
    if not isinstance(text, str) or not text.startswith('#EXTM3U') or '#EXT-X-ENDLIST' not in text:
        raise EpisodeSiteError('AV19 정상 VOD 재생목록이 아닙니다. 영상 주소를 다시 준비하세요.')
    resources = {address: 'manifest'}
    family = urlsplit(resource_url(address, identity, 'manifest')).hostname
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('#EXT-X-KEY:'):
            attrs = parse_m3u8_attributes(line.partition(':')[2])
            if attrs.get('METHOD') != 'AES-128' or set(attrs) - {'METHOD', 'URI', 'IV'}:
                raise EpisodeSiteError('AV19 지원하지 않는 키 프로토콜입니다.')
            target = resource_url(urljoin(address, attrs.get('URI', '')), identity, 'key', manifest_host=family)
            resources[target] = 'key'
        elif not line.startswith('#'):
            target = resource_url(urljoin(address, line), identity, 'segment', manifest_host=family)
            resources[target] = 'segment'
        elif ('URI=' in line or line.startswith(('#EXT-X-STREAM-INF', '#EXT-X-BYTERANGE'))):
            raise EpisodeSiteError('AV19 지원하지 않는 재생목록 형식입니다.')
    if 'key' not in resources.values() or 'segment' not in resources.values():
        raise EpisodeSiteError('AV19 본편 영상 또는 키가 없습니다.')
    return resources


def decode_key(module, payload):
    from app.engine.youtube_support import runtime_options
    if len(module) > 524288 or hashlib.sha384(module).hexdigest() != WASM_SHA384:
        raise EpisodeSiteError('AV19 플레이어 WASM 버전 또는 무결성을 확인할 수 없습니다.')
    if not isinstance(payload, bytes) or len(payload) > 65536:
        raise EpisodeSiteError('AV19 세션 키 응답이 너무 큽니다.')
    try:
        obj = json.loads(payload.decode('utf-8'))
        if not isinstance(obj, dict) or type(obj.get('version')) is not int or obj.get('key_length') != 16:
            raise ValueError
        if obj['version'] == 10:
            if obj.get('total_layers') != 10 or not isinstance(obj.get('layers'), list) or len(obj['layers']) != 10:
                raise ValueError
        elif obj['version'] == 11:
            fields = {'encrypted_key': 1024, 'bytecode_cipher': 32768, 'bytecode_nonce': 256, 'session_seed': 256}
            if set(obj) != {'version', 'key_length', *fields} or any(
                    not isinstance(obj[k], str) or not 1 <= len(obj[k]) <= cap for k, cap in fields.items()):
                raise ValueError
        else:
            raise ValueError
    except (ValueError, UnicodeError):
        raise EpisodeSiteError('AV19 세션 키 형식·버전이 변경되었거나 만료되었습니다. 영상 주소를 다시 준비하세요.') from None
    node = runtime_options().get('js_runtimes', {}).get('node', {}).get('path')
    if not node:
        raise EpisodeSiteError('AV19 다운로드에 Node.js 22+가 필요합니다.')
    data = json.dumps({'module': base64.b64encode(module).decode('ascii'),
                       'session': payload.decode('utf-8')}).encode()
    try:
        result = subprocess.run(
            [node, '--max-old-space-size=48', '--wasm-max-mem-pages=512',
             str(Path(__file__).with_name('av19_key.cjs'))],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise EpisodeSiteError('AV19 키 디코더 실행에 실패했습니다. Node.js와 접속 상태를 확인하세요.') from None
    if result.returncode or len(result.stdout) != 16:
        raise EpisodeSiteError('AV19 세션 키를 해석할 수 없습니다. 영상 주소를 다시 준비하세요.')
    return result.stdout


def extract_av19_episode(route, client):
    def same_page(value):
        if parse_av19_url(value)['url'] != route['url']:
            raise EpisodeSiteError('요청한 AV19 영상과 이동한 영상이 다릅니다.')
        return value
    final, html = client.request(route['url'], ('av19t.com', 'www.av19t.com'), validator=same_page)
    doc = Document(html).root
    frames = doc.find('iframe', id='videoIframe')
    if len(frames) != 1:
        raise EpisodeSiteError('AV19 본편 플레이어를 찾을 수 없습니다.')
    player = player_url(urljoin(final, frames[0].attrs.get('src', '')))
    _, source = client.request(player, (PLAYER,), referer=final, validator=player_url)
    if 'Level5Player.play({' not in source:
        raise EpisodeSiteError('AV19 지원하는 공개 플레이어가 아닙니다.')
    def field(name):
        match = re.search(r'\b' + name + r'\s*:\s*("(?:\\.|[^"\\])*")', source)
        if not match:
            raise EpisodeSiteError('AV19 플레이어 설정을 확인할 수 없습니다.')
        try:
            return json.loads(match[1])
        except ValueError:
            raise EpisodeSiteError('AV19 플레이어 설정이 올바르지 않습니다.') from None
    address = field('url')
    match = re.fullmatch(r'/cast2/([0-9a-f]{32})/v\.html', urlsplit(address).path)
    if not match:
        raise EpisodeSiteError('AV19 본편 재생목록을 확인할 수 없습니다.')
    identity = match[1]
    address = resource_url(address, identity, 'manifest')
    if field('wasmSha384Hex') != WASM_SHA384:
        raise EpisodeSiteError('AV19 플레이어 버전이 변경되었습니다.')
    def module_url(value):
        value = checked_url(value, (PLAYER,))
        p = urlsplit(value)
        if p.path != '/assets/core' or not re.fullmatch(r'v=\d+', p.query) or p.fragment:
            raise EpisodeSiteError('AV19 WASM 주소가 올바르지 않습니다.')
        return value
    module_address = module_url(urljoin(player, field('wasmBin')))
    _, module = client.request(module_address, (PLAYER,), referer=player, binary=True,
                               validator=module_url, max_bytes=524288)
    if hashlib.sha384(module).hexdigest() != WASM_SHA384:
        raise EpisodeSiteError('AV19 플레이어 WASM 무결성을 확인할 수 없습니다.')
    _, manifest = client.request(address, MEDIA, referer=player,
                                 validator=lambda u: resource_url(u, identity, 'manifest', manifest_host=urlsplit(address).hostname))
    resources = validate_manifest(manifest, address, identity)
    titles = doc.find('meta', property='og:title')
    title = titles[0].attrs.get('content', '').strip() if titles else ''
    title = title or next((n.text.strip() for n in doc.find('title') if n.text.strip()), '')
    if not title:
        raise EpisodeSiteError('AV19 영상 제목을 확인할 수 없습니다.')
    return dict(id=route['episode'], title=title, site='av19', url=address,
                webpage_url=route['url'], manifest=manifest, subtitles={},
                http_headers={'User-Agent': USER_AGENT, 'Referer': player},
                _av19_delivery=dict(module=module, resources=resources, identity=identity, referer=player,
                                    manifest_host=urlsplit(address).hostname))
