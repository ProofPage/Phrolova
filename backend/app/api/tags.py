"""
Rookery: Tags API Router
사용자 정의 태그 목록과 채널별 태그 지정을 관리한다.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.store.repositories import TagRepository

router = APIRouter(prefix="/api/tags", tags=["Tags"])


class CreateTagRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="태그 이름")


@router.get("", summary="전체 태그 목록 조회")
async def list_tags():
    return {"tags": TagRepository().list_all()}


@router.post("", summary="새 태그 생성")
async def create_tag(req: CreateTagRequest):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="태그 이름이 비어 있습니다.")

    repo = TagRepository()
    repo.add(name)
    return {"tags": repo.list_all()}


@router.delete("/{tag_name:path}", summary="태그 삭제")
async def delete_tag(tag_name: str):
    TagRepository().delete(tag_name)

    # 모든 채널에서도 해당 태그 제거
    from app.main import get_recorder_service

    service = get_recorder_service()
    service.remove_tag_from_all_channels(tag_name)

    return {"status": "ok", "deleted": tag_name}

class UpdateChannelTagsRequest(BaseModel):
    tags: list[str] = Field(..., description="적용할 태그 목록")

@router.patch("/channel/{channel_id:path}", summary="개별 채널의 태그 업데이트")
async def update_channel_tags(channel_id: str, req: UpdateChannelTagsRequest):
    from app.main import get_recorder_service
    from app.api.stream import _to_composite_key
    
    service = get_recorder_service()
    composite_key = _to_composite_key(channel_id)
    
    try:
        service.set_channel_tags(composite_key, req.tags)
        return {"status": "ok", "tags": req.tags}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
