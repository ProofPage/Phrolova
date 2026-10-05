"""
test_api_surface.py
공개 API 표면을 고정한다.

이 프로젝트의 1번 규칙은 "API 계약을 바꾸지 않는다"이다. 그런데 라우트는
데코레이터로 등록돼서, 파일을 옮기다 실수로 빠뜨려도 파싱도 import도 성공한다.
실제로 설정 라우터를 도메인별로 나누다 라우트 15개를 통째로 잃은 적이 있고,
그때는 이 목록을 손으로 대조해서야 알았다.

경로가 바뀌면 이 테스트가 먼저 깨진다. 의도한 변경이라면 아래
EXPECTED_API_ROUTES를 함께 고치면 되고, 그 diff가 곧 "API를 바꿨다"는 기록이 된다.

FastAPI 0.137부터 include_router()는 하위 라우트를 app.routes에 복사하지 않고
중첩 라우터로 보존한다. 따라서 app.routes를 평면 목록으로 순회하지 않는다.
공개 API는 공식 OpenAPI 스키마로 검사하고, 스키마가 합치는 후행 슬래시 별칭과
문서·SPA 경로는 실제 요청과 앱 설정으로 따로 검사한다.
"""

import re

from fastapi.testclient import TestClient

from app.main import STATIC_DIR, app

#: (HTTP 메서드, 경로). 메서드는 쉼표로 이어 붙이고 HEAD는 뺀다
#: (FastAPI가 GET에 자동으로 붙여주는 것이라 계약이 아니다).
EXPECTED_API_ROUTES = {
    ("POST", "/api/archive/download"),
    ("GET", "/api/archive/spaces/captured"),
    ("DELETE", "/api/archive/spaces/captured/{composite_key:path}"),
    ("POST", "/api/archive/spaces/download-captured"),
    ("GET", "/api/archive/twitcasting/{channel_id}"),
    ("GET", "/api/chat/files"),
    ("GET", "/api/chat/files/{file_id}/download"),
    ("GET", "/api/chat/files/{file_id}/messages"),
    ("GET", "/api/events"),
    ("GET", "/api/platforms/channels"),
    ("POST", "/api/platforms/channels"),
    ("DELETE", "/api/platforms/channels/{platform}/{channel_id:path}"),
    ("PATCH", "/api/platforms/channels/{platform}/{channel_id:path}/auto-record"),
    ("PUT", "/api/platforms/channels/{platform}/{channel_id:path}/download-options"),
    ("POST", "/api/platforms/scan-now"),
    ("PUT", "/api/platforms/settings/twitcasting"),
    ("GET", "/api/platforms/status"),
    ("DELETE", "/api/platforms/x/cookie"),
    ("POST", "/api/platforms/x/cookie"),
    ("GET", "/api/settings"),
    ("GET", "/api/settings/"),
    ("GET", "/api/settings/auth"),
    ("GET", "/api/settings/browse-dirs"),
    ("PUT", "/api/settings/chat"),
    ("GET", "/api/settings/cookie-status"),
    ("POST", "/api/settings/cookie-status/check"),
    ("PUT", "/api/settings/cookies"),
    ("POST", "/api/settings/cookies/test"),
    ("PUT", "/api/settings/discord"),
    ("GET", "/api/settings/discord/status"),
    ("POST", "/api/settings/discord/test"),
    ("PUT", "/api/settings/download"),
    ("PUT", "/api/settings/general"),
    ("PUT", "/api/settings/live"),
    ("PUT", "/api/settings/live-condition"),
    ("PUT", "/api/settings/vod"),
    ("POST", "/api/setup/complete"),
    ("GET", "/api/setup/status"),
    ("GET", "/api/stats"),
    ("GET", "/api/stats/"),
    ("GET", "/api/stream/channels"),
    ("POST", "/api/stream/channels"),
    ("DELETE", "/api/stream/channels/{channel_id:path}"),
    ("PATCH", "/api/stream/channels/{channel_id:path}/auto-record"),
    ("PUT", "/api/stream/channels/{channel_id}/download-options"),
    ("POST", "/api/stream/monitor/start"),
    ("POST", "/api/stream/monitor/stop"),
    ("POST", "/api/stream/record/stop-all"),
    ("POST", "/api/stream/record/{channel_id:path}/start"),
    ("POST", "/api/stream/record/{channel_id:path}/stop"),
    ("GET", "/api/system/logs"),
    ("GET", "/api/system/logs/{filename:path}"),
    ("DELETE", "/api/system/logs"),
    ("GET", "/api/system/update"),
    ("POST", "/api/system/update/check"),
    ("GET", "/api/tags"),
    ("POST", "/api/tags"),
    ("PATCH", "/api/tags/channel/{channel_id:path}"),
    ("DELETE", "/api/tags/{tag_name:path}"),
    ("POST", "/api/vod/clear-completed"),
    ("POST", "/api/vod/download"),
    ("POST", "/api/vod/info"),
    ("POST", "/api/vod/reorder"),
    ("GET", "/api/vod/status"),
    ("GET", "/api/vod/status/{task_id}"),
    ("POST", "/api/vod/{task_id}/cancel"),
    ("POST", "/api/vod/{task_id}/open-location"),
    ("POST", "/api/vod/{task_id}/pause"),
    ("POST", "/api/vod/{task_id}/resume"),
    ("POST", "/api/vod/{task_id}/retry"),
    ("GET", "/health"),
    ("GET", "/health/detail"),
}

TRAILING_SLASH_ALIASES = {
    ("GET", "/api/settings/"),
    ("GET", "/api/stats/"),
}

HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
PATH_CONVERTER = re.compile(r"{([^}:]+):[^}]+}")


def _schema_routes() -> set[tuple[str, str]]:
    schema = app.openapi()
    return {
        (method.upper(), path)
        for path, path_item in schema["paths"].items()
        for method in path_item
        if method in HTTP_METHODS and method != "head"
    }


def _expected_schema_routes() -> set[tuple[str, str]]:
    return {
        (method, PATH_CONVERTER.sub(r"{\1}", path))
        for method, path in EXPECTED_API_ROUTES - TRAILING_SLASH_ALIASES
    }


def _assert_same_routes(
    expected: set[tuple[str, str]], current: set[tuple[str, str]]
) -> None:
    removed = sorted(expected - current)
    added = sorted(current - expected)

    message = []
    if removed:
        message.append(
            "사라진 라우트 (배포된 구버전 클라이언트가 호출하던 것일 수 있다):\n  "
            + "\n  ".join(f"{m} {p}" for m, p in removed)
        )
    if added:
        message.append(
            "새로 생긴 라우트 (의도한 것이라면 EXPECTED_API_ROUTES에 추가한다):\n  "
            + "\n  ".join(f"{m} {p}" for m, p in added)
        )

    assert not message, "\n\n".join(message)


def test_public_api_surface_is_unchanged():
    """OpenAPI에 등록된 공개 API가 기대 목록과 정확히 같아야 한다."""
    _assert_same_routes(_expected_schema_routes(), _schema_routes())


def test_trailing_slash_aliases_are_explicit_routes():
    """자동 307 리다이렉트가 아니라 기존 별칭 자체가 응답해야 한다."""
    client = TestClient(app, follow_redirects=False)

    for _, path in sorted(TRAILING_SLASH_ALIASES):
        response = client.get(path)
        assert response.status_code == 200, f"GET {path}: {response.status_code}"


def test_documentation_routes_are_unchanged():
    assert app.docs_url == "/docs"
    assert app.swagger_ui_oauth2_redirect_url == "/docs/oauth2-redirect"
    assert app.openapi_url == "/openapi.json"
    assert app.redoc_url == "/redoc"


def test_spa_routes_follow_static_build_availability():
    """클린 백엔드와 프런트가 포함된 배포 환경의 동작을 모두 고정한다."""
    client = TestClient(app, follow_redirects=False)
    has_static_build = (STATIC_DIR / "index.html").exists()
    expected_status = 200 if has_static_build else 404

    for path in ("/", "/settings"):
        response = client.get(path)
        assert response.status_code == expected_status
        if has_static_build:
            assert '<div id="root"></div>' in response.text
