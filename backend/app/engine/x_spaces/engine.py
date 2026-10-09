"""Space 상태를 판단하고 녹화를 띄우는 엔진."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from app.core.config import get_settings
from app.core.logger import logger
from app.engine.base import LiveStatus

from app.engine.x_spaces.api import (
    _derive_master_url,
    _get_active_space,
    _get_m3u8_url,
    _get_user_id,
    get_space_by_id,
)
from app.engine.x_spaces.constants import (
    SPACE_STATE_NOT_STARTED,
    SPACE_STATE_RUNNING,
    X_SPACES_URL,
)
from app.engine.x_spaces.cookies import _build_headers, _parse_netscape_cookies


def _sanitize_filename(name: str) -> str:
    """파일명에 사용 불가한 문자를 제거한다."""
    from app.core.utils import clean_filename
    return clean_filename(name, max_length=50)


class XSpacesEngine:
    """X Spaces 라이브 감지 + m3u8 URL 캡처 엔진.

    라이브 감지: 비공식 GraphQL AudioSpaceById API (쿠키 인증)
    감지 방식: username → user_id → 활성 Space 확인
    m3u8 캡처: live_video_stream/status/{media_key} 에서 URL 추출
    다운로드: 캡처한 URL을 VodEngine(yt-dlp)에 전달 (별도 처리)
    """

    async def check_live_status(self, channel_id: str) -> LiveStatus:
        """비공식 GraphQL API로 사용자의 활성 Space를 확인하고 m3u8 URL을 캡처한다.

        Args:
            channel_id: X username (예: "KalserianT"). @핸들 제외.

        Returns:
            LiveStatus 딕셔너리.
            is_live=True 시 space_id와 m3u8_url 포함.
        """
        # "@username" 형태로 입력해도 정상 처리
        channel_id = channel_id.lstrip("@")

        settings = get_settings()
        cookie_file = settings.x_cookie_file

        if not cookie_file or not Path(cookie_file).is_file():
            logger.warning(
                f"[XSpaces:{channel_id}] 쿠키 파일이 설정되지 않았거나 없습니다: {cookie_file}"
            )
            return self._offline_status(channel_id)

        cookies = _parse_netscape_cookies(cookie_file)
        if not cookies.get("auth_token") or not cookies.get("ct0"):
            logger.warning(
                f"[XSpaces:{channel_id}] 쿠키 파일에서 auth_token/ct0를 찾을 수 없습니다."
            )
            return self._offline_status(channel_id)

        headers = _build_headers(cookies["ct0"])

        try:
            async with httpx.AsyncClient(
                cookies=cookies,
                headers=headers,
                timeout=15.0,
                follow_redirects=True,
            ) as client:
                # 1단계: UserByScreenName으로 user_id 조회
                user_id = await _get_user_id(client, channel_id)
                if user_id is None:
                    logger.warning(f"[XSpaces:{channel_id}] user_id 조회 실패 (쿠키 만료 또는 존재하지 않는 계정).")
                    return self._offline_status(channel_id)

                # 2단계: UserTweets 타임라인에서 활성 Space 탐색
                space_info = await _get_active_space(client, user_id, channel_id)
                if space_info is None:
                    logger.info(f"[XSpaces:{channel_id}] 활성 Space 없음 (오프라인).")
                    return self._offline_status(channel_id)
                space_id = space_info["space_id"]

                # 3단계: AudioSpaceById로 media_key + title 조회
                space_meta = await get_space_by_id(client, space_id)
                if space_meta is None:
                    logger.warning(f"[XSpaces:{channel_id}] Space 메타데이터 조회 실패: {space_id}")
                    return self._offline_status(channel_id)

                # state가 Running이 아니면 오프라인 처리 (종료된 Space가 타임라인에 남아있는 경우 대비)
                if space_meta["state"] != SPACE_STATE_RUNNING:
                    logger.info(
                        f"[XSpaces:{channel_id}] Space 종료됨 "
                        f"(state={space_meta['state']}, space_id={space_id})"
                    )
                    return self._offline_status(channel_id)

                title = space_meta["title"]
                media_key = space_meta["media_key"]

                # 4단계: m3u8 URL 캡처 + master URL 유도
                m3u8_url: Optional[str] = None
                master_url: Optional[str] = None
                if media_key:
                    m3u8_url = await _get_m3u8_url(client, media_key, channel_id)
                    if m3u8_url:
                        master_url = _derive_master_url(m3u8_url)

                logger.info(
                    f"[XSpaces:{channel_id}] 라이브 Space 감지: {space_id} — {title}"
                    + (" (master URL 캡처 완료)" if master_url else " (m3u8 캡처 실패)")
                )

                return LiveStatus(
                    channel_id=channel_id,
                    is_live=True,
                    channel_name=channel_id,
                    title=title,
                    category="X Spaces",
                    viewer_count=0,
                    thumbnail_url="",
                    profile_image_url="",
                    space_id=space_id,
                    m3u8_url=m3u8_url,
                    master_url=master_url,
                )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.warning(
                    f"[XSpaces:{channel_id}] 쿠키 인증 만료 (401). "
                    "쿠키 파일을 다시 추출해주세요."
                )
            else:
                logger.error(
                    f"[XSpaces:{channel_id}] HTTP 오류 {e.response.status_code}: {e}"
                )
            return self._offline_status(channel_id)
        except httpx.RequestError as e:
            logger.error(f"[XSpaces:{channel_id}] 네트워크 오류: {e}")
            return self._offline_status(channel_id)
        except Exception as e:
            logger.error(f"[XSpaces:{channel_id}] 예상치 못한 오류: {e}", exc_info=e)
            return self._offline_status(channel_id)

    async def start_ytdlp_recording(
        self,
        space_id: str,
        output_dir: str,
        channel_name: str,
        title: Optional[str] = None,
        cookie_file: Optional[str] = None,
    ) -> object:
        """yt-dlp subprocess로 X Spaces를 다운로드한다.

        m3u8 URL 캡처에 실패했을 때의 fallback — space_id URL로 시도.
        """
        ytdlp_path = get_settings().resolve_ytdlp_path()
        space_url = X_SPACES_URL.format(space_id=space_id)

        safe_channel = _sanitize_filename(channel_name)
        safe_title = _sanitize_filename(title or "X Spaces")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"[{safe_channel}] {safe_title}_{timestamp}.m4a"

        output_path = Path(output_dir) / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            ytdlp_path,
            space_url,
            "--output", str(output_path),
            "--format", "bestaudio",
            "--no-progress",
            "--quiet",
        ]

        if cookie_file and Path(cookie_file).is_file():
            cmd.extend(["--cookies", cookie_file])
        elif cookie_file:
            logger.warning(f"[XSpaces] 쿠키 파일을 찾을 수 없습니다: {cookie_file}")

        logger.info(f"[XSpaces] yt-dlp 다운로드 시작: {output_path}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        return process, str(output_path)

    async def download_by_space_url(
        self,
        space_url: str,
        output_dir: str,
        cookie_file: Optional[str] = None,
    ) -> dict:
        """Space URL로 직접 다운로드한다.

        UserTweets API를 사용하지 않고 space_id → AudioSpaceById → m3u8 → yt-dlp 흐름으로 처리.
        라이브 중인 Space와 종료된 Space(약 30일 이내) 모두 지원.

        Args:
            space_url: X/Twitter Space URL.
                       예: https://x.com/i/spaces/1BdGYyg...
                       또는 https://twitter.com/i/spaces/1BdGYyg...
            output_dir: 다운로드 저장 디렉토리.
            cookie_file: Netscape 형식 쿠키 파일 경로. None이면 설정에서 가져옴.

        Returns:
            성공: {"started": True, "space_id": ..., "title": ..., "state": ..., "output": ...}
            실패: {"error": "오류 메시지"}
        """
        # 1. space_id 추출
        match = re.search(r"/spaces/([A-Za-z0-9]+)", space_url)
        if not match:
            return {"error": f"Space URL에서 space_id를 추출할 수 없습니다: {space_url}"}
        space_id = match.group(1)

        # 2. 쿠키 로드
        cookie_file_path = cookie_file or get_settings().x_cookie_file
        if not cookie_file_path or not Path(cookie_file_path).is_file():
            return {"error": "X 쿠키 파일이 설정되지 않았습니다. 설정 페이지에서 쿠키 파일을 업로드해주세요."}

        cookies = _parse_netscape_cookies(cookie_file_path)
        if not cookies.get("auth_token") or not cookies.get("ct0"):
            return {"error": "쿠키 파일에서 auth_token/ct0를 찾을 수 없습니다. 쿠키 파일을 다시 추출해주세요."}

        headers = _build_headers(cookies["ct0"])

        try:
            async with httpx.AsyncClient(
                cookies=cookies,
                headers=headers,
                timeout=15.0,
                follow_redirects=True,
            ) as client:
                # 3. AudioSpaceById로 Space 메타데이터 조회
                space_info = await get_space_by_id(client, space_id)
                if space_info is None:
                    return {"error": f"Space 정보를 가져올 수 없습니다. space_id={space_id} — 쿠키 만료 또는 비공개 Space일 수 있습니다."}

                state = space_info["state"]
                media_key = space_info["media_key"]
                title = space_info["title"]

                if state == SPACE_STATE_NOT_STARTED:
                    return {"error": f"Space가 아직 시작되지 않았습니다: {title}"}

                if not media_key:
                    return {"error": f"media_key를 가져올 수 없습니다 (state={state}). 종료 후 시간이 너무 지났을 수 있습니다."}

                # 4. m3u8 URL 조회
                m3u8_url = await _get_m3u8_url(client, media_key, space_id)
                if not m3u8_url:
                    return {"error": "m3u8 URL을 가져올 수 없습니다. 종료된 지 오래된 Space이거나 비공개 Space일 수 있습니다."}

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "X 쿠키가 만료되었습니다. 브라우저에서 쿠키를 다시 추출해주세요."}
            return {"error": f"X API 오류 (HTTP {e.response.status_code})"}
        except Exception as e:
            logger.error(f"[XSpaces] Space 정보 조회 실패 (space_id={space_id}): {e}", exc_info=e)
            return {"error": str(e)}

        # 5. yt-dlp subprocess로 다운로드 시작 (start_ytdlp_recording과 동일 패턴)
        safe_title = _sanitize_filename(title)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"[XSpaces] {safe_title}_{timestamp}.m4a"

        output_path = Path(output_dir) / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        ytdlp_path = get_settings().resolve_ytdlp_path()
        cmd = [
            ytdlp_path,
            m3u8_url,
            "--output", str(output_path),
            "--format", "bestaudio",
            "--no-progress",
            "--quiet",
        ]
        if cookie_file_path:
            cmd.extend(["--cookies", cookie_file_path])

        logger.info(f"[XSpaces] 다운로드 시작: {title} ({state}) → {output_path}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def _wait_and_log() -> None:
            _, stderr = await process.communicate()
            if process.returncode == 0:
                logger.info(f"[XSpaces] 다운로드 완료: {output_path}")
            else:
                err_msg = stderr.decode(errors="replace").strip()[:300]
                logger.error(f"[XSpaces] 다운로드 실패 (exit={process.returncode}): {err_msg}")

        asyncio.create_task(_wait_and_log())

        return {
            "started": True,
            "space_id": space_id,
            "title": title,
            "state": state,
            "output": str(output_path),
        }

    @staticmethod
    def _offline_status(channel_id: str) -> LiveStatus:
        """오프라인 상태 딕셔너리를 반환한다."""
        return LiveStatus(
            channel_id=channel_id,
            is_live=False,
            channel_name=channel_id,
            title="",
            category="",
            viewer_count=0,
            thumbnail_url="",
            profile_image_url="",
            space_id=None,
            m3u8_url=None,
        )
