"""Platform classification and extractors for the existing VOD queue."""
from urllib.parse import urlsplit
from app.core.episode_domains import numbered_site_for_host
from app.engine.platform_auth import redact_media_error

def media_platform(url: str) -> str:
    host = (urlsplit(url).hostname or '').lower()
    numbered = numbered_site_for_host(host)
    if numbered: return numbered
    if host == 'v2.ohli365.org': return 'ohli365'
    if host == 'linkani.tv': return 'linkani'
    if host in ('www.ohli24.net', 'ohli24.net'): return 'ohli24'
    if host in ('bilibili.com', 'www.bilibili.com', 'm.bilibili.com', 'live.bilibili.com', 'b23.tv'): return 'bilibili'
    if host in ('tiktok.com', 'www.tiktok.com', 'm.tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com'): return 'tiktok'
    if host in ('twitch.tv', 'www.twitch.tv', 'm.twitch.tv', 'go.twitch.tv', 'clips.twitch.tv', 'player.twitch.tv'): return 'twitch'
    if host in ('kick.com', 'www.kick.com'): return 'kick'
    if host in ('ci.me', 'www.ci.me'): return 'cime'
    if host in ('vod.sooplive.com', 'vod.sooplive.co.kr', 'vod.afreecatv.com'): return 'soop'
    if host == 'chzzk.naver.com': return 'chzzk'
    if host in ('youtu.be', 'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'): return 'youtube'
    return 'external'

def canonical_platform_video(url: str) -> str:
    platform = media_platform(url)
    if platform in ('anilife', 'linkani', 'ohli24', 'tvwiki', 'tvchak', 'animaru', 'ohli365'):
        from app.engine.episode_sites import parse_episode_url
        route = parse_episode_url(url)
        if route['collection'] and platform != 'ohli24':
            raise ValueError('작품의 회차 목록에서 내려받을 회차를 선택하세요.')
        return route['url']
    if platform == 'bilibili':
        from app.engine.bilibili import canonical_bilibili_video_url
        return canonical_bilibili_video_url(url)
    if platform == 'tiktok':
        from app.engine.tiktok import canonical_tiktok_video_url
        return canonical_tiktok_video_url(url)
    if platform == 'twitch':
        from app.engine.twitch import canonical_twitch_video_url
        return canonical_twitch_video_url(url)
    if platform == 'kick':
        from app.engine.kick import canonical_kick_video_url
        return canonical_kick_video_url(url)
    if platform == 'soop':
        from app.engine.soop import normalize_soop_vod_url
        return normalize_soop_vod_url(url)
    if platform == 'cime':
        from app.engine.cime import parse_cime_video_url
        route = parse_cime_video_url(url)
        if not route: raise ValueError('올바른 씨미 다시보기 또는 클립 링크를 입력하세요.')
        return route['url']
    return url

class SafeMediaLogger:
    def __init__(self, logger): self.logger = logger
    def debug(self, message): self.logger.debug(redact_media_error(message))
    def info(self, message): self.logger.info(redact_media_error(message))
    def warning(self, message):
        # 일반 추출기 전환과 BunnyCDN의 선택 메타데이터 누락은 실패 경고가 아니다.
        text = str(message).strip()
        if text == '[generic] Falling back on generic information extractor':
            self.logger.info('[generic] 전용 추출기가 없어 일반 추출기로 미디어를 확인합니다.')
        elif text.partition(';')[0].strip() == '[BunnyCdn] unable to extract JSON-LD':
            self.logger.info('[BunnyCdn] 부가 메타데이터(JSON-LD)를 찾지 못했습니다. 미디어 추출을 계속합니다.')
        else:
            self.logger.warning(redact_media_error(message))
    def error(self, message): self.logger.error(redact_media_error(message))

def platform_ydl(url: str, options: dict):
    import yt_dlp
    opts = dict(options)
    if opts.get('logger'):
        opts['logger'] = SafeMediaLogger(opts['logger'])
    if media_platform(url) in ('anilife', 'linkani', 'ohli24', 'tvwiki', 'tvchak', 'animaru', 'ohli365'):
        from app.engine.episode_extractor import EpisodeSiteIE
        if media_platform(url) == 'tvwiki':
            from app.engine.tvwiki_downloader import TVWikiYoutubeDL
            ydl = TVWikiYoutubeDL(opts, auto_init=False)
        else:
            ydl = yt_dlp.YoutubeDL(opts, auto_init=False)
        ydl.add_info_extractor(EpisodeSiteIE())
        ydl.add_default_info_extractors()
        return ydl
    if media_platform(url) == 'cime':
        from app.engine.cime_extractor import CimeIE
        ydl = yt_dlp.YoutubeDL(opts, auto_init=False)
        ydl.add_info_extractor(CimeIE())
        ydl.add_default_info_extractors()
        return ydl
    return yt_dlp.YoutubeDL(opts)
