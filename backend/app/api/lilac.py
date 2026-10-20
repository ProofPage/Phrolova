"""Anime Hub API router for Phrolova.

Provides robust, high-speed anime catalog metadata, seasonal trends,
weekly broadcast schedules, multi-facet search, and AniSkip chapter skipping.
Uses AniList GraphQL as primary fast provider with cached fallbacks.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional
import httpx
from fastapi import APIRouter, HTTPException, Query

from app.core.logger import logger

router = APIRouter(prefix="/api/lilac", tags=["anime-hub"])

ANILIST_GRAPHQL = "https://graphql.anilist.co"
ANISKIP_BASE = "https://api.aniskip.com/v2"

# In-memory TTL cache to deliver instant responses
_CACHE: Dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = asyncio.Lock()
DEFAULT_TTL = 300  # 5 minutes
SCHEDULE_TTL = 1800  # 30 minutes


def _current_season() -> tuple[str, int]:
    now = time.gmtime()
    year = now.tm_year
    month = now.tm_mon
    if month in (12, 1, 2):
        season = "WINTER"
    elif month in (3, 4, 5):
        season = "SPRING"
    elif month in (6, 7, 8):
        season = "SUMMER"
    else:
        season = "FALL"
    return season, year


def _format_anilist_media(media: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize AniList media object to standard AnimeItem schema."""
    titles = media.get("title") or {}
    english = titles.get("english")
    romaji = titles.get("romaji")
    native = titles.get("native")
    display_title = english or romaji or native or "Untitled"

    cover = media.get("coverImage") or {}
    banner = media.get("bannerImage")
    large_cover = cover.get("extraLarge") or cover.get("large") or cover.get("medium") or ""

    start_date = media.get("startDate") or {}
    year = start_date.get("year") or media.get("seasonYear")

    trailer_data = media.get("trailer") or {}
    trailer_id = trailer_data.get("id") if trailer_data.get("site") == "youtube" else None
    embed_url = f"https://www.youtube.com/embed/{trailer_id}" if trailer_id else None

    # Score: convert 100-point scale to 10-point
    score = media.get("averageScore")
    normalized_score = round(score / 10.0, 1) if score else None

    genres = [{"mal_id": idx + 1, "name": g} for idx, g in enumerate(media.get("genres") or [])]

    return {
        "mal_id": media.get("idMal") or media.get("id"),
        "anilist_id": media.get("id"),
        "title": display_title,
        "title_english": english or romaji,
        "title_japanese": native or romaji,
        "images": {
            "jpg": {"image_url": large_cover, "large_image_url": large_cover},
            "webp": {"image_url": large_cover, "large_image_url": large_cover},
        },
        "banner_image": banner or large_cover,
        "score": normalized_score,
        "episodes": media.get("episodes"),
        "type": media.get("format") or "TV",
        "status": "Currently Airing" if media.get("status") == "RELEASING" else "Finished Airing",
        "synopsis": (media.get("description") or "").replace("<br>", "\n").replace("<i>", "").replace("</i>", ""),
        "trailer": {
            "youtube_id": trailer_id,
            "embed_url": embed_url,
        },
        "genres": genres,
        "year": year,
        "season": media.get("season"),
    }


async def _anilist_query(query: str, variables: Dict[str, Any], ttl: int = DEFAULT_TTL) -> Any:
    cache_key = f"{query}:{str(sorted(variables.items()))}"
    now = time.monotonic()
    async with _CACHE_LOCK:
        if cache_key in _CACHE:
            ts, data = _CACHE[cache_key]
            if now - ts < ttl:
                return data

    async with httpx.AsyncClient(
        timeout=10.0,
        headers={
            "User-Agent": "Phrolova/2.1.5 (https://github.com/ProofPage/Phrolova)",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    ) as client:
        try:
            resp = await client.post(
                ANILIST_GRAPHQL,
                json={"query": query, "variables": variables},
            )
            resp.raise_for_status()
            res_data = resp.json().get("data", {})
            async with _CACHE_LOCK:
                _CACHE[cache_key] = (now, res_data)
            return res_data
        except Exception as exc:
            logger.warning(f"AniList query failed: {exc}")
            async with _CACHE_LOCK:
                if cache_key in _CACHE:
                    return _CACHE[cache_key][1]
            return {}


@router.get("/home")
async def get_anime_home() -> Dict[str, Any]:
    """Return this season's releases, top popular anime, and today's schedule at lightning speed."""
    season, year = _current_season()

    gql = """
    query ($season: MediaSeason, $seasonYear: Int) {
      seasonMedia: Page(page: 1, perPage: 24) {
        media(season: $season, seasonYear: $seasonYear, type: ANIME, sort: POPULARITY_DESC) {
          id
          idMal
          title { english romaji native }
          coverImage { extraLarge large medium }
          bannerImage
          startDate { year }
          seasonYear
          season
          format
          status
          episodes
          averageScore
          genres
          description(asHtml: false)
          trailer { id site }
        }
      }
      topMedia: Page(page: 1, perPage: 24) {
        media(type: ANIME, sort: SCORE_DESC) {
          id
          idMal
          title { english romaji native }
          coverImage { extraLarge large medium }
          bannerImage
          startDate { year }
          seasonYear
          season
          format
          status
          episodes
          averageScore
          genres
          description(asHtml: false)
          trailer { id site }
        }
      }
    }
    """

    data = await _anilist_query(gql, {"season": season, "seasonYear": year}, ttl=600)
    season_list = [_format_anilist_media(m) for m in data.get("seasonMedia", {}).get("media", [])]
    top_list = [_format_anilist_media(m) for m in data.get("topMedia", {}).get("media", [])]

    # Graceful fallback data if upstream network is completely down
    if not season_list and not top_list:
        season_list = [
            {
                "mal_id": 52991,
                "title": "Frieren: Beyond Journey's End",
                "title_english": "Frieren: Beyond Journey's End",
                "title_japanese": "葬送のフリーレン",
                "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1015/138006l.jpg"}},
                "score": 9.3,
                "episodes": 28,
                "type": "TV",
                "status": "Finished Airing",
                "synopsis": "The adventure is over but life goes on for an elf mage just beginning to learn what living is all about.",
                "genres": [{"mal_id": 1, "name": "Adventure"}, {"mal_id": 2, "name": "Fantasy"}],
                "year": 2023,
            }
        ]

    return {
        "season": season_list,
        "top": top_list,
    }


@router.get("/schedule")
async def get_anime_schedule(day: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Weekly broadcast schedule for anime shows."""
    # AniList AiringSchedule
    gql = """
    query {
      Page(page: 1, perPage: 40) {
        airingSchedules(notYetAired: false, sort: TIME_DESC) {
          id
          airingAt
          timeUntilAiring
          episode
          media {
            id
            idMal
            title { english romaji native }
            coverImage { extraLarge large medium }
            bannerImage
            format
            status
            episodes
            averageScore
            genres
            description(asHtml: false)
            trailer { id site }
          }
        }
      }
    }
    """
    data = await _anilist_query(gql, {}, ttl=SCHEDULE_TTL)
    schedules = data.get("Page", {}).get("airingSchedules", [])
    seen = set()
    items = []
    for s in schedules:
        m = s.get("media")
        if m and m.get("id") not in seen:
            seen.add(m.get("id"))
            items.append(_format_anilist_media(m))

    return {"schedule": items}


@router.get("/search")
async def search_anime(
    q: str = Query("", description="Search keywords"),
    genre: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    order_by: str = Query("popularity"),
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=50),
) -> Dict[str, Any]:
    """Search catalog with multi-facet filters."""
    sort_map = {
        "popularity": "POPULARITY_DESC",
        "score": "SCORE_DESC",
        "title": "TITLE_ENGLISH_DESC",
    }
    sort_val = sort_map.get(order_by, "POPULARITY_DESC")

    variables: Dict[str, Any] = {
        "page": page,
        "perPage": limit,
        "sort": sort_val,
    }
    if q.strip():
        variables["search"] = q.strip()
    if genre:
        variables["genre"] = genre
    if type:
        format_map = {"tv": "TV", "movie": "MOVIE", "ova": "OVA", "ona": "ONA", "special": "SPECIAL"}
        if type.lower() in format_map:
            variables["format"] = format_map[type.lower()]
    if status:
        status_map = {"airing": "RELEASING", "complete": "FINISHED", "upcoming": "NOT_YET_RELEASED"}
        if status.lower() in status_map:
            variables["status"] = status_map[status.lower()]

    gql = """
    query ($page: Int, $perPage: Int, $search: String, $sort: [MediaSort], $genre: String, $format: MediaFormat, $status: MediaStatus) {
      Page(page: $page, perPage: $perPage) {
        pageInfo {
          hasNextPage
          total
        }
        media(search: $search, sort: $sort, genre: $genre, format: $format, status: $status, type: ANIME) {
          id
          idMal
          title { english romaji native }
          coverImage { extraLarge large medium }
          bannerImage
          startDate { year }
          seasonYear
          season
          format
          status
          episodes
          averageScore
          genres
          description(asHtml: false)
          trailer { id site }
        }
      }
    }
    """
    data = await _anilist_query(gql, variables, ttl=300)
    page_info = data.get("Page", {}).get("pageInfo", {})
    results = [_format_anilist_media(m) for m in data.get("Page", {}).get("media", [])]

    return {
        "results": results,
        "pagination": {
            "has_next_page": page_info.get("hasNextPage", False),
            "total": page_info.get("total", len(results)),
        },
    }


@router.get("/anime/{anime_id}")
async def get_anime_detail(anime_id: int) -> Dict[str, Any]:
    """Full detail metadata of an anime."""
    gql = """
    query ($id: Int) {
      Media(id: $id, type: ANIME) {
        id
        idMal
        title { english romaji native }
        coverImage { extraLarge large medium }
        bannerImage
        startDate { year }
        seasonYear
        season
        format
        status
        episodes
        averageScore
        genres
        description(asHtml: false)
        trailer { id site }
      }
    }
    """
    data = await _anilist_query(gql, {"id": anime_id}, ttl=1800)
    media = data.get("Media")
    if not media:
        # Try idMal if not found
        gql_mal = """
        query ($idMal: Int) {
          Media(idMal: $idMal, type: ANIME) {
            id
            idMal
            title { english romaji native }
            coverImage { extraLarge large medium }
            bannerImage
            startDate { year }
            seasonYear
            season
            format
            status
            episodes
            averageScore
            genres
            description(asHtml: false)
            trailer { id site }
          }
        }
        """
        data = await _anilist_query(gql_mal, {"idMal": anime_id}, ttl=1800)
        media = data.get("Media")

    return {"anime": _format_anilist_media(media) if media else {}}


@router.get("/skip-times/{mal_id}/{episode}")
async def get_skip_times(
    mal_id: int,
    episode: int,
    duration: float = Query(0.0, description="Video duration in seconds"),
) -> Dict[str, Any]:
    """Fetch AniSkip intro/outro timestamp intervals for automated skipping."""
    types = ["op", "ed", "mixed-op", "mixed-ed", "recap"]
    query_parts = [f"types[]={t}" for t in types]
    query_parts.append(f"episodeLength={max(0, round(duration))}")
    url = f"{ANISKIP_BASE}/skip-times/{mal_id}/{episode}?{'&'.join(query_parts)}"

    try:
        async with httpx.AsyncClient(timeout=6.0, headers={"User-Agent": "Phrolova/2.1.5"}) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                body = resp.json()
                results = body.get("results", [])
                intervals = []
                for item in results:
                    interval = item.get("interval", item)
                    intervals.append(
                        {
                            "type": item.get("skipType", ""),
                            "startTime": float(interval.get("startTime", 0.0)),
                            "endTime": float(interval.get("endTime", 0.0)),
                        }
                    )
                return {"found": True, "results": intervals}
            return {"found": False, "results": []}
    except Exception as exc:
        logger.debug(f"AniSkip request failed for {mal_id}/{episode}: {exc}")
        return {"found": False, "results": []}

