"""
Phrolova: Chat Logs API Router
채팅 아카이빙 로그 파일 목록 조회, 메시지 조회, 다운로드 엔드포인트.

조회 성능:
    로그가 쌓이면 파일 하나가 수십 MB, 수십만 줄이 된다. 예전에는 목록 화면이
    열릴 때마다 모든 파일을 끝까지 읽어 줄을 셌고, 100줄짜리 페이지 한 장을
    보여주려고 파일 전체를 파싱했다. 그래서 1페이지와 마지막 페이지가 똑같이
    느렸다.

    지금은 파일마다 인덱스(줄 수 + 체크포인트 바이트 위치)를 DB에 캐시한다.
    필터가 없으면 원하는 위치로 바로 seek 해서 필요한 줄만 파싱한다.
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.config import get_settings
from app.store.repositories import ChatIndexRepository

router = APIRouter(prefix="/api/chat", tags=["Chat"])

#: 이 개수마다 메시지의 시작 바이트 위치를 기록한다.
#: 촘촘할수록 페이지 조회가 빠르지만 인덱스가 커진다. 1000이면 페이지 한 장을
#: 위해 최대 1000줄만 훑으면 되고, 100만 줄짜리 파일도 오프셋이 1000개뿐이다.
CHECKPOINT_INTERVAL = 1000


# ── 유틸 ─────────────────────────────────────────────────

def _encode_file_id(relative_path: str) -> str:
    """상대 경로를 URL-safe Base64로 인코딩한다."""
    return base64.urlsafe_b64encode(
        relative_path.encode("utf-8")
    ).decode().rstrip("=")


def _decode_file_id(file_id: str) -> str:
    """URL-safe Base64 file_id를 상대 경로로 디코딩한다."""
    padding = 4 - len(file_id) % 4
    if padding != 4:
        file_id += "=" * padding
    return base64.urlsafe_b64decode(file_id).decode("utf-8")


def _resolve_and_validate(file_id: str) -> Path:
    """file_id를 허용된 라이브/기존 저장 경로 안에서 해석한다."""
    settings = get_settings()
    live_dir = Path(settings.effective_live_download_dir).resolve()
    legacy_dir = Path(settings.download_dir).resolve()

    try:
        relative = _decode_file_id(file_id)
    except Exception:
        raise HTTPException(status_code=400, detail="유효하지 않은 file_id입니다.")

    root_name, separator, relative_path = relative.partition("/")
    if separator and root_name in {"live", "legacy"}:
        base_dir = live_dir if root_name == "live" else legacy_dir
        relative = relative_path
    else:
        # 이전 버전에서 만든 file_id와의 호환성.
        base_dir = legacy_dir
    full_path = (base_dir / relative).resolve()

    # 경로 탈출 공격 방지
    if not full_path.is_relative_to(base_dir):
        raise HTTPException(status_code=403, detail="접근이 허용되지 않는 경로입니다.")

    if full_path.suffix.lower() != ".jsonl":
        raise HTTPException(status_code=403, detail="채팅 로그 파일만 접근할 수 있습니다.")
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    return full_path


# ── 인덱스 ───────────────────────────────────────────────

@dataclass
class _ChatIndex:
    """채팅 로그 파일 하나의 조회용 인덱스."""

    #: 읽어낼 수 있는 메시지 수. 빈 줄과 깨진 줄은 세지 않는다.
    message_count: int
    #: CHECKPOINT_INTERVAL번째 메시지가 시작하는 바이트 위치.
    offsets: list[int]
    #: 여기까지 훑었다. 개행으로 끝난 줄까지만 포함한다.
    scanned_bytes: int


def _is_message(line: bytes) -> bool:
    """이 줄이 메시지 한 건인가.

    줄 수가 아니라 '읽어낼 수 있는 메시지 수'를 세야 조회 결과와 총계가 맞는다.
    빈 줄과 깨진 줄은 조회할 때도 건너뛰기 때문이다.
    """
    if not line.strip():
        return False
    try:
        raw = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return (
        isinstance(raw, dict)
        and isinstance(raw.get("timestamp", ""), str)
        and isinstance(raw.get("nickname", "Unknown"), str)
        and isinstance(raw.get("message", ""), str)
        and (raw.get("user_id") is None or isinstance(raw["user_id"], str))
    )


def _scan_from(
    path: Path,
    start_position: int,
    start_count: int,
    offsets: list[int],
) -> tuple[int, int]:
    """start_position부터 이어 훑으며 메시지 수와 체크포인트를 채운다.

    개행으로 끝나지 않은 마지막 줄은 아카이버가 쓰는 도중일 수 있다. 세지 않고
    멈춰서, 다음 호출이 그 위치부터 다시 읽게 한다. 그렇게 하지 않으면 반쪽짜리
    줄을 메시지로 세거나 인덱스가 어긋난다.
    """
    position = start_position
    count = start_count

    with open(path, "rb") as f:
        f.seek(position)
        for line in f:
            if not line.endswith(b"\n"):
                break
            if _is_message(line):
                if count % CHECKPOINT_INTERVAL == 0:
                    offsets.append(position)
                count += 1
            position += len(line)

    return position, count


def _load_index(path: Path) -> _ChatIndex:
    """파일의 인덱스를 얻는다. 캐시가 유효하면 재사용한다.

    채팅 로그는 append 전용이라 크기만으로 판단할 수 있다.
      - 크기가 그대로면 그대로 쓴다.
      - 커졌으면 늘어난 부분만 이어서 센다. 녹화 중에도 전체를 다시 읽지 않는다.
      - 줄었으면 다른 파일로 바뀐 것이므로 처음부터 다시 만든다.
    """
    repository = ChatIndexRepository()
    key = str(path)
    cached = repository.get(key)
    size = path.stat().st_size

    if cached and cached["scanned_bytes"] == size:
        return _ChatIndex(cached["message_count"], cached["offsets"], size)

    if cached and size > cached["scanned_bytes"]:
        offsets = list(cached["offsets"])
        count = cached["message_count"]
        start = cached["scanned_bytes"]
    else:
        offsets, count, start = [], 0, 0

    scanned, count = _scan_from(path, start, count, offsets)
    repository.save(key, count, offsets, scanned)
    return _ChatIndex(count, offsets, scanned)


# ── 조회 ─────────────────────────────────────────────────

def _to_item(raw: dict) -> dict:
    """저장된 줄을 응답 형태로 바꾼다.

    profile 키는 레거시 데이터 호환용으로 무시하고 응답에는 포함하지 않는다.
    """
    return {
        "timestamp": raw.get("timestamp", ""),
        "user_id": raw.get("user_id"),
        "nickname": raw.get("nickname", "Unknown"),
        "message": raw.get("message", ""),
    }


def _is_json_literal(term: str) -> bool:
    """이 검색어가 파일에 그대로 적혀 있는가.

    따옴표와 역슬래시는 JSON이 \\" \\\\ 로 이스케이프해 저장한다. 그런 검색어는
    원문에서 그대로 찾을 수 없으므로 아래 선필터를 쓰면 안 된다.
    """
    return json.dumps(term, ensure_ascii=False)[1:-1] == term


def _read_page(path: Path, index: _ChatIndex, page: int, limit: int) -> list[dict]:
    """필터가 없을 때. 인덱스로 바로 건너뛰어 필요한 줄만 파싱한다."""
    start = (page - 1) * limit
    if start >= index.message_count or not index.offsets:
        return []

    checkpoint = min(start // CHECKPOINT_INTERVAL, len(index.offsets) - 1)
    skip = start - checkpoint * CHECKPOINT_INTERVAL

    items: list[dict] = []
    with open(path, "rb") as f:
        f.seek(index.offsets[checkpoint])
        for line in f:
            if f.tell() > index.scanned_bytes:
                break
            if not _is_message(line):
                continue
            if skip > 0:
                skip -= 1
                continue
            items.append(_to_item(json.loads(line)))
            if len(items) >= limit:
                break
    return items


def _read_filtered(
    path: Path,
    page: int,
    limit: int,
    search: Optional[str],
    nickname: Optional[str],
) -> tuple[list[dict], int]:
    """필터가 있을 때. 몇 건이 걸릴지 모르므로 전수 조사는 피할 수 없다.

    대신 파싱 전에 원문 문자열로 먼저 거른다. 대부분의 줄이 여기서 탈락하므로
    json.loads 호출이 크게 줄어든다. 선필터는 다른 필드에 걸릴 수 있어
    통과한 줄만 파싱해서 정확히 다시 확인한다.
    """
    search_lower = search.lower() if search else None
    nickname_lower = nickname.lower() if nickname else None
    pre_search = search_lower if (search_lower and _is_json_literal(search_lower)) else None
    pre_nickname = nickname_lower if (nickname_lower and _is_json_literal(nickname_lower)) else None

    start = (page - 1) * limit
    end = start + limit
    matched = 0
    items: list[dict] = []

    with open(path, "rb") as f:
        for raw_line in f:
            if not raw_line.endswith(b"\n"):
                break
            if not _is_message(raw_line):
                continue
            line = raw_line.decode("utf-8")
            if pre_search or pre_nickname:
                lowered = line.lower()
                if pre_search and pre_search not in lowered:
                    continue
                if pre_nickname and pre_nickname not in lowered:
                    continue

            try:
                item = _to_item(json.loads(line))
            except json.JSONDecodeError:
                continue

            if nickname_lower and nickname_lower not in item["nickname"].lower():
                continue
            if search_lower and search_lower not in item["message"].lower():
                continue

            if start <= matched < end:
                items.append(item)
            matched += 1

    return items, matched


def _read_messages(
    path: Path,
    page: int,
    limit: int,
    search: Optional[str] = None,
    nickname: Optional[str] = None,
) -> tuple[list[dict], int]:
    """페이지 하나와 전체 건수를 반환한다."""
    if search or nickname:
        return _read_filtered(path, page, limit, search, nickname)

    index = _load_index(path)
    return _read_page(path, index, page, limit), index.message_count


def _collect_files() -> list[dict]:
    """라이브 및 기존 저장 경로의 .jsonl 파일 메타데이터를 모은다."""
    settings = get_settings()
    roots = [("live", Path(settings.effective_live_download_dir).resolve())]
    legacy = Path(settings.download_dir).resolve()
    if legacy != roots[0][1]:
        roots.append(("legacy", legacy))

    result: list[dict] = []
    for root_name, base_dir in roots:
        if not base_dir.exists():
            continue
        for file in base_dir.glob("**/*.jsonl"):
            try:
                resolved_file = file.resolve()
                if not resolved_file.is_relative_to(base_dir):
                    continue
                if root_name == "legacy" and resolved_file.is_relative_to(roots[0][1]):
                    # 두 경로가 부모/자식 관계일 때 라이브 로그를 중복 노출하지 않는다.
                    continue
                stat = file.stat()
                relative = f"{root_name}/{file.relative_to(base_dir).as_posix()}"
                result.append({
                    "file_id": _encode_file_id(relative),
                    "filename": file.name,
                    "channel": file.parent.name,
                    "size_bytes": stat.st_size,
                    "message_count": _load_index(file).message_count,
                    "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
            except Exception:
                continue  # 손상된 파일 스킵

    result.sort(key=lambda x: x["modified_at"], reverse=True)
    return result


# ── 응답 스키마 ──────────────────────────────────────────

class ChatLogFile(BaseModel):
    """채팅 로그 파일 정보."""

    file_id: str
    filename: str
    channel: str
    size_bytes: int
    message_count: int
    created_at: str
    modified_at: str


class ChatMessageItem(BaseModel):
    """채팅 메시지 단건."""

    timestamp: str
    user_id: Optional[str]
    nickname: str
    message: str


class MessagesResponse(BaseModel):
    """페이지네이션 채팅 메시지 응답."""

    messages: list[ChatMessageItem]
    total: int
    page: int
    limit: int
    has_next: bool


# ── 엔드포인트 ───────────────────────────────────────────

@router.get("/files", response_model=list[ChatLogFile], summary="채팅 로그 파일 목록")
async def list_chat_files():
    """download_dir 하위의 모든 .jsonl 파일 목록을 반환합니다."""
    # 파일 I/O는 워커 스레드로 넘긴다. 이벤트 루프에서 직접 읽으면 그동안
    # SSE 상태 스트림과 다른 API가 전부 멈춰서 대시보드 갱신이 끊긴다.
    return await asyncio.to_thread(_collect_files)


@router.get(
    "/files/{file_id}/messages",
    response_model=MessagesResponse,
    summary="채팅 메시지 조회",
)
async def get_chat_messages(
    file_id: str,
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(100, ge=1, le=500, description="페이지당 메시지 수"),
    search: Optional[str] = Query(None, description="메시지 내용 키워드 필터"),
    nickname: Optional[str] = Query(None, description="닉네임 필터"),
):
    """특정 JSONL 파일의 채팅 메시지를 페이지네이션으로 반환합니다."""
    file_path = _resolve_and_validate(file_id)

    messages, total = await asyncio.to_thread(
        _read_messages, file_path, page, limit, search, nickname
    )

    end = (page - 1) * limit + limit
    return {
        "messages": messages,
        "total": total,
        "page": page,
        "limit": limit,
        "has_next": end < total,
    }


@router.get("/files/{file_id}/download", summary="채팅 로그 파일 다운로드")
async def download_chat_file(file_id: str):
    """JSONL 파일을 직접 다운로드합니다."""
    file_path = _resolve_and_validate(file_id)

    return FileResponse(
        path=str(file_path),
        media_type="application/jsonlines+json",
        filename=file_path.name,
    )
