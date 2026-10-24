#!/bin/sh
set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}

# 사용자 및 그룹 권한 조정
if [ -n "$PUID" ] && [ "$PUID" != "0" ]; then
    groupmod -o -g "$PGID" phrolova 2>/dev/null || true
    usermod -o -u "$PUID" -g "$PGID" phrolova 2>/dev/null || true
fi

# 마운트된 데이터 및 다운로드 디렉토리 권한 설정
for dir in /app/data /app/downloads /app/recordings; do
    if [ -d "$dir" ]; then
        chown -R "$PUID:$PGID" "$dir" 2>/dev/null || true
    else
        mkdir -p "$dir"
        chown -R "$PUID:$PGID" "$dir" 2>/dev/null || true
    fi
done

if [ "$1" = "python" ] || [ "$1" = "uvicorn" ]; then
    exec gosu phrolova "$@"
fi

exec "$@"
