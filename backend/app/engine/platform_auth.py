"""Domain-scoped SOOP/CIME cookies and public-first authentication fallback."""
from __future__ import annotations

import http.cookiejar
import os
import re
import tempfile
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Awaitable, TypeVar

from app.core.config import get_settings

DOMAINS = {'soop': ('sooplive.com', 'sooplive.co.kr', 'afreecatv.com'), 'cime': ('ci.me',)}
NAMES = {'soop': '숲', 'cime': '씨미'}
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


def read_cookie_jar(path: Path, platform: str, *, include_expired: bool = False) -> http.cookiejar.MozillaCookieJar:
    jar = http.cookiejar.MozillaCookieJar()
    # Netscape exporters use expiry 0 for session cookies.
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    normalized = []
    for line in lines:
        fields = line.split('\t')
        if len(fields) == 7 and fields[4] == '0':
            fields[4] = ''
            line = '\t'.join(fields)
        normalized.append(line)
    import io
    jar._really_load(io.StringIO('\n'.join(normalized) + '\n'), str(path), True, include_expired)
    for cookie in list(jar):
        domain = cookie.domain.lstrip('.').lower()
        if not any(domain == allowed or domain.endswith('.' + allowed) for allowed in DOMAINS[platform]):
            jar.clear(cookie.domain, cookie.path, cookie.name)
    return jar


def platform_cookie_jar(platform: str) -> http.cookiejar.MozillaCookieJar:
    source = _source(platform)
    if not source or not source.is_file():
        return http.cookiejar.MozillaCookieJar()
    try:
        return read_cookie_jar(source, platform)
    except (OSError, ValueError, UnicodeError, http.cookiejar.LoadError):
        return http.cookiejar.MozillaCookieJar()


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
    configured = bool(source and source.is_file())
    if not configured:
        return {'configured': False, 'valid': False, 'expired': False, 'message': '쿠키가 등록되지 않았습니다.'}
    try:
        all_cookies = read_cookie_jar(source, platform, include_expired=True)
        valid = any(not cookie.is_expired() for cookie in all_cookies)
        expired = bool(len(all_cookies)) and not valid
        return {'configured': True, 'valid': valid, 'expired': expired,
                'message': '쿠키가 만료되었습니다.' if expired else '쿠키 파일이 등록되었습니다.' if valid else '사용 가능한 쿠키가 없습니다.'}
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
    text = re.sub(r'(?i)(cookie|authorization|token)\s*[:=]\s*[^\r\n]+', r'\1=[비공개]', text)
    return text[:max_length]
