"""Anime Hub API router for Phrolova.

Provides robust, high-speed anime catalog metadata, seasonal trends,
weekly broadcast schedules, multi-facet search, and AniSkip chapter skipping.
Uses AniList GraphQL as primary fast provider with cached fallbacks.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional
import httpx
from fastapi import APIRouter, HTTPException, Query, Request

from app.core.config import get_settings
from app.core.file_browser import reveal
from app.core.logger import logger

router = APIRouter(prefix="/api/lilac", tags=["anime-hub"])

ANILIST_GRAPHQL = "https://graphql.anilist.co/"
ANISKIP_BASE = "https://api.aniskip.com/v2"

# In-memory TTL cache to deliver instant responses
_CACHE: Dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = asyncio.Lock()
DEFAULT_TTL = 300  # 5 minutes
SCHEDULE_TTL = 1800  # 30 minutes

# Comprehensive Korean title translation mapping dictionary for international catalogs
KOREAN_TITLE_MAP: Dict[str, str] = {
    "the apothecary diaries season 3": "약사의 혼잣말 3기",
    "the apothecary diaries season 2": "약사의 혼잣말 2기",
    "the apothecary diaries": "약사의 혼잣말",
    "kusuriya no hitorigoto 3": "약사의 혼잣말 3기",
    "kusuriya no hitorigoto": "약사의 혼잣말",
    "frieren: beyond journey's end": "장송의 프리렌",
    "frieren": "장송의 프리렌",
    "sousou no frieren": "장송의 프리렌",
    "blue box season 2": "푸른 상자 2기",
    "blue box": "푸른 상자",
    "ao no hako season 2": "푸른 상자 2기",
    "ao no hako": "푸른 상자",
    "black clover season 2": "블랙 클로버 2기",
    "black clover": "블랙 클로버",
    "cyberpunk: edgerunners 2": "사이버펑크: 엣지러너 2",
    "cyberpunk: edgerunners": "사이버펑크: 엣지러너",
    "reincarnated as a sword season 2": "환생했더니 검이었습니다 2기",
    "reincarnated as a sword": "환생했더니 검이었습니다",
    "steel ball run": "죠죠의 기묘한 모험 Part 7 스틸 볼 런",
    "made in abyss: mezameru shinpi": "메이드 인 어비스: 눈을 뜨는 신비",
    "made in abyss": "메이드 인 어비스",
    "gintama: the very final": "은혼 THE FINAL",
    "gintama season 3": "은혼 3기",
    "gintama": "은혼",
    "re:zero -starting life in another world-": "Re: 제로부터 시작하는 이세계 생활",
    "re:zero": "Re: 제로부터 시작하는 이세계 생활",
    "chainsaw man - the movie: reze arc": "체인소 맨 극장판: 레제편",
    "chainsaw man": "체인소 맨",
    "fullmetal alchemist: brotherhood": "강철의 연금술사 BROTHERHOOD",
    "fullmetal alchemist": "강철의 연금술사",
    "attack on titan season 3 part 2": "진격의 거인 3기 파트 2",
    "attack on titan": "진격의 거인",
    "shingeki no kyojin": "진격의 거인",
    "magical sisters luluttolilly part 2": "마법소녀 루루토릴리 2기",
    "magical sisters luluttolilly": "마법소녀 루루토릴리",
    "uncle's obsession with cute things": "아저씨는 귀여운 것이 좋아",
    "bleach: thousand-year blood war - the calamity": "블리치 천년혈전 편 : 화진담",
    "bleach: thousand-year blood war": "블리치 천년혈전 편",
    "bleach": "블리치",
    "psyren": "사이렌 (PSYREN)",
    "jujutsu kaisen": "주술회전",
    "demon slayer: kimetsu no yaiba": "귀멸의 칼날",
    "kimetsu no yaiba": "귀멸의 칼날",
    "oshi no ko": "최애의 아이",
    "solo leveling season 2": "나 혼자만 레벨업 2기",
    "solo leveling": "나 혼자만 레벨업",
    "dandadan": "단다단",
    "bocchi the rock!": "봇치 더 록!",
    "spy x family": "스파이 패밀리",
    "mushoku tensei: jobless reincarnation": "무직전생 ~이세계에 갔으면 최선을 다한다~",
    "mushoku tensei": "무직전생",
    "my hero academia": "나의 히어로 아카데미아",
    "one piece": "원피스",
    "naruto": "나루토",
    "boruto": "보루토",
    "overgeared": "템빨",
    "dragon ball super: beerus": "드래곤볼 슈퍼: 비루스",
    "tank chair": "탱크 체어",
    "renegade immortal": "선역 (Renegade Immortal)",
    "haikyu!! karasuno": "하이큐!! 카라스노",
    "haikyu!!": "하이큐!!",
}

def _localize_title(raw_title: str) -> str:
    cleaned = raw_title.strip().lower()
    return KOREAN_TITLE_MAP.get(cleaned, raw_title)

KOREAN_SYNOPSIS_MAP: Dict[str, str] = {
    "약사의 혼잣말": "후궁의 독살 미수 사건을 해결한 마오마오에게 새로운 음모의 그림자가 다가온다.",
    "장송의 프리렌": "마왕을 토벌한 용사 일행의 마법사 프리렌이 사람의 마음을 알아가는 따뜻한 후일담.",
    "푸른 상자": "배드민턴부의 이노마타 타이키와 농구부의 카노 치나츠의 풋풋한 청춘 러브 스토리.",
    "블랙 클로버": "마법제에 도전하는 아스타와 유노의 장대한 마법 판타지 배틀.",
    "사이버펑크": "나이트 시티의 뒷골목을 질주하는 새로운 용병들의 거친 생존기.",
    "환생했더니 검이었습니다": "지능을 가진 마검으로 전생한 주인공과 수인 소녀 프란의 모험기.",
    "체인소 맨": "체인소의 악마 포치타와 계약하여 데빌 헌터로 살아가는 덴지의 다크 액션.",
    "은혼": "해결사 긴토키와 동료들이 펼치는 유쾌하고 감동적인 SF 에도 활극.",
    "Re: 제로부터 시작하는 이세계 생활": "소중한 사람들을 지키기 위해 사망회귀로 절망을 극복하는 스바루의 사투.",
    "강철의 연금술사": "잃어버린 몸을 되찾기 위해 현자의 돌을 찾는 엘릭 형제의 장대한 여정.",
    "진격의 거인": "벽 안의 인류를 위협하는 거인들의 비밀과 자유를 향한 인류의 처절한 싸움.",
}

def _localize_synopsis(display_title: str, raw_synopsis: str) -> str:
    for ko_key, ko_syn in KOREAN_SYNOPSIS_MAP.items():
        if ko_key in display_title:
            return ko_syn
    return raw_synopsis or ""


def _current_season() -> tuple[str, int]:
    now = time.gmtime()
    year = now.tm_year
    month = now.tm_mon
    if month in (1, 2, 3):
        season = "WINTER"
    elif month in (4, 5, 6):
        season = "SPRING"
    elif month in (7, 8, 9):
        season = "SUMMER"
    else:
        season = "FALL"
    return season, year


def _format_anilist_media(media: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize AniList media object to standard AnimeItem schema with Korean localization."""
    titles = media.get("title") or {}
    english = titles.get("english")
    romaji = titles.get("romaji")
    native = titles.get("native")

    # Priority: Korean localized title -> English -> Romaji -> Native
    base_title = english or romaji or native or "Untitled"
    display_title = _localize_title(base_title)

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
        "title_korean": display_title,
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
        "status": {"RELEASING": "Currently Airing", "NOT_YET_RELEASED": "Not yet aired",
                   "FINISHED": "Finished Airing", "CANCELLED": "Cancelled",
                   "HIATUS": "On hiatus"}.get(media.get("status"), "Unknown"),
        "synopsis": _localize_synopsis(display_title, (media.get("description") or "").replace("<br>", "\n").replace("<i>", "").replace("</i>", "")),
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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://anilist.co",
            "Referer": "https://anilist.co/",
        },
        follow_redirects=True,
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
async def get_anime_home(source: str = Query("reanime", description="Content source provider")) -> Dict[str, Any]:
    """Return this season's releases, top popular anime, and today's schedule at lightning speed."""
    # Metadata is independent from a playback provider. Never fabricate site
    # catalogs, scores or provider IDs and present them as MAL identifiers.

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

    return {
        "season": season_list,
        "top": top_list,
        "catalog_source": "anilist",
        "availability_verified": False,
    }


@router.post("/open-folder")
async def open_anime_folder(request: Request) -> Dict[str, Any]:
    """Open the VOD downloads folder on the host machine using Windows Explorer."""
    settings = get_settings()
    folder_str = settings.vod_download_dir or settings.download_dir
    folder = Path(folder_str).resolve()
    folder.mkdir(parents=True, exist_ok=True)

    opened = await asyncio.to_thread(reveal, folder)
    return {
        "success": bool(opened),
        "path": str(folder),
        "message": "저장 폴더를 열었습니다." if opened else f"저장 위치: {folder}",
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
    q: str = "",
    genre: Optional[str] = None,
    type: Optional[str] = None,
    status: Optional[str] = None,
    order_by: str = "popularity",
    page: int = 1,
    limit: int = 24,
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
    if q and isinstance(q, str) and q.strip():
        variables["search"] = q.strip()
    if genre and isinstance(genre, str):
        variables["genre"] = genre
    if type and isinstance(type, str):
        format_map = {"tv": "TV", "movie": "MOVIE", "ova": "OVA", "ona": "ONA", "special": "SPECIAL"}
        if type.lower() in format_map:
            variables["format"] = format_map[type.lower()]
    if status and isinstance(status, str):
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
async def get_anime_detail(anime_id: int, id_type: str = "anilist") -> Dict[str, Any]:
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
    if id_type not in ("anilist", "mal"):
        raise HTTPException(status_code=400, detail="지원하지 않는 작품 ID 형식입니다.")
    if id_type == "mal":
        gql = gql.replace("$id: Int", "$idMal: Int").replace("Media(id: $id,", "Media(idMal: $idMal,")
    data = await _anilist_query(gql, {"idMal" if id_type == "mal" else "id": anime_id}, ttl=1800)
    media = data.get("Media")
    if not media and id_type == "anilist":
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


@router.get("/stream")
async def get_anime_stream(
    title: str = "",
    episode: int = 1,
    anilist_id: Optional[int] = None,
    mal_id: Optional[int] = None,
    source: str = "reanime",
    source_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve video player or HLS stream URL for the selected anime and episode."""
    if source_url:
        try:
            from app.engine.episode_sites import parse_episode_url, extract_episode, EpisodeSiteError
            route = parse_episode_url(source_url)
            if route["site"] != source or route["collection"]:
                raise EpisodeSiteError("선택한 소스의 실제 회차 주소가 필요합니다.")
            res = await asyncio.to_thread(extract_episode, route["url"])
            link = res.get("stream_url") or res.get("url")
            if link:
                return {"success": True, "stream_url": link, "is_embed": bool(res.get("is_embed")),
                        "source": source, "server": source}
        except (ValueError, httpx.HTTPError):
            pass
        return {"success": False, "stream_url": None, "source": source,
                "message": "선택한 소스의 실제 회차를 확인할 수 없습니다."}
    if source != "reanime":
        return {"success": False, "stream_url": None, "source": source,
                "message": "작품 ID만으로 해당 소스의 회차를 확인할 수 없습니다. 실제 회차 주소를 사용하세요."}

    # 1. Direct query to Re:Anime flix API if anilist_id is provided
    if anilist_id:
        try:
            flix_url = f"https://reanime.to/api/flix/{anilist_id}/{episode}"
            async with httpx.AsyncClient(
                timeout=8.0,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://reanime.to/",
                },
            ) as http_client:
                res = await http_client.get(flix_url)
                if res.status_code == 200:
                    data = res.json()
                    servers = data.get("servers", [])
                    chosen = next(
                        (s for s in servers if s.get("dataType") == "sub" and "HD" in s.get("serverName", "")),
                        next((s for s in servers if s.get("dataType") == "sub"), servers[0] if servers else None)
                    )
                    if chosen:
                        link = chosen.get("dataLink") or chosen.get("link") or ""
                        if link:
                            return {
                                "success": True,
                                "stream_url": link,
                                "is_embed": "flixcloud.cc" in link,
                                "source": "reanime",
                                "server": chosen.get("serverName", "HD-1"),
                            }
        except Exception as exc:
            logger.debug(f"Re:Anime flix lookup failed for anilist_id {anilist_id}: {exc}")

    # 3. Try searching by title in Re:Anime
    try:
        from app.engine.episode_sites import SiteClient
        from app.engine.reanime import parse_reanime_url, extract_reanime_episode

        search_q = httpx.URL("", params={"q": title}).query.decode("utf-8").split("q=")[-1]
        search_url = f"https://reanime.to/api/v1/search?q={search_q}&limit=5"
        async with httpx.AsyncClient(
            timeout=8.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://reanime.to/search",
            },
        ) as http_client:
            s_res = await http_client.get(search_url)
            if s_res.status_code == 200:
                s_data = s_res.json()
                items = s_data.get("data", [])
                matching = [item for item in items if isinstance(item.get("title"), str)
                            and item["title"].strip().casefold() == title.strip().casefold()]
                if len(matching) == 1:
                    target_id = matching[0].get("id")
                    if target_id:
                        watch_url = f"https://reanime.to/watch/{target_id}?ep={episode}"
                        client = SiteClient()
                        try:
                            route = parse_reanime_url(watch_url)
                            extracted = extract_reanime_episode(route, client)
                            video_url = extracted.get("url")
                            if video_url:
                                return {
                                    "success": True,
                                    "stream_url": video_url,
                                    "is_embed": "flixcloud.cc" in video_url,
                                    "source": "reanime",
                                    "server": "HD",
                                }
                        finally:
                            client.close()
    except Exception as exc:
        logger.debug(f"Re:Anime search resolution failed for {title}: {exc}")

    return {
        "success": False,
        "message": "해당 회차의 스트림을 외부 서버에서 찾을 수 없습니다. Phrolova 다운로드 큐를 이용해 보세요.",
        "stream_url": None,
    }


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

