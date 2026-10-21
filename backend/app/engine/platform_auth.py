"""Domain-scoped CIME cookies and public-first authentication fallback."""
from __future__ import annotations

import http.cookiejar
import copy
import os
import re
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Awaitable, TypeVar

from app.core.config import get_settings

DOMAINS = {'cime': ('ci.me',), 'kick': ('kick.com',), 'twitch': ('twitch.tv',), 'tiktok': ('tiktok.com',), 'bilibili': ('bilibili.com',), 'pandalive': ('pandalive.co.kr',), 'popkontv': ('popkontv.com',),
           'chzzk': ('naver.com',), 'youtube': ('youtube.com', 'google.com'), 'hearheart': ('hearheart.com',),
           'animaru': ('animaru1.com', 'storagewebtoon.store'),
           'anilife': ('anilife01.tv', 'anilife02.tv', 'anilife03.tv', 'anilife04.tv', 'anilife05.tv', 'anilife.tv')}
NAMES = {'cime': '씨미', 'kick': '킥', 'twitch': '트위치', 'tiktok': '틱톡', 'bilibili': '빌리빌리', 'pandalive': '팬더티비', 'popkontv': '팝콘티비', 'hearheart': '히어하트', 'animaru': '애니마루', 'anilife': '애니라이프'}
T = TypeVar('T')


class PlatformAuthenticationError(RuntimeError):
    def __init__(self, platform: str, expired: bool = False, permission_denied: bool = False):
        name = NAMES.get(platform, '플랫폼')
        message = (f'{name} 쿠키가 만료되었습니다. 설정에서 쿠키를 갱신하세요.' if expired else
                   f'{name} 콘텐츠의 시청 권한을 확인하세요.' if permission_denied else
                   f'{name} 로그인이 필요합니다. 설정에서 쿠키를 등록하세요.')
        super().__init__(message)


def _source(platform: str) -> Path | None:
    if platform not in DOMAINS:
        raise ValueError('지원하지 않는 인증 플랫폼입니다.')
    value = getattr(get_settings(), f'{platform}_cookie_file', None)
    return Path(value) if value else None


def scoped_cookie_jar(jar: http.cookiejar.CookieJar, platform: str) -> http.cookiejar.MozillaCookieJar:
    """Keep original cookie attributes, but never borrow another service's session."""
    result = http.cookiejar.MozillaCookieJar()
    for cookie in jar:
        domain = cookie.domain.lstrip('.').lower()
        allowed = any(domain == host or domain.endswith('.' + host) for host in DOMAINS[platform])
        if not allowed and platform == 'anilife':
            allowed = bool(re.fullmatch(r'anilife[0-9]*\.tv', domain))
        if allowed:
            result.set_cookie(copy.copy(cookie))
    return result


def read_cookie_jar(path: Path, platform: str, *, include_expired: bool = False) -> http.cookiejar.MozillaCookieJar:
    jar = http.cookiejar.MozillaCookieJar()
    # Netscape exporters use expiry 0 for session cookies.
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    normalized = []
    for line in lines:
        if line.startswith('#HttpOnly_'):
            line = line[len('#HttpOnly_'):]
        fields = line.split('\t')
        if len(fields) == 7 and fields[4] == '0':
            fields[4] = ''
            line = '\t'.join(fields)
        normalized.append(line)
    import io
    jar._really_load(io.StringIO('\n'.join(normalized) + '\n'), str(path), True, include_expired)
    return scoped_cookie_jar(jar, platform)


def platform_cookie_jar(platform: str) -> http.cookiejar.MozillaCookieJar:
    source = _source(platform)
    if not source or not source.is_file():
        return http.cookiejar.MozillaCookieJar()
    try:
        jar = read_cookie_jar(source, platform)
        for cookie in list(jar):
            if cookie.is_expired(time.time() + 30):
                jar.clear(cookie.domain, cookie.path, cookie.name)
        return jar
    except (OSError, ValueError, UnicodeError, http.cookiejar.LoadError):
        return http.cookiejar.MozillaCookieJar()


def chzzk_login_values(jar: http.cookiejar.MozillaCookieJar) -> dict[str, str]:
    """Import only unexpired Naver login cookies valid for both existing API hosts."""
    from http.cookies import SimpleCookie
    pairs = []
    for url in ("https://api.chzzk.naver.com/", "https://comm-api.game.naver.com/"):
        request = urllib.request.Request(url)
        jar.add_cookie_header(request)
        cookies = SimpleCookie()
        cookies.load(request.get_header("Cookie", ""))
        values = {name: cookies[name].value for name in ("NID_AUT", "NID_SES") if name in cookies}
        if len(values) != 2 or any(not value or any(c in value for c in "\r\n;") for value in values.values()):
            raise ValueError("Missing usable Naver login cookies")
        pairs.append(values)
    if pairs[0] != pairs[1]:
        raise ValueError("Conflicting Naver login cookies")
    return pairs[0]


def parse_chzzk_cookie_text(text: str) -> dict[str, str]:
    """텍스트(헤더, 키-값 쌍, Netscape 탭 구분 등)에서 NID_AUT와 NID_SES를 추출한다."""
    import re
    pattern_aut = re.search(r'(?:^|[;\s\t\n,])NID_AUT[\s=:\t]+(?:"([^"\r\n;]+)"|\'([^\'\r\n;]+)\'|([^\r\n;\s\t,]+))', text, re.IGNORECASE)
    pattern_ses = re.search(r'(?:^|[;\s\t\n,])NID_SES[\s=:\t]+(?:"([^"\r\n;]+)"|\'([^\'\r\n;]+)\'|([^\r\n;\s\t,]+))', text, re.IGNORECASE)
    if pattern_aut and pattern_ses:
        aut = (pattern_aut.group(1) or pattern_aut.group(2) or pattern_aut.group(3) or '').strip()
        ses = (pattern_ses.group(1) or pattern_ses.group(2) or pattern_ses.group(3) or '').strip()
        if aut and ses:
            return {'NID_AUT': aut, 'NID_SES': ses}
    if nid_aut_match and nid_ses_match:
        aut = nid_aut_match.group(1).strip('\'"')
        ses = nid_ses_match.group(1).strip('\'"')
        if aut and ses:
            return {'NID_AUT': aut, 'NID_SES': ses}
    raise ValueError('NID_AUT 또는 NID_SES 쿠키를 찾을 수 없습니다.')


def convert_text_to_netscape_cookies(text: str, platform: str) -> str:
    """Cookie 헤더 또는 Netscape 쿠키 텍스트(#HttpOnly_ 포함)를 표준 Netscape 포맷으로 변환한다."""
    lines = text.strip().splitlines()
    has_tabs = any('\t' in line for line in lines)
    if has_tabs:
        # Netscape 형태의 텍스트인 경우 #HttpOnly_ 제거 및 정규화
        out = ['# Netscape HTTP Cookie File', '# http://curl.haxx.se/rfc/cookie_spec.html', '']
        for line in lines:
            clean = line.strip()
            if clean.startswith('#HttpOnly_'):
                clean = clean[len('#HttpOnly_'):]
            if clean.startswith('#') and not clean.startswith('# '):
                continue
            out.append(clean)
        return '\n'.join(out) + '\n'

    # 'Cookie: name=value; name2=value2' 또는 단순 'name=value; name2=value2' 형식 처리
    clean_text = text.strip()
    if clean_text.lower().startswith('cookie:'):
        clean_text = clean_text[7:].strip()

    domain = DOMAINS.get(platform, (f'{platform}.com',))[0]
    cookie_domain = f'.{domain}' if not domain.startswith('.') else domain
    expiry = str(int(time.time()) + 365 * 86400)

    out = ['# Netscape HTTP Cookie File', '# http://curl.haxx.se/rfc/cookie_spec.html', '']
    pairs = [item.strip() for item in clean_text.split(';') if '=' in item]
    for pair in pairs:
        name, value = pair.split('=', 1)
        name = name.strip()
        value = value.strip()
        if name and value:
            out.append(f'{cookie_domain}\tTRUE\t/\tTRUE\t{expiry}\t{name}\t{value}')

    if len(out) <= 3:
        raise ValueError('유효한 쿠키 텍스트를 찾을 수 없습니다.')
    return '\n'.join(out) + '\n'


def extract_platform_from_browser(platform: str, browser_name: str = 'auto') -> str:
    """브라우저에서 특정 플랫폼의 쿠키를 추출하여 Netscape 형식 문자열로 반환한다."""
    import yt_dlp.cookies
    targets = [browser_name.lower()] if browser_name != 'auto' else ['whale', 'chrome', 'edge', 'brave', 'firefox']
    platform_domains = DOMAINS.get(platform, (f'{platform}.com',))
    for b in targets:
        try:
            jar = yt_dlp.cookies.extract_cookies_from_browser(b)
            matched = []
            for cookie in jar:
                cdom = (cookie.domain or '').lstrip('.').lower()
                if any(cdom == d or cdom.endswith('.' + d) for d in platform_domains):
                    matched.append(cookie)
            if matched:
                out = ['# Netscape HTTP Cookie File', '# http://curl.haxx.se/rfc/cookie_spec.html', '']
                for c in matched:
                    domain = c.domain or f'.{platform_domains[0]}'
                    tailmatch = 'TRUE' if domain.startswith('.') else 'FALSE'
                    path = c.path or '/'
                    secure = 'TRUE' if c.secure else 'FALSE'
                    expires = str(c.expires) if c.expires else '0'
                    out.append(f'{domain}\t{tailmatch}\t{path}\t{secure}\t{expires}\t{c.name}\t{c.value}')
                return '\n'.join(out) + '\n'
        except Exception:
            continue
    target_label = browser_name if browser_name != 'auto' else '브라우저'
    name = NAMES.get(platform, platform)
    raise ValueError(f'{target_label}에서 {name} 로그인 쿠키를 찾지 못했습니다. 해당 브라우저에서 먼저 로그인해 주세요.')


def extract_chzzk_from_browser(browser_name: str = 'auto') -> dict[str, str]:
    """설치된 브라우저에서 네이버 로그인 쿠키를 추출한다."""
    import yt_dlp.cookies
    targets = [browser_name.lower()] if browser_name != 'auto' else ['whale', 'chrome', 'edge', 'brave', 'firefox']
    for b in targets:
        try:
            jar = yt_dlp.cookies.extract_cookies_from_browser(b)
            found = {}
            for cookie in jar:
                if 'naver.com' in (cookie.domain or '') and cookie.name in ('NID_AUT', 'NID_SES'):
                    found[cookie.name] = cookie.value
            if len(found) == 2 and found.get('NID_AUT') and found.get('NID_SES'):
                return found
        except Exception:
            continue
    target_label = browser_name if browser_name != 'auto' else '브라우저'
    raise ValueError(f'{target_label}에서 네이버 로그인 쿠키(NID_AUT, NID_SES)를 찾지 못했습니다. 해당 브라우저에서 네이버에 먼저 로그인해 주세요.')


def get_platform_cookies(platform: str, request_url: str) -> dict[str, str]:
    from http.cookies import SimpleCookie
    jar = platform_cookie_jar(platform)
    request = urllib.request.Request(request_url)
    jar.add_cookie_header(request)
    cookies = SimpleCookie()
    cookies.load(request.get_header('Cookie', ''))
    return {name: value.value for name, value in cookies.items()}


def platform_cookie_status(platform: str) -> dict:
    source = _source(platform)
    return cookie_file_status(source, platform)


def cookie_file_status(source: Path | None, platform: str) -> dict:
    """Inspect a scoped cookie file without returning credentials or contacting a service."""
    configured = bool(source and source.is_file())
    if not configured:
        return {'configured': False, 'valid': False, 'expired': False, 'message': '쿠키가 등록되지 않았습니다.'}
    try:
        all_cookies = read_cookie_jar(source, platform, include_expired=True)
        valid = any(not cookie.is_expired(time.time() + 30) for cookie in all_cookies)
        expired = bool(len(all_cookies)) and not valid
        
        # 세션 키 존재 여부 확인
        SESSION_KEYS = {
            'youtube': ('SID', '__Secure-1PSID', 'HSID', 'SSID'),
            'twitch': ('auth-token', 'login'),
            'kick': ('session_token', 'kick_session'),
            'tiktok': ('sessionid', 'sessionid_ss'),
            'bilibili': ('SESSDATA', 'bili_jct'),
            'pandalive': ('sess_key', 'user_id', 'p_idx'),
            'popkontv': ('login_id', 'user_code', 'member_no'),
        }
        req_keys = SESSION_KEYS.get(platform)
        has_login_session = True
        if req_keys and valid:
            cookie_names = {c.name for c in all_cookies if not c.is_expired(time.time() + 30)}
            has_login_session = any(k in cookie_names for k in req_keys)

        if valid and not has_login_session:
            return {
                'configured': True, 'valid': False, 'expired': False,
                'message': '로그인 세션이 없는 쿠키 파일입니다. 해당 사이트 로그인 후 쿠키를 다시 등록하세요.'
            }

        return {'configured': True, 'valid': valid, 'expired': expired,
                'message': '쿠키가 만료되었습니다. 다시 등록하세요.' if expired else '로그인 세션이 확인되었습니다.' if valid else '사용 가능한 쿠키가 없습니다.'}
    except (OSError, ValueError, UnicodeError, http.cookiejar.LoadError):
        return {'configured': True, 'valid': False, 'expired': False, 'message': '쿠키 파일을 읽지 못했습니다.'}


@contextmanager
def platform_cookie_file(platform: str):
    jar = platform_cookie_jar(platform)
    if not len(jar):
        yield None
        return
    fd, filename = tempfile.mkstemp(prefix=f'phrolova_{platform}_', suffix='.txt')
    os.close(fd)
    try:
        jar.save(filename, ignore_discard=True)
        yield filename
    finally:
        Path(filename).unlink(missing_ok=True)


def authentication_required(error: Exception) -> bool:
    text = str(error).lower()
    return isinstance(error, PlatformAuthenticationError) or bool(re.search(
        r'http(?: error)?[ :]*(?:401|403)|로그인|시청 권한|인증이 필요|login|sign.?in|authentication|access.denied|subscriber', text))


async def with_platform_cookie_fallback(platform: str, operation: Callable[[str | None], Awaitable[T]]) -> T:
    try:
        return await operation(None)
    except Exception as error:
        if not authentication_required(error):
            raise
    status = platform_cookie_status(platform)
    with platform_cookie_file(platform) as cookie_file:
        if not cookie_file:
            raise PlatformAuthenticationError(platform, expired=status['expired']) from None
        try:
            return await operation(cookie_file)
        except Exception as error:
            if authentication_required(error):
                raise PlatformAuthenticationError(platform, permission_denied=True) from None
            raise


def redact_media_error(error: object, *, max_length: int = 1000) -> str:
    text = re.sub(r'https?://[^\s\]\)\"\']+', '[영상 주소]', str(error))
    text = re.sub(r'(?i)(\b(?:url|uri):\s*)/[^\s)]+', r'\1[영상 경로]', text)
    text = re.sub(r'(?i)(cookie|authorization|\bauth\b|token|sessionid(?:_ss)?|sid_tt|sid_guard|ttwid)\s*[:=]\s*[^\r\n]+', r'\1=[비공개]', text)
    return text[:max_length]
