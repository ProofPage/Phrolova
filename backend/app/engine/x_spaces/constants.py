"""X API 엔드포인트와 GraphQL 쿼리 ID, Space 상태값."""

from __future__ import annotations

# ── 상수 ────────────────────────────────────────────────────────────
X_SPACES_URL = "https://x.com/i/spaces/{space_id}"

# X 웹 클라이언트에 하드코딩된 공개 Bearer 토큰
_BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

# GraphQL QUERY_ID — X 배포마다 변경될 수 있음
# 최신값 확인: yt-dlp/yt-dlp twitter.py, trevorhobenshield/twitter-api-client constants.py
_AUDIO_SPACE_BY_ID_QUERY_ID = "HPEisOmj1epUNLCWTYhUWw"
_USER_BY_SCREEN_NAME_QUERY_ID = "oUZZZ8Oddwxs8Cd3iW3UEA"
# AudioSpaceSearch는 X API deprecated — UserTweets 방식으로 탐색
_USER_TWEETS_QUERY_IDS = [
    "rIIwMe1ObkGh_ByBtTCtRQ",  # 최신 (twspace-crawler 2023.07 기준)
    "V7H0Ap3_Hh2FyS75OCDO3Q",  # 구버전 fallback
    "CdG2Vuc1v6F5JyEngGpxVw",  # 구버전 fallback 2
]

# Space 상태값 (AudioSpaceById 응답의 metadata.state)
SPACE_STATE_RUNNING = "Running"
SPACE_STATE_ENDED = "Ended"
SPACE_STATE_NOT_STARTED = "NotStarted"
