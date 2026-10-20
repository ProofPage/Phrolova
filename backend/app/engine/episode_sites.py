"""첨부 Lua 플러그인의 작품·회차 규칙을 기존 동영상 큐에 연결한다."""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import json
import math
import re
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

import httpx

from app.core.http import USER_AGENT
from app.core.episode_domains import NUMBERED_SITE_HOSTS

SITES = {
    'ohli365': {'name': '애니365', 'hosts': ('v2.ohli365.org', 'ohli365.org', 'www.ohli365.org'), 'players': ('megaplay.buzz',),
                'media': ('nexabloom.top', 'qeltrix.top', 'silverorbit.top', 'broforgotsave.online')},
    'animaru': {'name': '애니마루', 'hosts': (NUMBERED_SITE_HOSTS['animaru'],),
                'api': ('api.storagewebtoon.store',),
                'media': ('api.storagewebtoon.store', 'play.storagewebtoon.store')},
    'tvwiki': {'name': '티비위키', 'hosts': (NUMBERED_SITE_HOSTS['tvwiki'],),
               'players': ('player.bunny-frame.online', 'bunny-cdn-player.online'),
               'media': ('poorcdn.com', 'toki56.com', 'amberbloom784.site', 'azuretrail425.site',
                         'breezymeadow545.site', 'cedarshore437.site', 'feff3f33.site', 'quietharbor140.site',
                         'cosmiccore763.com', 'cosmicpulse421.com', 'helixshore253.com', 'orbitflux694.com',
                         'polaredge239.com', 'prismcore161.com', 'quartzpulse842.com', 'solarrift733.com',
                         'stellardeck951.com', 'stormzone585.com', 'swiftdeck166.com', 'turbolink982.com',
                         'vividport408.com',
                         re.compile(r'(?:[a-z0-9-]+\.)*[a-z]+[0-9]+\.(?:com|site)'))},
    'anilife': {'name': '애니라이프', 'hosts': (NUMBERED_SITE_HOSTS['anilife'],),
                'media': ('aniplayer1.site', 'noblepulse539.com', 'quietsummit393.com', 'getvfa.store', 'getvfa.site', 's9.toki56.com')},
    'linkani': {'name': 'Linkani', 'hosts': ('linkani.tv',),
                'media': ('aniplayer1.site', 'noblepulse539.com', 'quietsummit393.com', 'getvfa.store', 'getvfa.site', 's9.toki56.com')},
    'ohli24': {'name': '애니24', 'hosts': ('www.ohli24.net', 'ohli24.net', 'ani.ohli24.com', 'ohli24.com', 'www.ohli24.com'),
               'players': ('michealcdn.com', 'cdndania.com'),
               # 회차별로 다른 세대의 CDN을 반환하므로 확인된 요일별 호스트 계열을 모두 허용한다.
               'media': ('michealcdn.com', 'cdndania.com',
                         *(f'{day}{i}bcloud-starcdn.xyz' for day in ('mon','tue','wed','thu','fri','sat','sun') for i in range(1, 8)),
                         *(f'hol{i}ncloud{generation}-nocdn.xyz' for generation in (1, 2) for i in range(1, 8)),
                         *(f'ohli{i}ncloud{generation}-nocdn.xyz' for generation in range(1, 6) for i in range(1, 8)))},
}
AD_PATH = re.compile(r'/(?:ads?|banner|advert[^/]*|popunder|tracking)/', re.I)


class EpisodeSiteError(ValueError):
    def __init__(self, message, *, status=None):
        super().__init__(message)
        self.status = status


def _host_allowed(host, domains, *, subdomains=False):
    if not host or len(host) > 253 or any(len(label) > 63 for label in host.split('.')):
        return False
    return any(bool(domain.fullmatch(host)) if isinstance(domain, re.Pattern)
               else host == domain or subdomains and host.endswith('.'+domain) for domain in domains)


def checked_url(value: str, domains, *, subdomains=False) -> str:
    try:
        if not isinstance(value, str) or re.search(r'[\s\x00-\x1f\x7f\\]', value):
            raise ValueError
        parts = urlsplit(value)
        host = (parts.hostname or '').lower()
        if (parts.scheme != 'https' or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443) or not _host_allowed(host, domains, subdomains=subdomains)):
            raise ValueError
        path = unquote(parts.path)
        if re.search(r'[\x00-\x1f\x7f\\]', path) or AD_PATH.search(path):
            raise ValueError
        return str(httpx.URL(value))
    except ValueError:
        raise EpisodeSiteError('콘텐츠 주소의 호스트·HTTPS 경로를 확인할 수 없습니다.') from None


def site_for_url(value: str) -> str | None:
    try:
        host = urlsplit(value).hostname
        return next((site for site, data in SITES.items() if _host_allowed(host or '', data['hosts'])), None)
    except ValueError:
        return None


def parse_episode_url(value: str) -> dict:
    site = site_for_url(value)
    if not site:
        raise EpisodeSiteError('지원하는 작품 또는 회차 주소를 입력하세요.')
    value = checked_url(value, SITES[site]['hosts'])
    parts = urlsplit(value)
    path = parts.path
    if site == 'ohli365':
        from app.engine.ohli365 import parse_ohli365_url
        return parse_ohli365_url(value)
    if site == 'animaru':
        from app.engine.animaru import parse_animaru_url
        return parse_animaru_url(value)
    if site == 'tvwiki':
        from app.engine.tvwiki import parse_tvwiki_url
        return parse_tvwiki_url(value)
    if site == 'anilife':
        match = re.fullmatch(r'/content/(\d+)(?:/([A-Za-z0-9_-]+|\d+\.\d+))?/?', path)
        if match:
            work, episode = match.groups()
            return dict(site=site, work=work, episode=episode,
                        url=f'https://{parts.hostname}/content/{work}'+(f'/{episode}' if episode else ''), collection=not episode)
    elif site == 'linkani':
        match = re.fullmatch(r'/watch/(\d+)/a(\d+)/k(\d+)/?', path)
        if match:
            work, source, number = match.groups()
            return dict(site=site, work=work, episode=f'a{source}-k{number}',
                        url=f'https://linkani.tv/watch/{work}/a{source}/k{number}/', collection=False)
        match = re.fullmatch(r'/ani/(\d+)/?', path)
        if match:
            return dict(site=site, work=match[1], episode=None, url=f'https://linkani.tv/ani/{match[1]}/', collection=True)
    else:
        new_work = re.fullmatch(r'/c/([^/?#]+)/?', path)
        if new_work:
            slug = unquote(new_work[1]).strip()
            return dict(site=site, work=slug, episode=None,
                        url=f'https://{parts.netloc.lower()}/c/{quote(slug)}', collection=True)
        new_ep = re.fullmatch(r'/e/([^/?#]+)/?', path)
        if new_ep:
            slug = unquote(new_ep[1]).strip()
            return dict(site=site, work=slug, episode=slug,
                        url=f'https://{parts.netloc.lower()}/e/{quote(slug)}', collection=False)
        match = re.fullmatch(r'/(\d+)/[^/]+\.html', path)
        if not match and (parts.query or parts.fragment) and re.search(r'\.html(?:[?#].*)?$', value):
            # 사이트가 제목의 물음표를 인코딩하지 않은 링크도 ID로 정상 페이지에 연결한다.
            match = re.fullmatch(r'/(\d+)/[^/]+', path)
            if match:
                return dict(site=site, work=match[1], episode=None,
                            url=f'https://{parts.netloc.lower()}/{match[1]}/index.html', collection=True)
        if match:
            return dict(site=site, work=match[1], episode=None,
                        url=urlunsplit(('https', parts.netloc.lower(), path, '', '')), collection=True)
    raise EpisodeSiteError('올바른 작품 또는 회차 주소를 입력하세요.')


@dataclass
class Node:
    tag: str = ''
    attrs: dict = field(default_factory=dict)
    parent: Node | None = None
    children: list = field(default_factory=list)

    @property
    def text(self):
        return ''.join(child if isinstance(child, str) else child.text for child in self.children)

    def find(self, tag=None, cls=None, **attrs):
        result = []
        for child in self.children:
            if not isinstance(child, Node):
                continue
            if ((tag is None or child.tag == tag) and (not cls or cls in child.attrs.get('class', '').split())
                    and all(k in child.attrs and (v is None or child.attrs[k] == v) for k, v in attrs.items())):
                result.append(child)
            result.extend(child.find(tag, cls, **attrs))
        return result


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node()
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.current)
        self.current.children.append(node)
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.current = node

    def handle_endtag(self, tag):
        node = self.current
        while node.parent:
            if node.tag == tag:
                self.current = node.parent
                break
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


class SiteClient:
    """다른 사이트의 쿠키를 빌리지 않고 리다이렉트마다 허용 호스트를 재확인한다."""
    def __init__(self):
        self.http = httpx.Client(timeout=15, follow_redirects=False, headers={'User-Agent': USER_AGENT})

    def close(self): self.http.close()

    def request(self, url, domains, *, referer=None, form=None, json_body=None, subdomains=False, headers=None, binary=False, prefix_bytes=None):
        from app.engine.tls_compat import enable_tls_compat, is_connection_reset
        if prefix_bytes is not None and (not binary or type(prefix_bytes) is not int or not 1 <= prefix_bytes <= 65536):
            raise ValueError('Invalid binary probe size')
        method = 'POST' if form is not None or json_body is not None else 'GET'
        origin = urlsplit(url).netloc
        redirects, retried_hosts = 0, set()
        while redirects < 6:
            url = checked_url(url, domains, subdomains=subdomains)
            host = urlsplit(url).hostname
            request_headers = {'Referer': str(httpx.URL(referer or url)), 'Accept': 'text/html,application/json,application/vnd.apple.mpegurl'}
            if method == 'POST': request_headers['X-Requested-With'] = 'XMLHttpRequest'
            # 재생 증명 헤더는 발급받은 API 호스트에서만 쓰고 CDN 이동에는 넘기지 않는다.
            if urlsplit(url).netloc == origin: request_headers.update(headers or {})
            try:
                body_args = {'json': json_body} if json_body is not None else {'data': form}
                with self.http.stream(method, url, headers=request_headers, **body_args) as response:
                    if response.headers.get('x-amzn-waf-action') in ('challenge', 'captcha') or response.headers.get('cf-mitigated') == 'challenge':
                        guidance = '브라우저에서 접속 상태와 인증 설정을 확인하세요.'
                        raise EpisodeSiteError('사이트 접속 확인이 필요합니다. '+guidance+' (HTTP '+str(response.status_code)+')', status=response.status_code)
                    if response.status_code in (301,302,303,307,308):
                        redirects += 1
                        url = urljoin(url, response.headers.get('location', ''))
                        if response.status_code == 303 or response.status_code in (301,302) and method == 'POST':
                            method, form, json_body = 'GET', None, None
                        continue
                    if response.status_code in (401,403):
                        raise EpisodeSiteError('사이트가 이 서버의 접근을 거부했습니다. 브라우저에서 접속 상태를 확인하세요. (HTTP '+str(response.status_code)+')', status=response.status_code)
                    if response.status_code == 404: raise EpisodeSiteError('작품 또는 회차를 찾을 수 없습니다. (HTTP 404)')
                    if response.status_code == 429: raise EpisodeSiteError('사이트 요청 한도에 도달했습니다. 잠시 후 다시 시도하세요. (HTTP 429)')
                    response.raise_for_status()
                    data = bytearray()
                    for chunk in response.iter_bytes(chunk_size=prefix_bytes or 65536):
                        data.extend(chunk[:max(0, prefix_bytes-len(data))] if prefix_bytes is not None else chunk)
                        if prefix_bytes is not None and len(data) >= prefix_bytes: break
                        if len(data) > 3*1024*1024: raise EpisodeSiteError('사이트 응답 크기가 너무 큽니다.')
                    if response.status_code == 202 and not data:
                        raise EpisodeSiteError('사이트 접속 확인이 필요합니다. 브라우저에서 접속 상태와 인증 설정을 확인하세요. (HTTP 202)', status=202)
                    return str(response.url), bytes(data) if binary else bytes(data).decode('utf-8-sig')
            except httpx.ConnectError as error:
                host = urlsplit(url).hostname
                # HTTP 전송 전에 끊긴 TLS 연결만 한 번 재시도하므로 POST를 중복 실행하지 않는다.
                if host not in retried_hosts and is_connection_reset(error) and enable_tls_compat(self.http, host):
                    retried_hosts.add(host)
                    continue
                raise EpisodeSiteError('사이트 HTTPS 연결을 확인할 수 없습니다. 접속 회선을 확인하세요.') from None
            except (httpx.HTTPError, UnicodeError):
                raise EpisodeSiteError('사이트 연결 또는 응답을 확인할 수 없습니다. 잠시 후 다시 시도하세요.') from None
        raise EpisodeSiteError('사이트 주소 이동이 너무 많습니다.')

    def json(self, url, domains, **kwargs):
        final, text = self.request(url, domains, **kwargs)
        try: return final, json.loads(text)
        except ValueError: raise EpisodeSiteError('사이트 응답이 정상 JSON 형식이 아닙니다.') from None


def _title(nodes):
    if not nodes or not nodes[0].text.strip(): raise EpisodeSiteError('작품 제목을 확인할 수 없습니다.')
    return nodes[0].text.strip()


def _rows(rows):
    if not rows or len(rows) > 10000: raise EpisodeSiteError('작품의 회차 목록을 확인할 수 없습니다.')
    if len({row['id'] for row in rows}) != len(rows): raise EpisodeSiteError('중복된 회차 ID가 있습니다.')
    return sorted(rows, key=lambda r:(r.get('number') is None, r.get('number') or 0, r['id']))


def _ohli_parent(doc, address):
    parents = [link for crumb in doc.find('ul', cls='page-breadcrumb') for link in crumb.find('a', href=None)
               if link.parent and link.parent.tag == 'span']
    if len(parents) != 1: raise EpisodeSiteError('회차가 속한 작품을 확인할 수 없습니다.')
    return parse_episode_url(urljoin(address, parents[0].attrs['href'])), parents[0].text.strip()


def load_catalog(url, client=None):
    own = client is None
    client = client or SiteClient()
    try: return _load_catalog(parse_episode_url(url), client)
    finally:
        if own: client.close()


def _load_catalog(route, client):
    if route['site'] == 'ohli365':
        from app.engine.ohli365 import load_ohli365_catalog
        return load_ohli365_catalog(route, client)
    if route['site'] == 'animaru':
        from app.engine.animaru import load_animaru_catalog
        return load_animaru_catalog(route, client)
    if route['site'] == 'tvwiki':
        from app.engine.tvwiki import load_tvwiki_catalog
        return load_tvwiki_catalog(route, client)
    site, work, selected = route['site'], route['work'], route['episode']
    hosts = SITES[site]['hosts']
    rows = []
    incomplete = False
    if site == 'anilife':
        final, _ = client.request(route['url'], hosts)
        target = parse_episode_url(final)
        if target['site'] != site or target['work'] != work: raise EpisodeSiteError('이동된 작품 ID가 다릅니다.')
        route = target
        origin = 'https://'+urlsplit(final).hostname
        hosts = (urlsplit(final).hostname,)
        _, payload = client.json(origin+'/api/anime/'+work, hosts, referer=final)
        item = payload.get('item') if isinstance(payload, dict) else None
        if not isinstance(item, dict) or str(item.get('id')) != work or not isinstance(item.get('title'), str):
            raise EpisodeSiteError('작품 API의 식별 정보가 다릅니다.')
        title = item['title'].strip()
        for episode in item.get('episodes') or []:
            key = str(episode.get('key') or '')
            if not re.fullmatch(r'[A-Za-z0-9_-]+', key): raise EpisodeSiteError('회차 ID가 올바르지 않습니다.')
            if not selected or key == selected or _number(selected) is not None and _number(episode.get('number')) == _number(selected):
                if episode.get('playbackUrl') != f'/api/playback/{work}/{key}': raise EpisodeSiteError('회차 재생 API가 다릅니다.')
                rows.append(dict(id=key, title=str(episode.get('title') or '').strip(), number=_number(episode.get('number')),
                    url=f'{origin}/content/{work}/{key}', available=episode.get('playable') is not False,
                    source_type=episode.get('sourceType')))
    elif site == 'linkani':
        address = f'https://linkani.tv/ani/{work}/'
        final, body = client.request(address, hosts, referer=route['url'])
        if parse_episode_url(final)['work'] != work: raise EpisodeSiteError('이동된 작품 ID가 다릅니다.')
        doc = Document(body).root
        title = _title(doc.find('h1', cls='detail-info-title'))
        seen = set()
        for node in doc.find('a', cls='ep', href=None):
            episode = parse_episode_url(urljoin(final, node.attrs['href']))
            if episode['work'] != work or not episode['episode']: raise EpisodeSiteError('다른 작품의 회차가 포함되어 있습니다.')
            key = episode['episode']
            if (not selected or selected == key) and key not in seen:
                seen.add(key)
                number = int(key.split('-k')[1])
                rows.append(dict(id=key, title=node.text.strip() or f'{number}화', number=number, url=episode['url'], available=True))
        rows = _rows(rows)
        # 사이트가 이전 회차를 목록에서 빼도 확인된 회차는 선택할 수 있게 한다.
        incomplete = not selected and [row['number'] for row in rows] != list(range(1,len(rows)+1))
    else:
        final, body = client.request(route['url'], hosts)
        if '/c/' in final or '/e/' in final or urlsplit(final).hostname in ('ani.ohli24.com', 'ohli24.com'):
            scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', body)
            inertia = next((json.loads(s.strip()) for s in scripts if s.strip().startswith('{"component":') and '"props":' in s), None)
            if not inertia or not isinstance(inertia.get('props'), dict):
                raise EpisodeSiteError('애니24 작품 데이터를 확인할 수 없습니다.')
            props = inertia['props']
            comic = props.get('comic') or {}
            title = (comic.get('title') or '').strip()
            work = str(comic.get('id') or work)
            ep_list = props.get('episodes', {}).get('data', [])
            netloc = urlsplit(final).netloc.lower()
            rows = []
            for ep in ep_list:
                ep_title = (ep.get('title') or '').strip()
                slug = ep.get('slug') or ep_title
                num_m = re.search(r'(\d+(?:\.\d+)?)화', ep_title)
                ep_url = f"https://{netloc}/e/{quote(slug)}"
                has_video = bool(ep.get('body', {}).get('url'))
                rows.append(dict(id=str(ep.get('id')), title=ep_title, url=ep_url,
                                 number=float(num_m[1]) if num_m else None, available=has_video))
            if selected:
                rows = [r for r in rows if unquote(selected) in (r['title'], unquote(urlsplit(r['url']).path.removeprefix('/e/')))]
                if not rows:
                    playing = props.get('playing') or {}
                    p_title = (playing.get('title') or '').strip()
                    p_slug = playing.get('slug') or p_title
                    if p_title:
                        num_m = re.search(r'(\d+(?:\.\d+)?)화', p_title)
                        has_video = bool(playing.get('body', {}).get('url'))
                        rows = [dict(id=str(playing.get('content_id') or '1'), title=p_title,
                                     url=f"https://{netloc}/e/{quote(p_slug)}",
                                     number=float(num_m[1]) if num_m else None, available=has_video)]
            incomplete = False
        else:
            if parse_episode_url(final)['work'] != work: raise EpisodeSiteError('이동된 작품·회차 ID가 다릅니다.')
            doc = Document(body).root
            title = _title(doc.find('h2'))
            players = doc.find('iframe', id='video', src=None)
            if len(players) == 1:
                parent, title_work = _ohli_parent(doc, final)
                rows = [dict(id=work, title=title, url=final, number=None, available=True)]
                work, title = parent['work'], title_work
            else:
                for container in doc.find(cls='eps-item'):
                    for node in container.find('a', href=None):
                        episode = parse_episode_url(urljoin(final,node.attrs['href']))
                        number = re.search(r'(\d+(?:\.\d+)?)화', node.text)
                        rows.append(dict(id=episode['work'], title=node.text.strip(), url=episode['url'],
                                         number=float(number[1]) if number else None, available=True))
                incomplete = False
    rows = _rows(rows)
    if not title or any(not row['title'] for row in rows): raise EpisodeSiteError('작품·회차 제목이 비어 있습니다.')
    return dict(source=site, id=work, title=title, url=route['url'], episodes=rows, incomplete=incomplete)


def _number(value):
    try:
        number = float(value)
        return number if 0 <= number < 1000000 else None
    except (ValueError,TypeError): return None


def _key_attributes(line):
    if len(line)>8192: raise EpisodeSiteError('영상 키 속성이 너무 깁니다.')
    text = line.partition(':')[2]
    pairs, quoted = {}, set()
    while text:
        match = re.match(r'([A-Z][A-Z0-9-]*)=(?:"([^"\x00-\x1f]+)"|([^,\s"\x00-\x1f]+))(,|$)', text)
        if not match or match[1] in pairs: raise EpisodeSiteError('영상 키 속성이 잘못되었거나 중복되었습니다.')
        pairs[match[1]] = match[2] if match[2] is not None else match[3]
        if match[2] is not None: quoted.add(match[1])
        text = text[match.end():]
        if match[4] and not text: raise EpisodeSiteError('영상 키 속성이 잘렸습니다.')
    if set(pairs)-{'METHOD','URI','IV','KEYFORMAT','KEYFORMATVERSIONS'} or 'METHOD' in quoted:
        raise EpisodeSiteError('지원하지 않는 영상 키 속성입니다.')
    if pairs.get('METHOD') == 'NONE' and set(pairs)=={'METHOD'}: return
    if (pairs.get('METHOD')!='AES-128' or 'URI' not in quoted
            or 'KEYFORMAT' in pairs and ('KEYFORMAT' not in quoted or pairs['KEYFORMAT']!='identity')
            or 'KEYFORMATVERSIONS' in pairs and ('KEYFORMATVERSIONS' not in quoted or pairs['KEYFORMATVERSIONS']!='1')
            or 'IV' in pairs and ('IV' in quoted or not re.fullmatch(r'0[xX][0-9a-fA-F]{32}',pairs['IV']))):
        raise EpisodeSiteError('보호된 영상 또는 지원하지 않는 영상 키 형식입니다.')


def validate_hls(client, url, referer, domains, depth=0, visited=None, *, headers=None):
    visited = visited if visited is not None else set()
    if depth >= 4 or len(visited) >= 128 or url in visited: raise EpisodeSiteError('재생목록 구조가 너무 깊거나 반복됩니다.')
    visited.add(url)
    final, body = client.request(url, domains, referer=referer, subdomains=True, **({'headers':headers} if headers else {}))
    if not body.lstrip().startswith('#EXTM3U'): raise EpisodeSiteError('정상 HLS 재생목록이 아닙니다.')
    # Ad markers are playlist tags, not arbitrary substrings of segment names.
    # SAMPLE-AES and other protected key methods are checked by _key_attributes.
    if re.search(r'^\s*#(?:EXT-X-(?:CUE|DATERANGE|SESSION-KEY)\b|(?:EXT(?:-X|-OATCLS)?-)?SCTE-?35\b|(?:EXT-X-)?(?:VAST|INTERSTITIAL)\b)',body,re.I|re.M):
        raise EpisodeSiteError('광고 구간 또는 보호된 재생목록은 지원하지 않습니다.')
    master = '#EXT-X-STREAM-INF:' in body
    count = 0
    children = set()
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith('#EXT-X-KEY:'): _key_attributes(line)
        refs = re.findall(r'URI="([^"]+)"',line) if line.startswith('#') else [line] if line else []
        for resource in refs:
            child = urljoin(final,resource)
            checked_url(child,domains,subdomains=True)
            if not line.startswith('#'): count += 1
            if master and (not line.startswith('#') or line.startswith('#EXT-X-MEDIA:') and 'TYPE=SUBTITLES' not in line):
                children.add(child)
    if not count or not master and '#EXT-X-ENDLIST' not in body: raise EpisodeSiteError('빈 재생목록이거나 아직 종료되지 않은 영상입니다.')
    for child in sorted(children): validate_hls(client,child,referer,domains,depth+1,visited,headers=headers)
    return final,body


def _assigned(doc, name):
    values = []
    for script in doc.find('script'):
        for match in re.finditer(r'\b'+re.escape(name)+r'\s*=\s*',script.text):
            try: value,_ = json.JSONDecoder().raw_decode(script.text[match.end():].lstrip())
            except ValueError: raise EpisodeSiteError('플레이어 JSON 설정이 잘렸거나 변경되었습니다.') from None
            values.append(value)
    if len(values) != 1 or not isinstance(values[0],dict): raise EpisodeSiteError('회차 플레이어 설정을 확인할 수 없습니다.')
    return values[0]


def extract_episode(url, client=None):
    own = client is None
    client = client or SiteClient()
    try: return _extract_episode(url,client)
    finally:
        if own: client.close()


def _anilife_playback(client, address, work, episode):
    origin = 'https://' + urlsplit(address).hostname
    # A playback proof is valid only on the API host that issued its cookie.
    hosts = (urlsplit(address).hostname,)
    for attempt in range(2):
        _, session = client.json(origin+'/api/playback/session', hosts, referer=address,
                                 form={}, headers={'X-Anilife-Player': '1'})
        if (not isinstance(session, dict) or not isinstance(session.get('token'), str)
                or not re.fullmatch(r'[A-Za-z0-9._~-]{1,4096}', session['token'])
                or isinstance(session.get('expiresAt'), bool) or not isinstance(session.get('expiresAt'), (int, float))
                or not math.isfinite(session['expiresAt']) or session['expiresAt'] <= 0):
            raise EpisodeSiteError('사이트의 재생 세션 발급 응답을 확인할 수 없습니다.')
        try:
            # 사이트의 일반 플레이어와 같은 게스트 세션·HttpOnly 쿠키를 사용한다.
            return client.json(origin+f'/api/playback/{work}/{episode}', hosts, referer=address,
                               headers={'X-Anilife-Playback': session['token'], 'X-Anilife-Delivery': 'source-v1'})[1]
        except EpisodeSiteError as error:
            if error.status != 403 or attempt: raise


def _extract_episode(url,client):
    route = parse_episode_url(url)
    if route['site'] == 'ohli365':
        from app.engine.ohli365 import extract_ohli365_episode
        return extract_ohli365_episode(route, client)
    if route['site'] == 'animaru':
        from app.engine.animaru import extract_animaru_episode
        return extract_animaru_episode(route, client)
    if route['site'] == 'tvwiki':
        from app.engine.tvwiki import extract_tvwiki_episode
        return extract_tvwiki_episode(route, client)
    catalog = load_catalog(url,client)
    if len(catalog['episodes']) != 1 or route['collection'] and route['site'] != 'ohli24':
        raise EpisodeSiteError('작품의 회차 목록에서 내려받을 회차를 선택하세요.')
    episode = catalog['episodes'][0]
    site = route['site']; data = SITES[site]; address = episode['url']
    referer = address; subtitles = []
    if site == 'anilife':
        if not episode['available']: raise EpisodeSiteError('재생 파일이 없는 회차입니다.')
        if episode['source_type'] not in ('anilife','linkkf','tvwiki','reanime'): raise EpisodeSiteError('지원하지 않는 회차 재생 제공자입니다.')
        player = _anilife_playback(client, address, catalog['id'], episode['id'])
        if not isinstance(player,dict) or player.get('is_ad') or player.get('advertisement'): raise EpisodeSiteError('회차 재생 응답을 확인할 수 없습니다.')
        media = player.get('videoUrl')
        if player.get('subtitleUrl'): subtitles.append(('ko',player['subtitleUrl']))
    else:
        final, body = client.request(address,data['hosts'])
        if parse_episode_url(final)['work'] != parse_episode_url(address)['work'] or parse_episode_url(final)['episode'] != route['episode']:
            raise EpisodeSiteError('이동된 회차 ID가 다릅니다.')
        doc = Document(body).root
        if site == 'linkani':
            videos = doc.find('video',id='linktv-video')
            sources = [node for video in videos for node in video.find('source',src=None)]
            if len(sources)==1:
                if sources[0].attrs.get('type') not in ('application/x-mpegURL','application/vnd.apple.mpegurl'): raise EpisodeSiteError('지원하지 않는 재생 형식입니다.')
                media = urljoin(final,sources[0].attrs['src'])
            elif not sources:
                player = _assigned(doc,'player_aaaa')
                source,number = episode['id'][1:].split('-k')
                if (player.get('flag')!='play' or str(player.get('id'))!=catalog['id'] or str(player.get('sid'))!=source
                        or str(player.get('nid'))!=number or player.get('from')!='sub' or player.get('encrypt')!=0):
                    raise EpisodeSiteError('회차 플레이어 식별 정보가 변경되었습니다.')
                if player.get('trysee')!=0 or player.get('points')!=0: raise EpisodeSiteError('미리보기 또는 권한이 필요한 회차는 지원하지 않습니다.')
                media = player.get('actual_url')
                if player.get('is_ad') or player.get('advertisement') or media!=player.get('url'): raise EpisodeSiteError('본편 재생 주소를 확인할 수 없습니다.')
            else: raise EpisodeSiteError('복수의 회차 재생 소스가 있습니다.')
            for video in videos:
                for track in video.find('track',kind='subtitles',src=None):
                    lang = track.attrs.get('srclang','')
                    if not re.fullmatch(r'[A-Za-z0-9-]+',lang): raise EpisodeSiteError('자막 언어를 확인할 수 없습니다.')
                    subtitles.append((lang,urljoin(final,track.attrs['src'])))
        else:
            if '/c/' in final or '/e/' in final or urlsplit(final).hostname in ('ani.ohli24.com', 'ohli24.com'):
                scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', body)
                inertia = next((json.loads(s.strip()) for s in scripts if s.strip().startswith('{"component":') and '"props":' in s), None)
                if not inertia or not isinstance(inertia.get('props'), dict):
                    raise EpisodeSiteError('회차 플레이어 정보를 확인할 수 없습니다.')
                playing = inertia['props'].get('playing') or {}
                body_info = playing.get('body') or {}
                player = body_info.get('url')
                if not player:
                    for ep_item in inertia['props'].get('episodes', {}).get('data', []):
                        if str(ep_item.get('id')) == str(episode['id']) or (ep_item.get('slug') and quote(ep_item['slug']) in address):
                            player = (ep_item.get('body') or {}).get('url')
                            break
                if not player:
                    raise EpisodeSiteError('회차 재생 주소를 확인할 수 없습니다.')
                checked_url(player, data['players'])
                match = re.fullmatch(r'/video/([a-fA-F0-9]{32})', urlsplit(player).path)
                if not match:
                    raise EpisodeSiteError('지원하지 않는 플레이어 경로입니다.')
                player_final, html = client.request(player, data['players'], referer=address)
            else:
                parent,_ = _ohli_parent(doc,final)
                if parent['work']!=catalog['id']: raise EpisodeSiteError('회차의 작품 연결이 변경되었습니다.')
                nodes = doc.find('iframe',id='video',src=None)
                if len(nodes)!=1: raise EpisodeSiteError('회차 플레이어를 확인할 수 없습니다.')
                player = urljoin(final,nodes[0].attrs['src'])
                checked_url(player,data['players'])
                match = re.fullmatch(r'/video/([a-fA-F0-9]{32})',urlsplit(player).path)
                if not match: raise EpisodeSiteError('지원하지 않는 플레이어 경로입니다.')
                player_final,html = client.request(player,data['players'],referer=address)
                if urlsplit(player_final).path != urlsplit(player).path: raise EpisodeSiteError('플레이어 주소가 변경되었습니다.')
            player = player_final
            player_host = urlsplit(player).hostname
            bundles = [urljoin(player,node.attrs['src']) for node in Document(html).root.find('script',src=None)
                       if urlsplit(urljoin(player,node.attrs['src'])).hostname==player_host
                       and urlsplit(urljoin(player,node.attrs['src'])).path=='/player/assets/scripts.php']
            if len(bundles)!=1: raise EpisodeSiteError('플레이어 설정을 확인할 수 없습니다.')
            _,script = client.request(bundles[0],(player_host,),referer=player)
            if '/player/index.php?data=' not in script or '&do=getVideo' not in script: raise EpisodeSiteError('영상 발급 구조가 변경되었습니다.')
            _,payload = client.json('https://'+player_host+'/player/index.php?'+urlencode({'data':match[1],'do':'getVideo'}),
                (player_host,),referer=player,form={'hash':match[1],'r':address})
            if not isinstance(payload,dict) or payload.get('hls') is not True or payload.get('is_ad') not in (None,False) or payload.get('advertisement') not in (None,False):
                raise EpisodeSiteError('회차 HLS 발급 응답을 확인할 수 없습니다.')
            media = payload.get('securedLink')
            checked_url(media,data['players'])
            referer = player
    final,manifest = validate_hls(client,media,referer,data['media'])
    subtitle_info = {}
    for lang,target in subtitles:
        _,text = client.request(target,data['media'],referer=referer,subdomains=True)
        if not text.lstrip().startswith('WEBVTT') or ' --> ' not in text: raise EpisodeSiteError('정상 VTT 자막을 확인할 수 없습니다.')
        subtitle_info.setdefault(lang,[]).append({'ext':'vtt','data':text})
    title = episode['title'] if episode['title'].startswith(catalog['title']) else f'{catalog["title"]} · {episode["title"]}'
    return dict(id=episode['id'],title=title,series=catalog['title'],
                episode=episode['title'],episode_number=episode.get('number'),webpage_url=address,
                uploader=data['name'],url=final,manifest=manifest,subtitles=subtitle_info,
                http_headers={'User-Agent':USER_AGENT,'Referer':referer},is_live=False)
