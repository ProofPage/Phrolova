# syntax=docker/dockerfile:1

# ---- 1. Frontend Build Stage ----
FROM node:22-alpine AS frontend-builder
WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
RUN npm run build

# ---- 2. Final Runtime Stage ----
FROM python:3.14-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Seoul

WORKDIR /app

# 시스템 의존성 설치: ffmpeg (미디어 녹화/후처리), nodejs (WASM 디코더), gosu (권한 관리), curl (헬스체크)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    gosu \
    curl \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# 파이썬 의존성 설치
COPY backend/requirements.txt backend/requirements-common.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 백엔드 소스 복사
COPY backend/app ./app
COPY backend/run.py ./run.py

# 빌드된 프론트엔드 정적 파일 주입
COPY --from=frontend-builder /build/backend/app/static ./app/static

# 실행 스크립트 복사 및 비루트 사용자 설정
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && useradd -u 1000 -U -d /app -s /bin/bash phrolova \
    && mkdir -p /app/data /app/downloads /app/recordings \
    && chown -R phrolova:phrolova /app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/ || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "run.py"]
