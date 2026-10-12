"""Current SOOP viewers must come from broadcast metadata, never station totals."""
import httpx
import pytest
from app.engine.soop import SoopLiveEngine


@pytest.mark.asyncio
@pytest.mark.parametrize('viewers', [17916, '17916', 0])
async def test_current_broadcast_viewers_and_cache(monkeypatch, viewers):
    original = httpx.AsyncClient
    calls = []
    def respond(request):
        calls.append(request)
        if request.method == 'POST':
            return httpx.Response(200, json={'CHANNEL': {'RESULT': 1, 'BNO': '42', 'BJNICK': '숲 채널', 'VIEW_CNT': 99}})
        assert request.url.host == 'chapi.sooplive.com'
        return httpx.Response(200, json={'profile_image': 'https://example.test/profile.jpg',
            'broad': {'broad_no': 42, 'current_sum_viewer': viewers},
            'station': {'broad_start': '2026-10-12 14:07:32', 'upd': {'total_view_cnt': 1200547639}}})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    engine = SoopLiveEngine()
    status = await engine.check_live_status('alice')
    assert status['viewer_count'] == int(viewers)
    assert status['profile_image_url'] == 'https://example.test/profile.jpg'
    assert status['live_started_at'] == '2026-10-12 14:07:32'
    assert (await engine.check_live_status('alice'))['viewer_count'] == int(viewers)
    assert len(calls) == 2
    # Expiration must refresh the current number instead of pinning the first.
    viewers = 19300
    stamp, channel, station = engine._cache['alice']
    engine._cache['alice'] = (stamp - 9, channel, station)
    assert (await engine.check_live_status('alice'))['viewer_count'] == 19300
    assert len(calls) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['offline', 'stale', 'missing', 'network'])
async def test_missing_or_stale_station_cannot_replace_current_status(monkeypatch, case):
    original = httpx.AsyncClient
    def respond(request):
        if request.method == 'POST':
            return httpx.Response(200, json={'CHANNEL': {'RESULT': 0 if case == 'offline' else 1,
                'BNO': '42', 'VIEW_CNT': '12', 'BJNICK': '숲 채널'}})
        if case == 'network':
            raise httpx.ConnectError('station temporarily unavailable', request=request)
        return httpx.Response(200, json={'broad': {'broad_no': 41 if case == 'stale' else 42,
            'current_sum_viewer': None if case == 'missing' else 17000}})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    status = await SoopLiveEngine().check_live_status('alice')
    assert status['is_live'] == (case != 'offline')
    assert status['viewer_count'] == (0 if case == 'offline' else 12)
