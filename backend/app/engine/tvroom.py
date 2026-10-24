"""TVRoom public episode pages and advertised HLS; no JavaScript execution."""
import re
import base64
import json
from urllib.parse import quote, unquote, urljoin, urlsplit

from app.core.http import USER_AGENT
from app.engine.episode_sites import Document, EpisodeSiteError, SITES, checked_url, validate_hls, _rows

CATEGORIES = {"영화", "드라마", "TV예능", "음악프로", "애니", "시사다큐"}


def decode_player_key(body):
    """Decode the public player's base64/permutation envelope, not its scripts."""
    try:
        if len(body) > 4096:
            raise ValueError
        data = json.loads(base64.b64decode(body, validate=True))
        rule = data["rule"]
        sizes, order, noise, count = (rule["segment_sizes"], rule["permutation"],
                                      rule["noise_length"], rule["segments_count"])
        if (type(count) is not int or not 1 <= count <= 16 or type(noise) is not int
                or not 0 <= noise <= 128 or len(sizes) != count or len(order) != count
                or any(type(n) is not int or not 1 <= n <= 16 for n in sizes)
                or any(type(n) is not int for n in order) or sorted(order) != list(range(count))
                or sum(sizes) != 16 or rule["key_length"] != 16):
            raise ValueError
        raw = base64.b64decode(data["encrypted_key"], validate=True)
        if len(raw) != 16 + count * noise:
            raise ValueError
        parts = [None] * count
        offset = 0
        for position in order:
            parts[position] = raw[offset:offset + sizes[position]]
            offset += sizes[position] + noise
        return b"".join(parts)
    except (ValueError, KeyError, TypeError):
        raise EpisodeSiteError("티비룸 영상 키 응답 형식이 변경되었습니다.") from None


def parse_tvroom_url(value):
    value = checked_url(value, SITES["tvroom"]["hosts"])
    parts = urlsplit(value)
    segments = [unquote(s) for s in parts.path.rstrip("/").split("/")[1:]]
    if (len(segments) not in (2, 3) or segments[0] != "video" or segments[1] in CATEGORIES
            or any(len(s) > 512 or not re.fullmatch(r"[^\s/?#\\]+", s) or s in (".", "..") for s in segments[1:])):
        raise EpisodeSiteError("티비룸의 개별 작품 또는 회차 주소를 입력하세요.")
    return dict(site="tvroom", work=segments[1], episode=segments[2] if len(segments) == 3 else None,
                collection=len(segments) == 2,
                url=f"https://{parts.hostname}/" + "/".join(quote(s, safe="-") for s in segments))


def _page(route, client):
    # SiteClient preserves the browser User-Agent and follows only allowed hosts.
    final, body = client.request(route["url"], SITES["tvroom"]["hosts"])
    target = parse_tvroom_url(final)
    if target["work"] != route["work"] or route["episode"] and target["episode"] != route["episode"]:
        raise EpisodeSiteError("이동된 티비룸 작품·회차가 다릅니다.")
    return target, Document(body).root


def _catalog(route, target, doc):
    titles = doc.find("title")
    title = re.sub(r"\s*-\s*티비룸\s*$", "", titles[0].text).strip() if titles else ""
    if not title:
        raise EpisodeSiteError("티비룸 작품 제목을 확인할 수 없습니다.")
    episodes = {}
    for a in doc.find("a", cls="episode-item", href=None):
        ep = parse_tvroom_url(urljoin(target["url"], a.attrs["href"]))
        label = a.text.strip()
        if ep["work"] != route["work"] or not ep["episode"] or not label:
            continue
        if route["episode"] and ep["episode"] != route["episode"]:
            continue
        number = re.search(r"(?:제\s*)?(\d+(?:\.\d+)?)\s*(?:회|화)", label)
        episodes[ep["episode"]] = dict(id=ep["episode"], title=label, url=ep["url"],
                                      number=float(number[1]) if number else None, available=True)
    if not episodes:
        raise EpisodeSiteError("티비룸 회차 목록을 확인할 수 없습니다.")
    return dict(source="tvroom", id=route["work"], title=title, url=route["url"],
                episodes=_rows(list(episodes.values())), incomplete=False)


def load_tvroom_catalog(route, client):
    return _catalog(route, *_page(route, client))


def extract_tvroom_episode(route, client):
    target, doc = _page(route, client)
    catalog = _catalog(route, target, doc)
    if len(catalog["episodes"]) != 1:
        raise EpisodeSiteError("작품의 회차 목록에서 내려받을 회차를 선택하세요.")
    frames = doc.find("iframe", id="view_iframe", src=None)
    if len(frames) != 1:
        raise EpisodeSiteError("티비룸 플레이어를 확인할 수 없습니다.")
    player = checked_url(urljoin(target["url"], frames[0].attrs["src"]), SITES["tvroom"]["players"])
    _, html = client.request(player, SITES["tvroom"]["players"], referer=target["url"])
    nodes = Document(html).root.find(id="player", **{"data-m3u8": None})
    if len(nodes) != 1:
        raise EpisodeSiteError("티비룸 재생목록 주소를 확인할 수 없습니다.")
    media = checked_url(nodes[0].attrs["data-m3u8"], ("player.pongping.top",))
    final, manifest = validate_hls(client, media, player, SITES["tvroom"]["media"])
    keys = set(re.findall(r'^#EXT-X-KEY:[^\r\n]*URI="([^"]+)"', manifest, re.M))
    if len(keys) != 1:
        raise EpisodeSiteError("티비룸 영상 키 구성을 확인할 수 없습니다.")
    key_url = checked_url(urljoin(final, keys.pop()), ("player.pongping.top",))
    _, encoded_key = client.request(key_url, ("player.pongping.top",), referer=player, binary=True)
    key = decode_player_key(encoded_key)
    episode = catalog["episodes"][0]
    return dict(id=route["work"] + "-" + episode["id"], title=catalog["title"],
                series=route["work"], episode=episode["title"], episode_number=episode["number"],
                webpage_url=episode["url"], uploader="티비룸", url=final, manifest=manifest,
                subtitles={}, is_live=False,
                hls_aes={"key": key.hex()},
                http_headers={"User-Agent": USER_AGENT, "Referer": player,
                              "Origin": "https://player-v2.pongping.top"})
