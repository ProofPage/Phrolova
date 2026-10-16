"""Exercise credential and settings transactions at the HTTP boundary."""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import platforms, setup
from app.api.settings import auth, notifications
from app.core.config import get_settings
from app.engine.auth import AuthManager
from app.services.recorder import RecorderService


def denied(*args, **kwargs):
    assert kwargs['raise_on_error'] is True
    raise PermissionError('private-secret must not appear in response')


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(platforms, '_COOKIE_SAVE_PATH', tmp_path / 'cookies.txt')
    service = RecorderService.__new__(RecorderService)
    service._auth = AuthManager(nid_aut='old-aut', nid_ses='old-ses')
    monkeypatch.setattr('app.main.get_recorder_service', lambda: service)
    app = FastAPI()
    for router in (platforms.router, setup.router, auth.router, notifications.router):
        app.include_router(router)
    with TestClient(app) as http:
        yield http


@pytest.mark.parametrize('platform,filename,field,body', [
    ('youtube/cookie', 'youtube_cookies.txt', 'youtube_cookie_file',
     '# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tnew-secret\n'),
    ('kick/cookie', 'kick_cookies.txt', 'kick_cookie_file',
     '# Netscape HTTP Cookie File\n.kick.com\tTRUE\t/\tTRUE\t0\tsession_token\tnew-secret\n'),
    ('rplay/session', 'rplay_session.json', 'rplay_session_file',
     json.dumps({'accessToken': 'new-secret-token-123456', 'requestorOid': 'a' * 24})),
])
@pytest.mark.parametrize('operation', ['post', 'delete'])
@pytest.mark.parametrize('existing', [True, False])
@pytest.mark.parametrize('error_type', [PermissionError, ValueError])
def test_file_transaction_restores_prior_state(client, monkeypatch, tmp_path, platform, filename, field, body, operation, existing, error_type):
    path = tmp_path / filename
    if existing:
        path.write_bytes(b'previous-secret')
    settings = get_settings()
    previous = str(path) if existing else None
    setattr(settings, field, previous)
    def cannot_save(*args, **kwargs):
        assert kwargs['raise_on_error'] is True
        raise error_type('private-secret')
    monkeypatch.setattr(platforms, '_update_env_file', cannot_save)
    response = getattr(client, operation)('/api/platforms/' + platform,
        **({'files': {'file': ('credentials.txt', body)}} if operation == 'post' else {}))
    assert response.status_code == 500, response.text
    assert 'private-secret' not in response.text and 'new-secret' not in response.text
    assert path.exists() == existing
    if existing:
        assert path.read_bytes() == b'previous-secret'
    assert getattr(get_settings(), field) == previous
    assert not list(tmp_path.glob('.credential-*'))


def test_failed_restore_keeps_previous_credential_for_recovery(client, monkeypatch, tmp_path):
    destination = tmp_path / 'kick_cookies.txt'
    destination.write_bytes(b'previous-secret')
    monkeypatch.setattr(platforms, '_update_env_file', denied)
    original = Path.replace
    def replace(path, target):
        if path.name == 'previous':
            raise PermissionError('restore denied')
        return original(path, target)
    monkeypatch.setattr(Path, 'replace', replace)
    result = client.delete('/api/platforms/kick/cookie')
    assert result.status_code == 500 and '복구 파일 위치' in result.text
    backups = list(tmp_path.glob('.credential-*/previous'))
    assert len(backups) == 1 and backups[0].read_bytes() == b'previous-secret'
    assert 'previous-secret' not in result.text


def test_auth_write_failure_preserves_running_credentials(client, monkeypatch):
    settings = get_settings()
    settings.nid_aut, settings.nid_ses = 'old-aut', 'old-ses'
    monkeypatch.setattr('app.core.utils.update_env_file', denied)
    response = client.put('/api/settings/cookies', json={'nid_aut': 'new-aut', 'nid_ses': 'new-ses'})
    assert response.status_code == 500 and 'private-secret' not in response.text
    assert (settings.nid_aut, settings.nid_ses) == ('old-aut', 'old-ses')
    from app.main import get_recorder_service
    assert get_recorder_service()._auth.get_ytdlp_cookies() == 'NID_AUT=old-aut; NID_SES=old-ses'


def test_cookie_removal_reports_logged_out(client):
    response = client.put('/api/settings/cookies', json={'nid_aut': '', 'nid_ses': ''})
    assert response.status_code == 200 and response.json()['authenticated'] is False


@pytest.mark.parametrize('invalid', [True, False])
def test_discord_does_not_partially_apply_failed_request(client, monkeypatch, invalid):
    settings = get_settings()
    settings.discord_bot_token = 'old-token'
    settings.discord_notify_ttl = 300
    monkeypatch.setattr(notifications, '_update_env_file', denied)
    response = client.put('/api/settings/discord', json={
        'discord_bot_token': 'new-token', 'discord_notify_ttl': 600,
        'discord_webhook_url': 'http://invalid.example' if invalid else 'https://discord.com/api/webhooks/test',
    })
    assert response.status_code == (400 if invalid else 500)
    assert settings.discord_bot_token == 'old-token' and settings.discord_notify_ttl == 300
    assert 'private-secret' not in response.text


def test_setup_save_failure_does_not_mark_configured(client, monkeypatch, tmp_path):
    settings = get_settings()
    previous = settings.model_dump()
    monkeypatch.setattr(setup, '_update_env_file', denied)
    response = client.post('/api/setup/complete', json={'download_dir': str(tmp_path / 'downloads')})
    assert response.status_code == 500 and 'private-secret' not in response.text
    assert settings.model_dump() == previous
    assert not setup.is_setup_complete()


def test_setup_commits_cookies_once(client, monkeypatch, tmp_path):
    calls = []
    original = setup._update_env_file
    def save(values, **kwargs):
        calls.append(values)
        original(values, **kwargs)
    monkeypatch.setattr(setup, '_update_env_file', save)
    monkeypatch.setattr('app.core.utils.update_env_file', denied)
    response = client.post('/api/setup/complete', json={
        'download_dir': str(tmp_path / 'downloads'), 'nid_aut': 'new-aut', 'nid_ses': 'new-ses',
    })
    assert response.status_code == 200 and len(calls) == 1
    from app.main import get_recorder_service
    assert get_recorder_service()._auth.get_ytdlp_cookies() == 'NID_AUT=new-aut; NID_SES=new-ses'
