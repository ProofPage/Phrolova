"""
Rookery: FastAPI 진입점
Lifespan 컨텍스트 매니저를 통해 Conductor 라이프사이클을 관리한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

# NOTE: Windows 이벤트 루프 정책은 app/__init__.py에서 설정됨

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings, resolve_data_dir
from app.core.http import close_http_client
from app.core.logger import logger
from app.engine.auth import AuthManager
from app.engine.conductor import Conductor
from app.services.recorder import RecorderService
from app.services.discord_bot import DiscordBotService
from app.services.notifications import DiscordWebhookTransport, NotificationService
from app.engine.updater import UpdaterService
from app.store import close_database, get_database, migrate_json_files
from app.version import __version__

# API Routers
from app.api.stream import router as stream_router
from app.api.vod import router as vod_router
from app.api.settings import router as settings_router
from app.api.chat import router as chat_router
from app.api.stats import router as stats_router
from app.api.setup import router as setup_router
from app.api.platforms import router as platforms_router
from app.api.archive import router as archive_router
from app.api.tags import router as tags_router
from app.api.events import router as events_router
from app.api.system import router as system_router

# ── 전역 인스턴스 ────────────────────────────────────────
_recorder_service: RecorderService | None = None
_updater_service: UpdaterService | None = None
_notification_service: NotificationService | None = None


def get_notification_service() -> NotificationService:
    """NotificationService 인스턴스를 반환한다. (DI용)"""
    if _notification_service is None:
        raise RuntimeError("NotificationService가 초기화되지 않았습니다.")
    return _notification_service

def get_updater_service() -> UpdaterService:
    """UpdaterService 인스턴스를 반환한다. (DI용)"""
    if _updater_service is None:
        raise RuntimeError("UpdaterService가 초기화되지 않았습니다.")
    return _updater_service


def get_recorder_service() -> RecorderService:
    """RecorderService 인스턴스를 반환한다. (DI용)"""
    if _recorder_service is None:
        raise RuntimeError("RecorderService가 초기화되지 않았습니다.")
    return _recorder_service


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """애플리케이션 시작/종료 라이프사이클 관리."""
    global _recorder_service, _updater_service, _notification_service

    settings = get_settings()
    logger.info(f"🚀 {settings.app_name} 시작 중...")

    # FFmpeg 경로 검증
    try:
        ffmpeg = settings.resolve_ffmpeg_path()
        logger.info(f"✅ FFmpeg 확인: {ffmpeg}")
    except FileNotFoundError as e:
        logger.warning(f"⚠️ {e}")

    # yt-dlp 경로 검증 (Windows exe 환경에서 없으면 자동 다운로드)
    try:
        ytdlp = settings.resolve_ytdlp_path(auto_download=True)
        logger.info(f"✅ yt-dlp 확인: {ytdlp}")
    except Exception as e:
        logger.warning(f"⚠️ yt-dlp 확인 실패: {e}")

    # ── 저장소 ───────────────────────────────────────────
    # 다른 모든 서비스가 저장소에 의존하므로 가장 먼저 연다.
    data_dir = resolve_data_dir()
    database = get_database()
    migrate_json_files(database, data_dir)

    # ── 알림 서비스 ──────────────────────────────────────
    # 전송 채널보다 먼저 만들어 두면 부팅 중 발생한 알림도 큐에 쌓였다가 전송된다.
    _notification_service = NotificationService()

    # 서비스 초기화
    auth = AuthManager()
    conductor = Conductor(auth=auth, notifier=_notification_service)
    _recorder_service = RecorderService(
        conductor=conductor, auth=auth, notifier=_notification_service
    )

    if auth.is_authenticated:
        logger.info("🔑 인증 쿠키 로드 완료.")
    else:
        logger.info("🔓 비로그인 모드로 동작합니다.")

    # Discord Bot 시작 (토큰이 설정되어 있으면 자동 구동)
    # on_ready 콜백으로 연결 복구 즉시 대기 중인 알림을 흘려보낸다.
    discord_bot = DiscordBotService(
        recorder_service=_recorder_service,
        on_ready=_notification_service.wake,
    )
    discord_bot.set_notifier(_notification_service)

    # 전송 채널 등록 — Bot을 먼저, 실패 시 Webhook으로 폴백한다.
    _notification_service.register(discord_bot)
    _notification_service.register(DiscordWebhookTransport())

    await _notification_service.start()
    await discord_bot.start()

    # 업데이트 알리미 시작
    _updater_service = UpdaterService(notifier=_notification_service)
    await _updater_service.start()

    logger.info(f"✅ {settings.app_name} Engine Started!")

    # Conductor 시작 (감시 루프 실행)
    await conductor.start()

    yield

    # ── 종료 ──
    logger.info(f"🛑 {settings.app_name} 종료 중...")
    if _updater_service:
        await _updater_service.stop()
    # Conductor를 먼저 멈춰야 종료 중 발생한 '녹화 완료' 알림이 큐에 들어간다.
    if conductor:
        await conductor.stop()
    # 알림 서비스를 봇보다 먼저 정리해 마지막 알림 전송을 시도한다.
    if _notification_service:
        await _notification_service.stop()
    if discord_bot:
        await discord_bot.stop()
    await close_http_client()
    # 저장소는 마지막에 닫는다 — 위 종료 과정에서 아직 쓰기가 발생한다.
    close_database()
    _recorder_service = None
    _notification_service = None
    logger.info("👋 Goodbye!")


# ── 정적 파일 경로 ─────────────────────────────────────────
# PyInstaller onefile → sys._MEIPASS
# PyInstaller onedir  → sys.executable 옆 _internal/app/static
# 일반 실행            → 현재 파일 기준

def _resolve_static_dir() -> Path:
    """PyInstaller 빌드 방식에 관계없이 static 폴더를 찾는다."""
    candidates = []

    # 1) PyInstaller onefile: _MEIPASS 사용
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "app" / "static")

    # 2) PyInstaller onedir: exe 옆 _internal 폴더
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / "_internal" / "app" / "static")

    # 3) 일반 실행: 현재 파일 기준
    candidates.append(Path(__file__).resolve().parent / "static")

    for path in candidates:
        if path.exists() and (path / "index.html").exists():
            return path

    # 어디에도 없으면 기본값 반환 (경고는 아래에서 처리)
    return candidates[-1]

STATIC_DIR = _resolve_static_dir()


# ── FastAPI 앱 ───────────────────────────────────────────
app = FastAPI(
    title="Rookery",
    description="다중 플랫폼 스트리밍 및 VOD 전문 녹화 솔루션",
    version=__version__,
    lifespan=lifespan,
)

# CORS 설정 (개발 환경 프록시 연동용 — 프로덕션에서는 동일 오리진이므로 실질적 영향 없음)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 라우터 등록 ──────────────────────────────────────────
app.include_router(stream_router)
app.include_router(vod_router)
app.include_router(settings_router)
app.include_router(chat_router)
app.include_router(stats_router)
app.include_router(setup_router)
app.include_router(platforms_router)
app.include_router(archive_router)
app.include_router(tags_router)
app.include_router(events_router)
app.include_router(system_router)


# ── 헬스 체크 ────────────────────────────────────────────
@app.get("/health", tags=["Health"])
async def health_check_root():
    """헬스 체크 엔드포인트."""
    return {"message": "Rookery Engine Started"}


@app.get("/health/detail", tags=["Health"])
async def health_check():
    """상세 헬스 체크."""
    settings = get_settings()
    try:
        get_recorder_service()
    except RuntimeError:
        pass

    return {
        "status": "ok",
        "app": settings.app_name,
        "version": __version__,
        "authenticated": bool(settings.nid_aut and settings.nid_ses),
    }


# ── 프론트엔드 SPA 서빙 ────────────────────────────────────
# API 라우터 등록 이후에 마운트해야 API가 우선 처리됨
if STATIC_DIR.exists():
    # /assets 등 정적 리소스 서빙
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def serve_spa_root():
        """SPA 루트 페이지 반환."""
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa_fallback(request: Request, full_path: str):
        """SPA 클라이언트 라우팅 지원 — API 경로가 아닌 모든 요청을 index.html로 반환."""
        # API / health 경로는 404로 반환 (이미 등록된 라우터가 처리)
        if full_path.startswith(("api/", "health", "docs", "openapi")):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(STATIC_DIR / "index.html")
else:
    logger.warning(
        "⚠️  static 폴더를 찾을 수 없습니다. 개발 환경(Vite dev server)으로 동작합니다. "
        "배포 시 'npm run build'를 먼저 실행하세요."
    )


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        # uvicorn이 자기 stderr 핸들러를 달면 INFO가 ERROR로 둔갑한다.
        # app.core.logger._attach_uvicorn_logging 참고.
        log_config=None,
    )
