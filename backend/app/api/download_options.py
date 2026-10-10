"""대시보드 자동 다운로드 조건 요청."""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal

from app.engine.download_condition import DownloadCondition, parse_watchalong_tags


class ChannelDownloadOptions(BaseModel):
    auto_record: bool = True
    recording_quality: str | None = Field(None, max_length=30)
    output_format: Literal['mp4','mkv'] | None = None
    download_condition: DownloadCondition | None = None
    watchalong_tags: str | None = Field(None, max_length=500)

    @field_validator('recording_quality')
    @classmethod
    def validate_quality(cls, value):
        import re
        if value is not None and value not in ('best', 'worst') and not re.fullmatch(r'\d{2,4}p(?:\d{1,3}(?:\.\d+)?)?', value):
            raise ValueError('올바른 녹화 화질을 선택하세요.')
        return value

    @field_validator("watchalong_tags")
    @classmethod
    def clean_tags(cls, value: str | None) -> str | None:
        if value is None:
            return None
        tags = parse_watchalong_tags(value)
        return ", ".join(tags)

    @model_validator(mode="after")
    def inherit_tags(self):
        if self.download_condition != "watchalong":
            self.watchalong_tags = None
        elif self.watchalong_tags is None:
            self.watchalong_tags = "같이보기"
        elif not self.watchalong_tags:
            raise ValueError("같이보기 태그를 하나 이상 입력하세요.")
        return self


class DefaultDownloadOptions(BaseModel):
    live_download_condition: DownloadCondition = "all"
    watchalong_tags: str = Field("같이보기", max_length=500)

    @field_validator("watchalong_tags")
    @classmethod
    def clean_tags(cls, value: str) -> str:
        tags = parse_watchalong_tags(value)
        return ", ".join(tags)

    @model_validator(mode="after")
    def require_watchalong_tags(self):
        if self.live_download_condition == "watchalong" and not self.watchalong_tags:
            raise ValueError("같이보기 태그를 하나 이상 입력하세요.")
        return self
