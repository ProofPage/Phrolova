"""통계에 표시하는 경로는 기존 저장 엔진의 우선순위를 그대로 따른다."""
from types import SimpleNamespace

import pytest

from app.api import stats
from app.core.config import Settings


@pytest.mark.asyncio
@pytest.mark.parametrize('overrides,expected', [
    ({}, ('/legacy', '/legacy', '/legacy')),
    ({'live_download_dir': '/live'}, ('/live', '/legacy', '/legacy')),
    ({'vod_download_dir': '/video'}, ('/legacy', '/video', '/video')),
    ({'live_download_dir': '/live', 'vod_download_dir': '/video'}, ('/live', '/video', '/video')),
    ({'split_download_dirs': True, 'vod_chzzk_dir': '/chzzk', 'vod_external_dir': '/external'}, ('/legacy', '/external', '/chzzk')),
    ({'split_download_dirs': True, 'vod_chzzk_dir': '/chzzk'}, ('/legacy', '/legacy', '/chzzk')),
    ({'split_download_dirs': True, 'vod_chzzk_dir': '/chzzk', 'vod_external_dir': '/external', 'vod_download_dir': '/video'}, ('/legacy', '/video', '/video')),
])
async def test_stats_exposes_effective_paths_without_changing_legacy_fields(monkeypatch, overrides, expected):
    values=dict(download_dir='/legacy', live_download_dir='', vod_download_dir='', split_download_dirs=False, vod_chzzk_dir='', vod_external_dir='')
    values.update(overrides)
    settings=Settings(_env_file=None, **values)
    monkeypatch.setattr(stats, 'get_settings', lambda: settings)
    monkeypatch.setattr(stats, 'LiveHistoryRepository', lambda: SimpleNamespace(list_sessions=lambda: []))
    monkeypatch.setattr(stats, 'VodRepository', lambda: SimpleNamespace(list_all=lambda: []))
    monkeypatch.setattr(stats, 'Path', lambda value: SimpleNamespace(exists=lambda: False))
    def no_service():
        raise RuntimeError('No service in isolated test')
    monkeypatch.setattr('app.main.get_recorder_service', no_service)

    result=await stats.get_stats()
    storage=result['storage']
    assert (storage['live_download_dir'], storage['vod_download_dir'], storage['vod_chzzk_dir'])==expected
    assert storage['download_dir']==expected[0]
    assert (storage['used_bytes'], storage['total_bytes'], storage['free_bytes'])==(0,0,0)
    assert storage['usage_available'] is False
    assert settings.model_dump()==Settings(_env_file=None, **values).model_dump()


@pytest.mark.asyncio
@pytest.mark.parametrize('available', [True, False])
async def test_disk_measurement_and_volume_metadata(monkeypatch, available):
    settings = Settings(_env_file=None, download_dir='/live')
    monkeypatch.setattr(stats, 'get_settings', lambda: settings)
    monkeypatch.setattr(stats, 'LiveHistoryRepository', lambda: SimpleNamespace(list_sessions=lambda: []))
    monkeypatch.setattr(stats, 'VodRepository', lambda: SimpleNamespace(list_all=lambda: []))
    monkeypatch.setattr(stats, 'Path', lambda value: SimpleNamespace(exists=lambda: True, __str__=lambda: value))
    def no_service():
        raise RuntimeError('Isolated test')
    monkeypatch.setattr('app.main.get_recorder_service', no_service)
    def usage(path):
        if not available:
            raise OSError('Drive unavailable')
        return SimpleNamespace(used=500, total=1000, free=500)
    monkeypatch.setattr(stats.shutil, 'disk_usage', usage)
    calls = []
    def volume(path):
        calls.append(path)
        return {'disk_mountpoint': '/volume', 'disk_filesystem': 'testfs'}
    monkeypatch.setattr(stats, '_disk_volume_info', volume)
    storage = (await stats.get_stats())['storage']
    assert storage['usage_available'] is available
    assert (storage['disk_mountpoint'], storage['disk_filesystem']) == (('/volume', 'testfs') if available else ('', ''))
    assert bool(calls) is available
