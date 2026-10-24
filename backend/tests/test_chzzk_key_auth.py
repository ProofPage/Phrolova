"""Live AES keys receive credentials only on the official HTTPS API origin."""

import contextlib
import io
from types import SimpleNamespace

import pytest

from tests.test_chzzk_recording_isolation import writer
from tests.test_chzzk_continuity import CDN


@pytest.mark.parametrize("url,authenticated", [
    ("https://api.chzzk.naver.com/service/v1/encryption/live/1/aes_key", True),
    ("https://api.chzzk.naver.com/service/v1/encryption/videos/1/aes_key", True),
    ("http://api.chzzk.naver.com/service/v1/encryption/live/1/aes_key", False),
    ("https://api.chzzk.naver.com.evil.test/key", False),
    ("https://resources-rmcnmv.akamaized.net/key", False),
    ("https://user:password@api.chzzk.naver.com/key", False),
    ("https://api.chzzk.naver.com:444/key", False),
])
def test_live_key_cookie_is_origin_scoped(monkeypatch, url, authenticated):
    with contextlib.ExitStack() as stack:
        cdn = stack.enter_context(CDN())
        cdn.playlist("primary")
        reader, source = writer(stack, cdn)
        reader.stream.api_cookie = "NID_AUT=fixture-account"
        seen = []
        key = b"fixture-key-1234"

        class Body(io.BytesIO):
            def read1(self, size, decode_content=True):
                return super().read1(size)

        def response(address, **kwargs):
            seen.append(kwargs["headers"])
            return contextlib.nullcontext(SimpleNamespace(
                raw=Body(key), headers={"Content-Length": str(len(key))},
                status_code=200,
            ))

        monkeypatch.setattr(source.session.http, "get", response)
        assert reader.writer.http_bytes(url) == key
        assert ("Cookie" in seen[0]) is authenticated
