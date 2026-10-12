"""CHZZK source discovery and native Streamlink continuity integration.

Source selection is adapted from Chzzk-Rekoda 50424e5 (MIT; see third_party).
The Akamai mapping is a candidate only: the writer verifies the same interval,
rendition, initialization and media before it can replace Korean media.
"""

import base64
import json
from urllib.parse import parse_qs, urlsplit, urlunsplit

from streamlink.exceptions import StreamError
from streamlink.stream.hls import HLSStream

from app.engine.chzzk_continuity import (
    ChzzkContinuityReader, ChzzkM3U8Parser, ContinuitySource,
    SourcePath, Unavailable, cdn_from_url,
)
from app.engine.chzzk_time_machine import LIVE_DETAIL_URL, TIME_MACHINE_URL, _is_trusted_media_url


def trusted_media_url(url):
    try:
        return isinstance(url, str) and _is_trusted_media_url(url)
    except ValueError:
        return False


def source_paths(media):
    paths = []
    for item in media:
        if not isinstance(item, dict):
            continue
        if str(item.get('mediaId')).upper() not in {'HLS', 'LLHLS'} or str(item.get('protocol')).upper() != 'HLS':
            continue
        url = item.get('path')
        if not isinstance(url, str) or not trusted_media_url(url):
            continue
        mode = 'llhls' if str(item['mediaId']).upper() == 'LLHLS' else 'hls'
        paths.append(SourcePath(url, False, mode, cdn_from_url(url)))
        tracks = item.get('encodingTrack') or []
        for track in tracks if isinstance(tracks, list) else []:
            p2p = track.get('p2pPath') if isinstance(track, dict) else None
            if not isinstance(p2p, str):
                continue
            for encoded in parse_qs(urlsplit(p2p).query).get('cdn_url', []):
                try:
                    history = base64.b64decode(encoded + '=' * (-len(encoded) % 4), validate=True).decode('utf-8')
                except (ValueError, UnicodeError):
                    continue
                if trusted_media_url(history):
                    paths.append(SourcePath(history, True, 'hls', cdn_from_url(history)))
    for path in list(paths):
        parsed = urlsplit(path.url)
        if not path.history and parsed.hostname in {'nvelop-livecloud.pstatic.net', 'livecloud.pstatic.net'}:
            candidate = urlunsplit(parsed._replace(netloc='livecloud.akamaized.net'))
            if not any(p.url == candidate and p.mode == path.mode for p in paths):
                paths.append(SourcePath(candidate, False, path.mode, 'akamai', probe=True))
    return sorted(dict.fromkeys(paths), key=lambda path: path.priority)


class ChzzkHLSStream(HLSStream):
    __reader__ = ChzzkContinuityReader
    __parser__ = ChzzkM3U8Parser

    def __init__(self, session, url, channel_id, *args, live_id=0,
                 source_paths=(), start_lookback=0, resume=None,
                 time_machine_active=None, source_mode='hls', source_cdn=None,
                 event_callback=None, api_cookie=None, capture_start_offset=0,
                 recording_time_machine=False,
                 buffer_dir=None,
                 **kwargs):
        super().__init__(session, url, *args, **kwargs)
        self._url = url
        self._channel_id = channel_id
        self.api_cookie = api_cookie
        self.recording_time_machine = recording_time_machine
        self.capture_start_offset = capture_start_offset
        self.buffer_dir = buffer_dir
        self.continuity = ContinuitySource(
            self, self._source_snapshot, live_id, source_paths,
            lookback=start_lookback, resume=resume,
            time_machine_active=time_machine_active, mode=source_mode,
            cdn=source_cdn, event_callback=event_callback,
        )

    @property
    def url(self):
        return self._url

    def _source_snapshot(self):
        headers = {'Referer': 'https://chzzk.naver.com/'}
        if self.api_cookie:
            headers['Cookie'] = self.api_cookie
        try:
            response = self.session.http.get(
                LIVE_DETAIL_URL.format(channel_id=self._channel_id),
                headers=headers, timeout=(5, 5), retries=0,
            )
            response.raise_for_status()
            payload = response.json()
            content = payload.get('content') or {}
            if payload.get('code', 200) != 200:
                raise Unavailable('CHZZK API rejected source discovery', category='http')
            if content.get('status') != 'OPEN':
                return None
            if content.get('membershipBenefitType') == 'MEMBER_ONLY' and not self.api_cookie:
                raise Unavailable('Authentication required', status=403, category='http')
            live_id = content.get('liveId')
            if type(live_id) is not int:
                raise Unavailable('CHZZK API did not return a live ID')
            playback = content.get('livePlaybackJson') or '{}'
            playback = json.loads(playback) if isinstance(playback, str) else playback
            paths = source_paths(playback.get('media') or [])
            if self.recording_time_machine:
                time_response = self.session.http.get(
                    TIME_MACHINE_URL.format(live_id=live_id), headers=headers,
                    timeout=(5, 5), retries=0,
                )
                time_response.raise_for_status()
                time_payload = time_response.json()
                time_content = time_payload.get('content') or {}
                time_media = (time_content.get('playback') or {}).get('media') or []
                # The time-machine endpoint also returns compact tuple entries.
                time_media = [dict(mediaId=i[0], protocol=i[1], path=i[2])
                              if isinstance(i, (list, tuple)) and len(i)>=3 else i for i in time_media]
                machine_paths = source_paths(time_media)
                if time_payload.get('code', 200) != 200 or not machine_paths:
                    raise Unavailable('Required CHZZK time-machine source unavailable')
                paths = machine_paths + paths
            if not paths:
                raise Unavailable('CHZZK source unavailable or unauthorized')
            selected = SourcePath(self._url, False, self.continuity.primary.mode, cdn_from_url(self._url))
            return live_id, [selected, *paths], content.get('timeMachineActive')
        except Unavailable:
            raise
        except Exception as error:
            status = getattr(getattr(error, 'response', None), 'status_code', None)
            raise Unavailable('CHZZK API source discovery failed', status=status,
                              category='http' if status else 'network') from None

    def initialize_sources(self):
        snapshot = self._source_snapshot()
        if snapshot is None:
            raise Unavailable('CHZZK broadcast ended')
        live_id, paths, flag = snapshot
        self.continuity.live_id = live_id
        # Preserve explicit time-machine/CDN/TS rendition selection. Discovery
        # supplements it with validated alternatives instead of replacing it.
        mode = next((p.mode for p in paths if p.url == self._url), self.continuity.primary.mode)
        initial = SourcePath(self._url, False, mode, cdn_from_url(self._url))
        self.continuity.paths = [initial, *paths]
        self.continuity.primary.mode = mode
        self.continuity.time_machine_active = flag
