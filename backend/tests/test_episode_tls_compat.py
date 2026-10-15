"""회선의 TLS 초기 연결 끊김을 복구하되 인증서·요청 경계를 유지하는지 검사한다."""
import errno
import functools
import http.server
from pathlib import Path
import ssl
import threading

import httpcore
import httpx
import pytest

from app.engine import episode_sites as sites
from app.engine import tls_compat as compat


@pytest.fixture
def tls_server():
    received = []
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self):
            received.append((self.command, self.rfile.read(int(self.headers.get('Content-Length', 0)))))
            content = b'fragmented verified HTTPS'
            self.send_response(200)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Set-Cookie', 'guest=local-only; Path=/; Secure; HttpOnly')
            self.end_headers()
            self.wfile.write(content)

        do_POST = do_GET

        def log_message(self, *args):
            pass

    certificates = Path(__file__).parent/'fixtures/tls'
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificates/'localhost.pem', certificates/'localhost-key.pem')
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        server.received = received
        yield server, ssl.create_default_context(cafile=str(certificates/'localhost.pem'))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def records(data):
    output = []
    while len(data) >= 5:
        length = int.from_bytes(data[3:5], 'big')
        output.append((data[:3], data[5:5+length]))
        data = data[5+length:]
    assert not data
    return output


def test_client_hello_record_boundaries_preserve_every_handshake_byte():
    outgoing = ssl.MemoryBIO()
    ssl_object = ssl.create_default_context().wrap_bio(ssl.MemoryBIO(), outgoing, server_hostname='localhost')
    with pytest.raises(ssl.SSLWantReadError):
        ssl_object.do_handshake()
    original = outgoing.read()
    result = compat.split_client_hello(original, 'localhost')
    before, after = records(original), records(result)
    assert len(after) == len(before) + 1
    assert b''.join(payload for _, payload in after) == b''.join(payload for _, payload in before)
    assert all(header == before[0][0] for header, _ in after)
    assert all(b'localhost' not in payload for _, payload in after)


@pytest.mark.parametrize('data', [b'', b'\x16\x03', b'\x16\x03\x01\x00\x10short',
                                      b'\x17\x03\x03\x00\x09localhost'])
def test_incomplete_or_application_records_are_not_modified(data):
    assert compat.split_client_hello(data, 'localhost') == data


def test_real_fragmented_https_keeps_verification_cookies_and_pool_reuse(tls_server):
    server, context = tls_server
    with httpx.Client(verify=context, trust_env=False, timeout=3) as client:
        assert compat.enable_tls_compat(client, 'localhost')
        backend = client._transport._pool._network_backend
        assert compat.enable_tls_compat(client, 'LOCALHOST')
        assert client._transport._pool._network_backend is backend
        for _ in range(3):
            response = client.get(f'https://localhost:{server.server_port}/episode')
            assert response.content == b'fragmented verified HTTPS'
        assert client.cookies.get('guest') == 'local-only'


def test_untrusted_certificate_is_still_rejected(tls_server):
    server, _ = tls_server
    with httpx.Client(trust_env=False, timeout=3) as client:
        compat.enable_tls_compat(client, 'localhost')
        with pytest.raises(httpx.ConnectError, match='CERTIFICATE_VERIFY_FAILED') as caught:
            client.get(f'https://localhost:{server.server_port}/')
        assert not compat.is_connection_reset(caught.value)


def test_hostname_mismatch_is_still_rejected(tls_server):
    server, context = tls_server
    from httpcore._backends.sync import SyncBackend
    stream = SyncBackend().connect_tcp('127.0.0.1', server.server_port, timeout=3)
    with pytest.raises(httpcore.ConnectError, match='CERTIFICATE_VERIFY_FAILED'):
        compat._TLSStream(stream, context, 'wrong.invalid', 3)


def test_site_client_reset_fallback_issues_only_one_real_post(tls_server):
    server, context = tls_server
    from httpcore._backends.sync import SyncBackend
    class ResetStream(httpcore.NetworkStream):
        def start_tls(self, *args, **kwargs):
            try:
                raise ConnectionResetError(errno.ECONNRESET, 'reset')
            except OSError as error:
                raise httpcore.ConnectError('initial reset') from error
        def close(self):
            pass

    class Backend(httpcore.NetworkBackend):
        count = 0
        def connect_tcp(self, *args, **kwargs):
            self.count += 1
            if self.count == 1:
                return ResetStream()
            return SyncBackend().connect_tcp('127.0.0.1', server.server_port, timeout=3)

    original = Backend()
    client = sites.SiteClient(); client.http.close()
    client.http = httpx.Client(verify=context, trust_env=False, timeout=3)
    client.http._transport._pool._network_backend = original
    try:
        response = client.request('https://localhost/api/playback/session', ('localhost',), form={'player':'1'})
        assert response[1] == 'fragmented verified HTTPS'
        assert original.count == 2 and server.received == [('POST', b'player=1')]
        assert client.http.cookies.get('guest') == 'local-only'
    finally:
        client.close()


def test_other_hosts_keep_the_original_tls_transport():
    from unittest.mock import Mock
    original = Mock()
    context = ssl.create_default_context()
    wrapped = compat._ScopedStream(original, {'anilife01.tv'})
    result = wrapped.start_tls(context, 'unrelated.example', 2)
    original.start_tls.assert_called_once_with(context, 'unrelated.example', 2)
    assert isinstance(result, compat._ScopedStream)
    result.close()
    original.start_tls.return_value.close.assert_called_once()


def test_proxy_pools_and_original_backends_are_preserved():
    with httpx.Client(proxy='http://localhost:3128', trust_env=False) as client:
        pool = next(transport._pool for transport in client._mounts.values() if transport is not None)
        original = pool._network_backend
        proxy = pool._proxy_url
        assert compat.enable_tls_compat(client, 'anilife01.tv')
        assert pool._network_backend.delegate is original
        assert pool._proxy_url == proxy
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
        assert not compat.enable_tls_compat(client, 'anilife01.tv')


@pytest.mark.parametrize('kind', ['reset', 'certificate', 'timeout', 'read', 'forbidden'])
def test_site_request_retries_only_one_pre_http_reset(monkeypatch, kind):
    calls, enabled = [], []
    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            if kind == 'reset':
                raise httpx.ConnectError('TLS failed') from ConnectionResetError(errno.ECONNRESET, 'reset')
            if kind == 'certificate':
                raise httpx.ConnectError('TLS failed') from ssl.SSLCertVerificationError('untrusted')
            if kind == 'timeout':
                raise httpx.ConnectTimeout('timeout')
            if kind == 'read':
                raise httpx.ReadError('body failed') from ConnectionResetError(errno.ECONNRESET, 'reset')
            return httpx.Response(403)
        return httpx.Response(200, text='ok')
    monkeypatch.setattr(compat, 'enable_tls_compat', lambda client, host: enabled.append(host) or True)
    client = sites.SiteClient()
    client.http.close()
    client.http = httpx.Client(transport=httpx.MockTransport(handle))
    try:
        request = functools.partial(client.request, 'https://anilife01.tv/api/playback/session',
                                    ('anilife01.tv',), form={}, headers={'X-Anilife-Player':'1'})
        if kind == 'reset':
            assert request()[1] == 'ok'
            assert enabled == ['anilife01.tv'] and len(calls) == 2
            assert all(r.method == 'POST' and r.content == b'' for r in calls)
            assert all(r.headers['X-Anilife-Player'] == '1' for r in calls)
        else:
            with pytest.raises(sites.EpisodeSiteError):
                request()
            assert not enabled and len(calls) == 1
    finally:
        client.close()


def test_reset_retries_are_bounded_and_redirects_still_check_hosts(monkeypatch):
    calls, enabled = [], []
    def handle(request):
        calls.append(request)
        raise httpx.ConnectError('TLS failed') from ConnectionResetError(10054, 'reset')
    monkeypatch.setattr(compat, 'enable_tls_compat', lambda client, host: enabled.append(host) or True)
    client = sites.SiteClient(); client.http.close()
    client.http = httpx.Client(transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(sites.EpisodeSiteError, match='HTTPS'):
            client.request('https://anilife01.tv/', ('anilife01.tv',))
        assert len(calls) == 2 and enabled == ['anilife01.tv']
        calls.clear(); enabled.clear()
        client.http.close()
        def redirect(request):
            calls.append(request)
            return httpx.Response(302, headers={'Location':'https://untrusted.example/'})
        client.http = httpx.Client(transport=httpx.MockTransport(redirect))
        with pytest.raises(sites.EpisodeSiteError, match='호스트'):
            client.request('https://anilife01.tv/', ('anilife01.tv',))
        assert len(calls) == 1 and not enabled
    finally:
        client.close()


def test_exception_chain_with_cycle_does_not_loop():
    first, second = RuntimeError('first'), RuntimeError('second')
    first.__cause__, second.__cause__ = second, first
    assert not compat.is_connection_reset(first)
