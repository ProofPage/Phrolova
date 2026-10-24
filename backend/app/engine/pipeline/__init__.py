"""녹화 파이프라인.

구현이 둘인데 한 파일에 있었다. 이름은 15개가 겹치지만 실제로 같은 코드는
네 개(합쳐 10줄)뿐이고 핵심인 start_recording은 서로 30%밖에 닮지 않았다.
공통 조상을 만들 만한 사이가 아니라서, 합치는 대신 파일을 나눴다.

호출부가 쓰던 이름은 여기서 그대로 내준다.
"""

from app.engine.pipeline.ffmpeg import FFmpegPipeline
from app.engine.pipeline.state import RecordingState
from app.engine.pipeline.ytdlp import YtdlpLivePipeline

__all__ = ["FFmpegPipeline", "RecordingState", "YtdlpLivePipeline"]
