"""AV19-only native HLS transport: approve every URL before every redirect."""
from io import BytesIO
import threading

import yt_dlp
from yt_dlp.networking import Request, Response
from yt_dlp.utils import ExtractorError

from app.engine.av19 import MEDIA, decode_key, resource_url
from app.engine.episode_sites import EpisodeSiteError, SiteClient


class AV19YoutubeDL(yt_dlp.YoutubeDL):
    def __init__(self, *args, **kwargs):
        self._av19_delivery = None
        self._av19_keys = {}
        self._av19_lock = threading.Lock()
        super().__init__(*args, **kwargs)

    def configure_av19(self, delivery):
        self._av19_delivery = delivery
        self._av19_keys.clear()

    def urlopen(self, request):
        try:
            if not isinstance(request, Request) or request.method != 'GET' or request.data is not None:
                raise EpisodeSiteError('AV19에서 허용되지 않은 요청입니다.')
            delivery = self._av19_delivery
            if not delivery:
                raise EpisodeSiteError('AV19 영상 주소를 다시 준비하세요.')
            def validate(value):
                kind = delivery['resources'].get(value)
                if kind is None:
                    raise EpisodeSiteError('AV19 재생목록에 없는 주소는 요청할 수 없습니다.')
                return resource_url(value, delivery['identity'], kind, manifest_host=delivery.get('manifest_host'))
            address = validate(request.url)
            kind = delivery['resources'][address]
            # Full fragments are returned as HTTP 200 even for retry Range requests;
            # native HttpFD handles a range-ignoring origin without corrupting resume.
            with self._av19_lock:
                data = self._av19_keys.get(address) if kind == 'key' else None
                if data is None:
                    client = SiteClient()
                    try:
                        _, data = client.request(address, MEDIA, referer=delivery['referer'],
                                                 binary=True, validator=validate,
                                                 max_bytes=16*1024*1024 if kind == 'segment' else 65536 if kind == 'key' else 3*1024*1024)
                    finally:
                        client.close()
                    if kind == 'key':
                        data = decode_key(delivery['module'], data)
                        self._av19_keys[address] = data
                    elif kind == 'segment' and (not data or len(data) % 16):
                        raise EpisodeSiteError('AV19 영상 조각이 정상 AES-CBC 형식이 아닙니다.')
            return Response(BytesIO(data), address, {'Content-Length': str(len(data)),
                                                    'Content-Type': 'application/octet-stream'})
        except EpisodeSiteError as error:
            if error.status in (401, 403):
                raise ExtractorError('AV19 접근 거부 또는 세션 만료입니다. 사이트 접속 상태를 확인하고 영상 주소를 다시 준비하세요.', expected=True) from None
            raise ExtractorError('AV19 전송 실패: ' + str(error), expected=True) from None
