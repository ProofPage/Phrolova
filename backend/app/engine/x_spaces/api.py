"""X GraphQL 호출과 응답 파싱.

이 층은 쿠키를 모른다 — 헤더는 호출하는 쪽에서 만들어 넘긴다.
"""

from __future__ import annotations

import json
from typing import Optional

import httpx

from app.core.logger import logger

from app.engine.x_spaces.constants import (
    _AUDIO_SPACE_BY_ID_QUERY_ID,
    _USER_BY_SCREEN_NAME_QUERY_ID,
    _USER_TWEETS_QUERY_IDS,
)


async def _get_user_id(client: httpx.AsyncClient, username: str) -> Optional[str]:
    """GraphQL UserByScreenName으로 user_id를 조회한다."""
    variables = json.dumps({
        "screen_name": username,
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

    try:
        resp = await client.get(
            f"https://twitter.com/i/api/graphql/{_USER_BY_SCREEN_NAME_QUERY_ID}/UserByScreenName",
            params={"variables": variables, "features": features},
        )
        resp.raise_for_status()
        data = resp.json()
        user = data.get("data", {}).get("user", {}).get("result", {})
        return user.get("rest_id")
    except Exception as e:
        logger.warning(f"UserByScreenName 조회 실패 ({username}): {e}")
        return None


async def _get_active_space(
    client: httpx.AsyncClient,
    user_id: str,
    username: str,
) -> Optional[dict]:
    """AudioSpaceSearch 또는 UserTweets 타임라인에서 활성 Space를 탐색한다.

    Returns:
        {"space_id": ..., "title": ..., "media_key": ...} 또는 None.
    """
    # UserTweets 타임라인에서 Space 관련 트윗 탐색
    variables = json.dumps({
        "userId": user_id,
        "count": 20,
        "includePromotedContent": False,
        "withQuickPromoteEligibilityTweetFields": False,
        "withVoice": True,
        "withV2Timeline": True,
    })
    features = json.dumps({
        "rweb_lists_timeline_redesign_enabled": True,
        "responsive_web_graphql_exclude_directive_enabled": True,
        "verified_phone_label_enabled": False,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_timeline_navigation_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "tweetypie_unmention_optimization_enabled": True,
        "responsive_web_edit_tweet_api_enabled": True,
        "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
        "view_counts_everywhere_api_enabled": True,
        "longform_notetweets_consumption_enabled": True,
        "responsive_web_twitter_article_tweet_consumption_enabled": False,
        "tweet_awards_web_tipping_enabled": False,
        "freedom_of_speech_not_reach_fetch_enabled": True,
        "standardized_nudges_misinfo": True,
        "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
        "longform_notetweets_rich_text_read_enabled": True,
        "longform_notetweets_inline_media_enabled": True,
        "responsive_web_media_download_video_enabled": False,
        "responsive_web_enhance_cards_enabled": False,
    })

    # 여러 QUERY_ID 후보를 순서대로 시도 (X 배포마다 변경되므로)
    for qid in _USER_TWEETS_QUERY_IDS:
        try:
            resp = await client.get(
                f"https://twitter.com/i/api/graphql/{qid}/UserTweets",
                params={"variables": variables, "features": features},
            )
            if resp.status_code == 400:
                continue
            resp.raise_for_status()
            data = resp.json()
            space_info = _extract_space_from_timeline(data)
            if space_info:
                return space_info
            # 응답은 왔지만 Space 없음 → 오프라인 (qid 성공 확인용 디버그 로그)
            logger.debug(f"[XSpaces:{username}] UserTweets 성공 (qid={qid}) — Space 없음 또는 파싱 실패")
            return None
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning(f"[XSpaces:{username}] UserTweets 레이트 리밋 (429). 다음 폴링까지 대기.")
            else:
                logger.warning(f"UserTweets HTTP 오류 (qid={qid}): {e.response.status_code} — {e.response.text[:200]}")
            continue
        except Exception as e:
            logger.warning(f"UserTweets 조회 실패 (qid={qid}): {e}")
            continue

    # 타임라인 실패 시 AudioSpaceById로 직접 시도 (space_id를 모르면 불가, fallback 없음)
    logger.warning(f"[XSpaces:{username}] 모든 타임라인 쿼리 실패.")
    return None


def _extract_space_id_from_url(url: str) -> Optional[str]:
    """URL에서 space_id를 추출한다. /i/spaces/{id} 패턴."""
    if "/i/spaces/" not in url:
        return None
    try:
        return url.rstrip("/").split("/i/spaces/")[1].split("?")[0].split("/")[0]
    except IndexError:
        return None


def _extract_space_from_timeline(data: dict) -> Optional[dict]:
    """UserTweets GraphQL 응답에서 활성 Space 정보를 추출한다.

    탐색 순서:
    1. tweet.legacy.entities.urls[].expanded_url (가장 안정적)
    2. card.legacy.binding_values list 형식 (구버전 호환)
    3. card.legacy.binding_values dict 형식 (신버전)
    """
    try:
        instructions = (
            data.get("data", {})
            .get("user", {})
            .get("result", {})
            .get("timeline_v2", {})
            .get("timeline", {})
            .get("instructions", [])
        )
        for instruction in instructions:
            for entry in instruction.get("entries", []):
                content = entry.get("content", {})
                tweet_result = (
                    content.get("itemContent", {})
                    .get("tweet_results", {})
                    .get("result", {})
                )
                if not tweet_result:
                    continue

                tweet_legacy = tweet_result.get("legacy", {})

                # 방법 1: entities.urls (가장 안정적)
                for url_entity in tweet_legacy.get("entities", {}).get("urls", []):
                    for key in ("expanded_url", "url", "display_url"):
                        space_id = _extract_space_id_from_url(url_entity.get(key, ""))
                        if space_id:
                            return {"space_id": space_id, "title": "X Spaces", "media_key": None}

                # 방법 2: card.legacy.binding_values (list 형식)
                card = tweet_result.get("card", {})
                card_legacy = card.get("legacy", {})
                binding_values = card_legacy.get("binding_values", [])

                if isinstance(binding_values, list):
                    title = ""
                    space_id = None
                    for bv in binding_values:
                        key = bv.get("key", "")
                        val = bv.get("value", {})
                        if key == "card_url":
                            url = val.get("scribe_value", {}).get("value", "") or val.get("string_value", "")
                            space_id = _extract_space_id_from_url(url)
                        elif key == "title":
                            title = val.get("string_value", "")
                    if space_id:
                        return {"space_id": space_id, "title": title or "X Spaces", "media_key": None}

                elif isinstance(binding_values, dict):
                    # 방법 3: binding_values dict 형식 (신버전)
                    card_url_obj = binding_values.get("card_url", {})
                    url = card_url_obj.get("string_value", "")
                    space_id = _extract_space_id_from_url(url)
                    if space_id:
                        title = binding_values.get("title", {}).get("string_value", "X Spaces")
                        return {"space_id": space_id, "title": title, "media_key": None}

    except Exception:
        pass
    return None


def _derive_master_url(dynamic_url: str) -> str:
    """dynamic_playlist.m3u8 URL에서 master_playlist.m3u8 URL을 유도한다.

    master URL은 쿼리파라미터 없이 안정적 — 종료 후 약 30일간 유효.

    Args:
        dynamic_url: live_video_stream에서 반환된 dynamic_playlist.m3u8?token=... URL.

    Returns:
        master_playlist.m3u8 URL (쿼리파라미터 제거).
    """
    return dynamic_url.split("?")[0].replace("dynamic_playlist", "master_playlist")


async def get_space_by_id(
    client: httpx.AsyncClient,
    space_id: str,
) -> Optional[dict]:
    """AudioSpaceById로 특정 Space의 상태와 media_key를 조회한다."""
    variables = json.dumps({
        "id": space_id,
        "isMetatagsQuery": False,
        "withSuperFollowsUserFields": False,
        "withUserResults": True,
        "withBirdwatchPivots": False,
        "withReactionsMetadata": False,
        "withReactionsPerspective": False,
        "withSuperFollowsTweetFields": False,
        "withReplays": True,
        "withScheduledSpaces": False,
        "withDownvotePerspective": False,
    })

    try:
        resp = await client.get(
            f"https://twitter.com/i/api/graphql/{_AUDIO_SPACE_BY_ID_QUERY_ID}/AudioSpaceById",
            params={"variables": variables},
        )
        resp.raise_for_status()
        data = resp.json()
        metadata = data.get("data", {}).get("audioSpace", {}).get("metadata", {})
        state = metadata.get("state", "")  # "Running" or "Ended" or "NotStarted"
        media_key = metadata.get("media_key")
        title = metadata.get("title", "X Spaces")
        return {"state": state, "media_key": media_key, "title": title}
    except Exception as e:
        logger.debug(f"AudioSpaceById 조회 실패 (space_id={space_id}): {e}")
        return None


async def _get_m3u8_url(
    client: httpx.AsyncClient,
    media_key: str,
    username: str,
) -> Optional[str]:
    """live_video_stream/status/{media_key}에서 m3u8 URL을 추출한다."""
    try:
        resp = await client.get(
            f"https://twitter.com/i/api/1.1/live_video_stream/status/{media_key}",
            params={"client": "web", "use_syndication_guest_id": "false", "cookie_set_token": "xx"},
        )
        resp.raise_for_status()
        data = resp.json()
        location = data.get("source", {}).get("location", "")
        if location and "m3u8" in location:
            return location
        logger.debug(f"[XSpaces:{username}] m3u8 URL 없음. 응답: {str(data)[:200]}")
        return None
    except Exception as e:
        logger.debug(f"[XSpaces:{username}] live_video_stream 조회 실패: {e}")
        return None
