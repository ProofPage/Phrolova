"""Platform classification and extractors for the existing VOD queue."""
from urllib.parse import urlsplit
from app.engine.platform_auth import redact_media_error

def media_platform(url: str) -> str:
    host = (urlsplit(url).hostname or '').lower()
    if host in ('ci.me', 'www.ci.me'): return 'cime'
    if host in ('vod.sooplive.com', 'vod.sooplive.co.kr', 'vod.afreecatv.com'): return 'soop'
    if host == 'chzzk.naver.com': return 'chzzk'
    if host in ('youtu.be', 'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'): return 'youtube'
    return 'external'

def canonical_platform_video(url: str) -> str:
    platform = media_platform(url)
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
    def warning(self, message): self.logger.warning(redact_media_error(message))
    def error(self, message): self.logger.error(redact_media_error(message))

def platform_ydl(url: str, options: dict):
    import yt_dlp
    opts = dict(options)
    if media_platform(url) in ('soop', 'cime') and opts.get('logger'):
        opts['logger'] = SafeMediaLogger(opts['logger'])
    if media_platform(url) == 'cime':
        from app.engine.cime_extractor import CimeIE
        ydl = yt_dlp.YoutubeDL(opts, auto_init=False)
        ydl.add_info_extractor(CimeIE())
        ydl.add_default_info_extractors()
        return ydl
    return yt_dlp.YoutubeDL(opts)
