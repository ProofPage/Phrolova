"""LilacAnime API router for Phrolova.

Provides anime catalog metadata, seasonal trends, weekly broadcast schedules,
search, detailed information, and AniSkip intro/outro skip intervals.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional
import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.logger import logger

router = APIRouter(prefix="/api/lilac", tags=["lilac"])

JIKAN_BASE = "https://api.jikan.moe/v4"
ANISKIP_BASE = "https://api.aniskip.com/v2"

# In-memory LRU-like TTL cache to avoid spamming public endpoints
_CACHE: Dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = asyncio.Lock()
DEFAULT_TTL = 300  # 5 minutes
SCHEDULE_TTL = 1800  # 30 minutes


async def _fetch_cached(url: str, ttl: int = DEFAULT_TTL, timeout: float = 12.0) -> Any:
    now = time.monotonic()
    async with _CACHE_LOCK:
        if url in _CACHE:
            ts, data = _CACHE[url]
            if now - ts < ttl:
                return data

    async with httpx.AsyncClient(
        timeout=timeout,
        headers={
            "User-Agent": "Phrolova-LilacAnime/2.1.4 (https://github.com/ProofPage/Phrolova)",
            "Accept": "application/json",
        },
        follow_redirects=True,
    ) as client:
        try:
            resp = await client.get(url)
            if resp.status_code == 429:
                # Rate limited: return stale cache if available
                async with _CACHE_LOCK:
                    if url in _CACHE:
                        return _CACHE[url][1]
                raise HTTPException(status_code=429, detail="Upstream rate limit exceeded")
            resp.raise_for_status()
            data = resp.json()
            async with _CACHE_LOCK:
                _CACHE[url] = (now, data)
            return data
        except httpx.HTTPError as exc:
            logger.warning(f"Lilac upstream request failed [{url}]: {exc}")
            async with _CACHE_LOCK:
                if url in _CACHE:
                    return _CACHE[url][1]
            raise HTTPException(status_code=502, detail=f"Upstream provider error: {exc}")


@router.get("/home")
async def get_lilac_home() -> Dict[str, Any]:
    """Home view aggregating current seasonal releases, top popular anime, and today's schedule."""
    season_url = f"{JIKAN_BASE}/seasons/now?limit=20&sfw=true"
    top_url = f"{JIKAN_BASE}/top/anime?filter=bypopularity&limit=20&sfw=true"

    try:
        season_res, top_res = await asyncio.gather(
            _fetch_cached(season_url, ttl=600),
            _fetch_cached(top_url, ttl=1800),
            return_exceptions=True,
        )

        season_items = season_res.get("data", []) if isinstance(season_res, dict) else []
        top_items = top_res.get("data", []) if isinstance(top_res, dict) else []

        return {
            "season": season_items,
            "top": top_items,
        }
    except Exception as exc:
        logger.error(f"Failed to load LilacAnime home: {exc}")
        return {"season": [], "top": []}


@router.get("/schedule")
async def get_lilac_schedule(day: Optional[str] = Query(None, description="monday, tuesday, etc.")) -> Dict[str, Any]:
    """Weekly broadcast schedule for anime shows."""
    url = f"{JIKAN_BASE}/schedules?sfw=true"
    if day:
        url += f"&filter={day.lower()}"

    data = await _fetch_cached(url, ttl=SCHEDULE_TTL)
    return {"schedule": data.get("data", [])}


@router.get("/search")
async def search_lilac_anime(
    q: str = Query("", description="Search keywords"),
    genre: Optional[str] = Query(None),
    type: Optional[str] = Query(None, description="tv, movie, ova, etc."),
    status: Optional[str] = Query(None, description="airing, complete, upcoming"),
    order_by: str = Query("popularity", description="popularity, score, title"),
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=50),
) -> Dict[str, Any]:
    """Search anime catalog with multi-facet filters."""
    params = [f"page={page}", f"limit={limit}", "sfw=true"]
    if q.strip():
        params.append(f"q={httpx.URL('', params={'q': q}).query.decode('utf-8').split('q=')[-1]}")
    if genre:
        params.append(f"genres={genre}")
    if type:
        params.append(f"type={type.lower()}")
    if status:
        params.append(f"status={status.lower()}")
    if order_by:
        params.append(f"order_by={order_by}")

    url = f"{JIKAN_BASE}/anime?{'&'.join(params)}"
    data = await _fetch_cached(url, ttl=300)
    return {
        "results": data.get("data", []),
        "pagination": data.get("pagination", {}),
    }


@router.get("/anime/{anime_id}")
async def get_lilac_anime_detail(anime_id: int) -> Dict[str, Any]:
    """Full detail metadata of an anime including synopsis, characters, trailers, and relations."""
    url = f"{JIKAN_BASE}/anime/{anime_id}/full"
    data = await _fetch_cached(url, ttl=1800)
    return {"anime": data.get("data", {})}


@router.get("/skip-times/{mal_id}/{episode}")
async def get_lilac_skip_times(
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
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": "Phrolova-LilacAnime/2.1.4"}) as client:
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
