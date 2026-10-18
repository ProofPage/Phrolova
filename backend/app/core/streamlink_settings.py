"""Validated, opt-in per-platform Streamlink transport settings."""
from pydantic import BaseModel, Field, field_validator

from app.engine.base import Platform


class StreamlinkPlatformOptions(BaseModel):
    playlist_reload_seconds: float = Field(0, ge=0, le=60, allow_inf_nan=False)
    query_parameters: dict[str, str] = Field(default_factory=dict, max_length=32)

    @field_validator("playlist_reload_seconds")
    @classmethod
    def validate_reload_interval(cls, value):
        # Streamlink 8's HLS worker ignores positive intervals below 2 seconds.
        if 0 < value < 2:
            raise ValueError("Use 0 for automatic timing, or an interval of at least 2 seconds")
        return value

    @field_validator("query_parameters")
    @classmethod
    def validate_query_parameters(cls, value):
        for key, item in value.items():
            if not key.strip() or len(key) > 128 or len(item) > 4096 or any(
                ord(char) < 32 or ord(char) == 127 for char in key + item
            ):
                raise ValueError("Invalid stream query parameter")
        return value


StreamlinkPlatformSettings = dict[Platform, StreamlinkPlatformOptions]


def serialize_streamlink_settings(value: StreamlinkPlatformSettings) -> dict:
    return {Platform(key).value: StreamlinkPlatformOptions.model_validate(options).model_dump()
            for key, options in value.items()}
