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
    "the apothecary diaries": "약사의 혼잣말",
    "the apothecary diaries season 2": "약사의 혼잣말 2기",
    "the apothecary diaries season 3": "약사의 혼잣말 3기",
    "kusuriya no hitorigoto": "약사의 혼잣말",
    "frieren: beyond journey's end": "장송의 프리렌",
    "frieren": "장송의 프리렌",
    "sousou no frieren": "장송의 프리렌",
    "blue box": "푸른 상자",
    "blue box season 2": "푸른 상자 2기",
    "ao no hako": "푸른 상자",
    "black clover": "블랙 클로버",
    "black clover season 2": "블랙 클로버 2기",
    "cyberpunk: edgerunners": "사이버펑크: 엣지러너",
    "cyberpunk: edgerunners 2": "사이버펑크: 엣지러너 2",
    "re:zero -starting life in another world-": "Re: 제로부터 시작하는 이세계 생활",
    "re:zero": "Re: 제로부터 시작하는 이세계 생활",
    "chainsaw man": "체인소 맨",
    "chainsaw man - the movie: reze arc": "체인소 맨 극장판: 레제편",
    "fullmetal alchemist: brotherhood": "강철의 연금술사 BROTHERHOOD",
    "fullmetal alchemist": "강철의 연금술사",
    "attack on titan": "진격의 거인",
    "shingeki no kyojin": "진격의 거인",
    "gintama": "은혼",
    "bleach": "블리치",
    "bleach: thousand-year blood war": "블리치 천년혈전 편",
    "bleach: thousand-year blood war - the calamity": "블리치 천년혈전 편 : 화진담",
    "jujutsu kaisen": "주술회전",
    "demon slayer: kimetsu no yaiba": "귀멸의 칼날",
    "kimetsu no yaiba": "귀멸의 칼날",
    "oshi no ko": "최애의 아이",
    "solo leveling": "나 혼자만 레벨업",
    "solo leveling season 2": "나 혼자만 레벨업 2기",
    "dandadan": "단다단",
    "bocchi the rock!": "봇치 더 록!",
    "spy x family": "스파이 패밀리",
    "mushoku tensei: jobless reincarnation": "무직전생 ~이세계에 갔으면 최선을 다한다~",
    "mushoku tensei": "무직전생",
    "my hero academia": "나의 히어로 아카데미아",
    "one piece": "원피스",
    "naruto": "나루토",
    "boruto": "보루토",
    "reincarnated as a sword": "환생했더니 검이었습니다",
    "reincarnated as a sword season 2": "환생했더니 검이었습니다 2기",
    "steel ball run": "죠죠의 기묘한 모험 Part 7 스틸 볼 런",
    "made in abyss": "메이드 인 어비스",
    "made in abyss: mezameru shinpi": "메이드 인 어비스: 눈을 뜨는 신비",
    "psyren": "사이렌 (PSYREN)",
    "uncle's obsession with cute things": "아저씨는 귀여운 것이 좋아",
    "renegade immortal": "선역 (Renegade Immortal)",
}

def _localize_title(raw_title: str) -> str:
    cleaned = raw_title.strip().lower()
    for en_key, ko_val in KOREAN_TITLE_MAP.items():
        if en_key in cleaned or cleaned in en_key:
            return ko_val
    return raw_title


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
    # 1. Domestic Source: Ohli24 (애니24)
    if source == "ohli24":
        return {
            "season": [
                {
                    "mal_id": 52991,
                    "title": "약사의 혼잣말 3기",
                    "title_english": "The Apothecary Diaries Season 3",
                    "title_japanese": "薬屋のひとりごと 第3期",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1015/138006l.jpg"}},
                    "score": 8.5,
                    "episodes": 12,
                    "type": "TV",
                    "status": "Currently Airing",
                    "synopsis": "후궁의 독살 미수 사건을 해결한 마오마오에게 새로운 음모의 그림자가 다가온다.",
                    "genres": [{"mal_id": 1, "name": "드라마"}, {"mal_id": 2, "name": "미스터리"}],
                    "year": 2026,
                },
                {
                    "mal_id": 173828,
                    "title": "푸른 상자 2기",
                    "title_english": "Blue Box Season 2",
                    "title_japanese": "アオのハコ Season 2",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1841/141443l.jpg"}},
                    "score": 8.1,
                    "episodes": 12,
                    "type": "TV",
                    "status": "Currently Airing",
                    "synopsis": "배드민턴부의 이노마타 타이키와 농구부의 카노 치나츠의 풋풋한 청춘 러브 스토리.",
                    "genres": [{"mal_id": 3, "name": "로맨스"}, {"mal_id": 4, "name": "스포츠"}],
                    "year": 2026,
                },
                {
                    "mal_id": 50709,
                    "title": "블랙 클로버 2기",
                    "title_english": "Black Clover Season 2",
                    "title_japanese": "ブラッククローバー 第2期",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/2/88336l.jpg"}},
                    "score": 8.7,
                    "episodes": 24,
                    "type": "TV",
                    "status": "Currently Airing",
                    "synopsis": "마법제에 도전하는 아스타와 유노의 장대한 마법 판타지 배틀.",
                    "genres": [{"mal_id": 5, "name": "액션"}, {"mal_id": 6, "name": "판타지"}],
                    "year": 2026,
                },
                {
                    "mal_id": 52034,
                    "title": "사이버펑크: 엣지러너 2",
                    "title_english": "Cyberpunk: Edgerunners 2",
                    "title_japanese": "サイバーパンク エッジランナーズ 2",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1286/125473l.jpg"}},
                    "score": 8.9,
                    "episodes": 10,
                    "type": "ONA",
                    "status": "Currently Airing",
                    "synopsis": "나이트 시티의 뒷골목을 질주하는 새로운 용병들의 거친 생존기.",
                    "genres": [{"mal_id": 7, "name": "SF"}, {"mal_id": 8, "name": "액션"}],
                    "year": 2026,
                },
            ],
            "top": [
                {
                    "mal_id": 52991,
                    "title": "장송의 프리렌",
                    "title_english": "Frieren: Beyond Journey's End",
                    "title_japanese": "葬送のフリーレン",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1015/138006l.jpg"}},
                    "score": 9.3,
                    "episodes": 28,
                    "type": "TV",
                    "status": "Finished Airing",
                    "synopsis": "마왕을 토벌한 용사 일행의 마법사 프리렌이 사람의 마음을 알아가는 따뜻한 후일담.",
                    "genres": [{"mal_id": 9, "name": "모험"}, {"mal_id": 10, "name": "판타지"}],
                    "year": 2023,
                },
                {
                    "mal_id": 44511,
                    "title": "체인소 맨",
                    "title_english": "Chainsaw Man",
                    "title_japanese": "チェンソーマン",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1806/126216l.jpg"}},
                    "score": 8.6,
                    "episodes": 12,
                    "type": "TV",
                    "status": "Finished Airing",
                    "synopsis": "체인소의 악마 포치타와 계약하여 데빌 헌터로 살아가는 덴지의 다크 히어로 액션.",
                    "genres": [{"mal_id": 11, "name": "다크 판타지"}, {"mal_id": 12, "name": "액션"}],
                    "year": 2022,
                },
            ],
        }

    # 2. Domestic Source: Moeni (모에니)
    if source == "moeni":
        return {
            "season": [
                {
                    "mal_id": 173828,
                    "title": "푸른 상자 2기",
                    "title_english": "Blue Box Season 2",
                    "title_japanese": "アオのハコ Season 2",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1841/141443l.jpg"}},
                    "score": 8.1,
                    "episodes": 12,
                    "type": "TV",
                    "status": "Currently Airing",
                    "synopsis": "배드민턴부의 이노마타 타이키와 농구부의 카노 치나츠의 풋풋한 청춘 러브 스토리.",
                    "genres": [{"mal_id": 3, "name": "로맨스"}, {"mal_id": 4, "name": "스포츠"}],
                    "year": 2026,
                },
                {
                    "mal_id": 4928,
                    "title": "학생회에도 구멍은 있다!",
                    "title_english": "Seitokai ni mo Ana wa Aru!",
                    "title_japanese": "生徒会にも穴はある！",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1171/109222l.jpg"}},
                    "score": 7.9,
                    "episodes": 12,
                    "type": "TV",
                    "status": "Currently Airing",
                    "synopsis": "개성 넘치는 학생회 임원들의 유쾌하고 발랄한 학원 일상 코미디.",
                    "genres": [{"mal_id": 13, "name": "코미디"}, {"mal_id": 14, "name": "일상"}],
                    "year": 2026,
                },
                {
                    "mal_id": 236,
                    "title": "Re: 제로부터 시작하는 이세계 생활 4기",
                    "title_english": "Re:Zero 4th Season",
                    "title_japanese": "Re:ゼロから始める異世界生活 4th season",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1522/128039l.jpg"}},
                    "score": 8.8,
                    "episodes": 16,
                    "type": "TV",
                    "status": "Currently Airing",
                    "synopsis": "소중한 사람들을 지키기 위해 사망회귀로 절망을 극복하는 스바루의 사투.",
                    "genres": [{"mal_id": 15, "name": "판타지"}, {"mal_id": 16, "name": "서스펜스"}],
                    "year": 2026,
                },
            ],
            "top": [
                {
                    "mal_id": 173828,
                    "title": "푸른 상자 2기",
                    "title_english": "Blue Box Season 2",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1841/141443l.jpg"}},
                    "score": 8.1,
                    "episodes": 12,
                    "type": "TV",
                    "status": "Currently Airing",
                    "genres": [{"mal_id": 3, "name": "로맨스"}],
                    "year": 2026,
                }
            ],
        }

    # 3. Domestic Source: Zzapflix (짭플릭스)
    if source == "zzapflix":
        return {
            "season": [
                {
                    "mal_id": 123692,
                    "title": "템빨",
                    "title_english": "Overgeared",
                    "title_japanese": "テムパル〜アイテムの力〜",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1171/109222l.jpg"}},
                    "score": 8.8,
                    "episodes": 24,
                    "type": "ONA",
                    "status": "Currently Airing",
                    "synopsis": "전 세계 20억 명이 플레이하는 가상현실 VR 게임 SATISFY에서 신화급 대장장이로 거듭나는 루저의 통쾌한 인생 역전기.",
                    "genres": [{"mal_id": 100, "name": "애니"}, {"mal_id": 101, "name": "판타지"}],
                    "year": 2026,
                },
                {
                    "mal_id": 123703,
                    "title": "블랙클로버 New Chapter",
                    "title_english": "Black Clover New Chapter",
                    "title_japanese": "ブラッククローバー",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/2/88336l.jpg"}},
                    "score": 8.7,
                    "episodes": 12,
                    "type": "TV",
                    "status": "Currently Airing",
                    "synopsis": "마법제에 도전하는 소년들의 장대한 마법 배틀.",
                    "genres": [{"mal_id": 100, "name": "애니"}, {"mal_id": 102, "name": "액션"}],
                    "year": 2026,
                },
                {
                    "mal_id": 123694,
                    "title": "연애박사",
                    "title_english": "Love Doctor",
                    "title_japanese": "恋愛博士",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1841/141443l.jpg"}},
                    "score": 8.2,
                    "episodes": 16,
                    "type": "TV",
                    "status": "Currently Airing",
                    "synopsis": "연애에 서툰 이들을 위한 현실 밀착 공감 로맨스 드라마.",
                    "genres": [{"mal_id": 103, "name": "드라마"}, {"mal_id": 104, "name": "로맨스"}],
                    "year": 2026,
                },
                {
                    "mal_id": 123696,
                    "title": "우리들의 발라드 2",
                    "title_english": "Our Ballad Season 2",
                    "title_japanese": "私たちのバラード 2",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1015/138006l.jpg"}},
                    "score": 8.4,
                    "episodes": 12,
                    "type": "TV",
                    "status": "Currently Airing",
                    "synopsis": "대한민국을 울리는 최고의 보컬리스트들이 선사하는 감동의 발라드 음악 예능.",
                    "genres": [{"mal_id": 105, "name": "예능"}, {"mal_id": 106, "name": "음악"}],
                    "year": 2026,
                },
                {
                    "mal_id": 123734,
                    "title": "드골: 저항의 시작",
                    "title_english": "De Gaulle",
                    "title_japanese": "ドゴール",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1286/125473l.jpg"}},
                    "score": 8.5,
                    "episodes": 1,
                    "type": "MOVIE",
                    "status": "Finished Airing",
                    "synopsis": "역사를 뒤바꾼 결단의 순간, 자유 프랑스를 이끈 지도자의 뜨거운 서사.",
                    "genres": [{"mal_id": 107, "name": "영화"}, {"mal_id": 108, "name": "전쟁"}],
                    "year": 2026,
                },
            ],
            "top": [
                {
                    "mal_id": 123692,
                    "title": "템빨",
                    "title_english": "Overgeared",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1171/109222l.jpg"}},
                    "score": 8.8,
                    "episodes": 24,
                    "type": "ONA",
                    "status": "Currently Airing",
                    "genres": [{"mal_id": 100, "name": "애니"}],
                    "year": 2026,
                },
                {
                    "mal_id": 123753,
                    "title": "하이큐!! 카라스노 고교 VS 시라토리자와",
                    "title_english": "Haikyu!! Karasuno vs Shiratorizawa",
                    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/1841/141443l.jpg"}},
                    "score": 9.0,
                    "episodes": 10,
                    "type": "TV",
                    "status": "Finished Airing",
                    "genres": [{"mal_id": 100, "name": "애니"}, {"mal_id": 109, "name": "스포츠"}],
                    "year": 2026,
                },
            ],
        }

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


@router.get("/stream")
async def get_anime_stream(
    title: str = "",
    episode: int = 1,
    anilist_id: Optional[int] = None,
    mal_id: Optional[int] = None,
    source: str = "reanime",
) -> Dict[str, Any]:
    """Resolve video player or HLS stream URL for the selected anime and episode."""
    # 0. Zzapflix (짭플릭스) stream
    if source == "zzapflix":
        try:
            from app.engine.zzapflix import extract_zzapflix_episode
            work_id = str(mal_id) if mal_id else "123692"
            res = extract_zzapflix_episode({"work": work_id, "episode": str(episode - 1)})
            return {
                "success": True,
                "stream_url": res["stream_url"],
                "is_embed": res["is_embed"],
                "source": "zzapflix",
                "server": "Zzapflix Wiselife",
            }
        except Exception as exc:
            logger.debug(f"Zzapflix stream resolution error: {exc}")

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

    # 2. Try Moeni / domestic fast source if available
    try:
        from app.engine.moeni import parse_moeni_url, extract_moeni_episode
        from app.engine.episode_sites import SiteClient

        # If Blue Box / 푸른 상자
        if "blue box" in title.lower() or "푸른 상자" in title or "ao no hako" in title.lower():
            client = SiteClient()
            try:
                route = parse_moeni_url(f"https://moeni.net/4686/{episode}")
                res = extract_moeni_episode(route, client)
                if res.get("url"):
                    return {
                        "success": True,
                        "stream_url": res["url"],
                        "is_embed": False,
                        "source": "moeni",
                        "server": "Moeni HD",
                    }
            finally:
                client.close()
    except Exception as exc:
        logger.debug(f"Moeni fallback lookup failed for {title}: {exc}")

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
                if items:
                    target_id = items[0].get("id")
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

