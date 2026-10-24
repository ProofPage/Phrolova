"""Compatibility name for the Streamlink recorder; no live FFmpeg execution."""
from app.engine.pipeline.ytdlp import YtdlpLivePipeline

FFmpegPipeline = YtdlpLivePipeline
