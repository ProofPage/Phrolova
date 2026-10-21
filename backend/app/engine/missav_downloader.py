"""Allow only this extraction's exact HLS resources, including every redirect."""
from io import BytesIO
import yt_dlp
from yt_dlp.networking import Request, Response
from yt_dlp.utils import ExtractorError
from app.engine.episode_sites import SiteClient, EpisodeSiteError
from app.engine.missav import MEDIA_HOSTS, resource_url


class MissAVYoutubeDL(yt_dlp.YoutubeDL):
    def __init__(self, *args, **kwargs):
        self._missav_delivery = None
        super().__init__(*args, **kwargs)

    def configure_missav(self, delivery):
        self._missav_delivery = delivery

    def urlopen(self, request):
        try:
            d = self._missav_delivery
            if not d or not isinstance(request, Request) or request.method != 'GET' or request.data is not None:
                raise EpisodeSiteError('MissAV 허용되지 않은 요청입니다.')
            def validate(value):
                kind = d['resources'].get(value)
                if not kind:
                    raise EpisodeSiteError('MissAV 본편 재생목록에 없는 주소입니다.')
                return resource_url(value, d['identity'], kind)
            address = validate(request.url)
            if address in d['playlists']:
                data = d['playlists'][address].encode()
            else:
                client = SiteClient()
                try:
                    _, data = client.request(address, MEDIA_HOSTS, referer=d['referer'],
                                             binary=True, validator=validate, max_bytes=16*1024*1024)
                finally:
                    client.close()
                if len(data) < 377 or any(data[i] != 0x47 for i in (0, 188, 376)):
                    raise EpisodeSiteError('MissAV 정상 MPEG-TS 영상 조각이 아닙니다.')
            return Response(BytesIO(data), address, {'Content-Length': str(len(data))})
        except EpisodeSiteError as error:
            raise ExtractorError('MissAV 전송 실패: ' + str(error), expected=True) from None
