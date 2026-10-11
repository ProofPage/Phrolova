"""Exercise both real import orders in fresh interpreters."""
import subprocess
import sys
from pathlib import Path
import pytest

@pytest.mark.parametrize("imports", ["import streamlink; import yt_dlp", "import yt_dlp; import streamlink"])
def test_signed_url_parsing_with_both_media_engines(imports):
    code = imports + """
from app.engine.media_http_compat import install_media_http_compat
install_media_http_compat()
from urllib3.util.url import parse_url
from requests import Request
url = 'https://cdn.example/video%2fmix.m3u8?token=a%2fb'
assert parse_url(url).url == url
assert Request('GET', url).prepare().url == url
assert parse_url('https://[fe80::1%25eth0]/video').host
install_media_http_compat()
assert parse_url(url).url == url
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
