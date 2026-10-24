"""대시보드 자동 다운로드 조건 요청."""

import json

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from typing import Literal

from app.engine.download_condition import DownloadCondition, parse_watchalong_tags


class ScheduleWindow(BaseModel):
    """한 요일 묶음의 감시 시간대. days는 월요일=0."""

    days: list[int] = Field(min_length=1)
    start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    @field_validator("days")
    @classmethod
    def unique_days(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("요일은 0(월)부터 6(일)까지입니다.")
        return sorted(set(value))


class ChannelMonitorSchedule(BaseModel):
    """채널별 감시 방식. always면 기존처럼 항상 확인한다."""

    mode: Literal["always", "scheduled"] = "always"
    windows: list[ScheduleWindow] = Field(default_factory=list, max_length=50)
    lead_minutes: int = Field(10, ge=0, le=180)
    delay_minutes: int = Field(30, ge=0, le=360)

    @model_validator(mode="after")
    def require_window(self):
        if self.mode == "scheduled" and not self.windows:
            raise ValueError("예약 감시에는 시간대를 하나 이상 추가하세요.")
        return self

    def to_storage(self) -> str | None:
        """DB에 저장할 JSON. 상시 감시면 NULL로 되돌린다."""
        if self.mode != "scheduled":
            return None
        return json.dumps(self.model_dump(), ensure_ascii=False)


class ChannelDownloadOptions(BaseModel):
    auto_record: bool = True
    recording_quality: str | None = Field(None, max_length=100)
    output_format: Literal['mp4','mkv'] | None = None
    download_condition: DownloadCondition | None = None
    watchalong_tags: str | None = Field(None, max_length=500)
    monitor_schedule: ChannelMonitorSchedule | None = None
    popkontv_password: SecretStr | None = Field(None, exclude=True, repr=False)

    @field_validator('recording_quality')
    @classmethod
    def validate_quality(cls, value):
        import re
        if value is not None and value not in ('best', 'worst'):
            # Standard resolution/qn or custom per-channel format override
            if not re.fullmatch(r'[A-Za-z0-9_\[\]<>=+/*.,: -]{1,80}', value):
                raise ValueError('올바른 녹화 화질 또는 포맷을 입력하세요.')
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
