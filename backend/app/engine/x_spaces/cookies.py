"""X 인증 쿠키를 읽고, 헤더를 만들고, 살아있는지 확인한다."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import httpx

from app.core.logger import logger

from app.engine.x_spaces.constants import _BEARER_TOKEN, _USER_BY_SCREEN_NAME_QUERY_ID


def _parse_netscape_cookies(cookie_file: str) -> dict[str, str]:
    """Netscape 형식 쿠키 파일에서 X 인증에 필요한 쿠키를 추출한다.

    Returns:
        {"auth_token": "...", "ct0": "...", ...} 형태의 딕셔너리.
        필요한 키가 없으면 빈 딕셔너리.
    """
    result: dict[str, str] = {}
    target_keys = {"auth_token", "ct0"}

    try:
        with open(cookie_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    name = parts[5]
                    value = parts[6]
                    if name in target_keys:
                        result[name] = value
    except Exception as e:
        logger.error(f"쿠키 파일 파싱 실패: {cookie_file} — {e}")

    return result


def _build_headers(ct0: str) -> dict[str, str]:
    """X 내부 API 호출에 필요한 헤더를 구성한다."""
    return {
        "Authorization": f"Bearer {_BEARER_TOKEN}",
        "x-csrf-token": ct0,
        "x-twitter-auth-type": "OAuth2Client",
        "x-twitter-client-language": "ko",
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }


async def verify_cookie(cookie_file: str) -> dict:
    """쿠키 파일의 auth_token/ct0로 X 인증 유효성을 확인한다.

    X API verify_credentials 엔드포인트를 호출하여 쿠키 만료 여부를 판단한다.

    Args:
        cookie_file: Netscape 형식 쿠키 파일 경로.

    Returns:
        {"valid": bool, "checked_at": ISO8601 str, "reason": str | None}
    """
    checked_at = datetime.now().isoformat()

    if not cookie_file or not Path(cookie_file).is_file():
        return {
            "valid": False,
            "checked_at": checked_at,
            "reason": f"쿠키 파일을 찾을 수 없습니다: {cookie_file}",
        }

    cookies = _parse_netscape_cookies(cookie_file)
    if not cookies.get("auth_token") or not cookies.get("ct0"):
        return {
            "valid": False,
            "checked_at": checked_at,
            "reason": "쿠키 파일에서 auth_token/ct0를 찾을 수 없습니다.",
        }

    headers = _build_headers(cookies["ct0"])

    try:
        async with httpx.AsyncClient(
            cookies=cookies,
            headers=headers,
            timeout=10.0,
            follow_redirects=True,
        ) as client:
            # account/verify_credentials.json은 deprecated → UserByScreenName으로 대체
            variables = json.dumps({
                "screen_name": "x",
                "withSafetyModeUserFields": True,
            })
            features = json.dumps({
                "hidden_profile_likes_enabled": True,
                "hidden_profile_subscriptions_enabled": True,
                "responsive_web_graphql_exclude_directive_enabled": True,
                "verified_phone_label_enabled": False,
                "subscriptions_verification_info_is_identity_verified_enabled": True,
                "subscriptions_verification_info_verified_since_enabled": True,
                "highlights_tweets_tab_ui_enabled": True,
                "responsive_web_twitter_article_notes_tab_enabled": False,
                "creator_subscriptions_tweet_preview_api_enabled": True,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                "responsive_web_graphql_timeline_navigation_enabled": True,
            })
            resp = await client.get(
                f"https://twitter.com/i/api/graphql/{_USER_BY_SCREEN_NAME_QUERY_ID}/UserByScreenName",
                params={"variables": variables, "features": features},
            )
            if resp.status_code == 200:
                return {"valid": True, "checked_at": checked_at, "reason": None}
            elif resp.status_code == 401:
                return {
                    "valid": False,
                    "checked_at": checked_at,
                    "reason": "쿠키가 만료되었습니다. 브라우저에서 쿠키를 다시 추출해주세요.",
                }
            else:
                return {
                    "valid": False,
                    "checked_at": checked_at,
                    "reason": f"X API 응답 오류 (HTTP {resp.status_code})",
                }
    except httpx.RequestError as e:
        return {
            "valid": False,
            "checked_at": checked_at,
            "reason": f"네트워크 오류: {e}",
        }
    except Exception as e:
        return {
            "valid": False,
            "checked_at": checked_at,
            "reason": f"예상치 못한 오류: {e}",
        }
