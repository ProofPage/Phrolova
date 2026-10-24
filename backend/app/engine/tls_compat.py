"""인증서 검증을 유지하면서 TLS ClientHello의 레코드 경계를 조정한다."""
from __future__ import annotations

import errno
import ssl
import time

import httpcore
import httpx


def split_client_hello(data: bytes, hostname: str) -> bytes:
    """일부 회선이 한 레코드 안의 SNI를 보고 연결을 끊는 경우에만 사용한다."""
    name = hostname.encode('idna')
    output = bytearray()
    offset = 0
    while offset + 5 <= len(data):
        size = int.from_bytes(data[offset + 3:offset + 5], 'big')
        end = offset + 5 + size
        if end > len(data):
            break
        header, payload = data[offset:offset + 3], data[offset + 5:end]
        position = payload.find(name)
        if header[0] == 22 and payload[:1] == b'\x01' and position >= 0 and len(name) > 1:
            split = position + len(name) // 2
            output.extend(header + split.to_bytes(2, 'big') + payload[:split])
            output.extend(header + (size - split).to_bytes(2, 'big') + payload[split:])
        else:
            output.extend(data[offset:end])
        offset = end
    output.extend(data[offset:])
    return bytes(output)


class _TLSStream(httpcore.NetworkStream):
    def __init__(self, stream, context, hostname, timeout):
        self.stream = stream
        self.incoming, self.outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        self.tls = context.wrap_bio(self.incoming, self.outgoing, server_side=False, server_hostname=hostname)
        self.hostname = hostname
        self.eof = False
        deadline = None if timeout is None else time.monotonic() + timeout
        try:
            while True:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise httpcore.ConnectTimeout('TLS handshake timed out')
                try:
                    self.tls.do_handshake()
                    self._flush(remaining)
                    break
                except ssl.SSLWantReadError:
                    self._flush(remaining)
                    self._receive(remaining)
        except Exception as error:
            stream.close()
            if isinstance(error, httpcore.TimeoutException):
                raise httpcore.ConnectTimeout(str(error)) from error
            if isinstance(error, (OSError, httpcore.NetworkError)):
                raise httpcore.ConnectError(str(error)) from error
            raise

    def _flush(self, timeout):
        data = self.outgoing.read()
        if data:
            self.stream.write(split_client_hello(data, self.hostname), timeout=timeout)

    def _receive(self, timeout):
        data = self.stream.read(65536, timeout=timeout)
        if data:
            self.incoming.write(data)
        elif not self.eof:
            self.eof = True
            self.incoming.write_eof()

    def read(self, max_bytes, timeout=None):
        try:
            while True:
                try:
                    data = self.tls.read(max_bytes)
                    self._flush(timeout)
                    return data
                except ssl.SSLWantReadError:
                    self._flush(timeout)
                    self._receive(timeout)
        except httpcore.TimeoutException as error:
            raise httpcore.ReadTimeout(str(error)) from error
        except OSError as error:
            raise httpcore.ReadError(str(error)) from error

    def write(self, buffer, timeout=None):
        try:
            while buffer:
                try:
                    size = self.tls.write(buffer)
                    buffer = buffer[size:]
                    self._flush(timeout)
                except ssl.SSLWantReadError:
                    self._flush(timeout)
                    self._receive(timeout)
        except httpcore.TimeoutException as error:
            raise httpcore.WriteTimeout(str(error)) from error
        except OSError as error:
            raise httpcore.WriteError(str(error)) from error

    def close(self):
        self.stream.close()

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return _TLSStream(self, ssl_context, server_hostname, timeout)

    def get_extra_info(self, info):
        if info == 'ssl_object':
            return self.tls
        if info == 'is_readable' and self.tls.pending():
            return True
        return self.stream.get_extra_info(info)


class _ScopedStream(httpcore.NetworkStream):
    def __init__(self, stream, hosts):
        self.stream, self.hosts = stream, hosts

    def read(self, max_bytes, timeout=None):
        return self.stream.read(max_bytes, timeout=timeout)

    def write(self, buffer, timeout=None):
        return self.stream.write(buffer, timeout=timeout)

    def close(self):
        self.stream.close()

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        host = (server_hostname or '').lower()
        if host in self.hosts:
            # HTTPX가 만든 SSLContext를 그대로 써서 CA·호스트명 검증 설정을 보존한다.
            return _TLSStream(self.stream, ssl_context, server_hostname, timeout)
        return _ScopedStream(self.stream.start_tls(ssl_context, server_hostname, timeout), self.hosts)

    def get_extra_info(self, info):
        return self.stream.get_extra_info(info)


class _Backend(httpcore.NetworkBackend):
    def __init__(self, delegate, hosts):
        self.delegate, self.hosts = delegate, hosts

    def connect_tcp(self, *args, **kwargs):
        return _ScopedStream(self.delegate.connect_tcp(*args, **kwargs), self.hosts)

    def connect_unix_socket(self, *args, **kwargs):
        return _ScopedStream(self.delegate.connect_unix_socket(*args, **kwargs), self.hosts)

    def sleep(self, seconds):
        self.delegate.sleep(seconds)


def enable_tls_compat(client: httpx.Client, hostname: str) -> bool:
    """클라이언트의 쿠키·프록시·인증서 설정을 바꾸지 않고 한 호스트에만 적용한다."""
    enabled = False
    # HTTPX의 연결 풀 연결부만 감싸 환경 변수로 설정한 프록시도 그대로 사용한다.
    transports = [getattr(client, '_transport', None), *getattr(client, '_mounts', {}).values()]
    for transport in transports:
        pool = getattr(transport, '_pool', None)
        backend = getattr(pool, '_network_backend', None)
        if backend is None:
            continue
        if isinstance(backend, _Backend):
            backend.hosts.add(hostname.lower())
        else:
            pool._network_backend = _Backend(backend, {hostname.lower()})
        enabled = True
    return enabled


def is_connection_reset(error: BaseException) -> bool:
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, ConnectionResetError) or isinstance(error, OSError) and error.errno in (errno.ECONNRESET, 10054):
            return True
        error = error.__cause__ or error.__context__
    return False
