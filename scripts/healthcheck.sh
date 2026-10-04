#!/usr/bin/env bash
# Rookery 운영 서버 점검 (읽기 전용)
#
# 녹화가 진행 중인 상태에서 실행해도 안전하도록 설계했다:
#   - 파일을 쓰거나 지우지 않는다
#   - 서비스를 재시작하지 않는다
#   - SQLite는 읽기 전용(mode=ro)으로만 열어 쓰기 잠금을 만들지 않는다
#   - 설정 변경 API(PUT/POST)를 호출하지 않는다
#
# 사용법:
#   bash healthcheck.sh                 # 기본 http://127.0.0.1:8000
#   BASE=http://127.0.0.1:9000 bash healthcheck.sh

set -uo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"
# Rookery로 이름을 바꾸기 전 설치본은 ~/signal-recorder 에 있다.
if [ -z "${APP_DIR:-}" ]; then
    for cand in "$HOME/rookery" "$HOME/signal-recorder"; do
        [ -d "$cand" ] && APP_DIR="$cand" && break
    done
    APP_DIR="${APP_DIR:-$HOME/rookery}"
fi

section() { printf '\n\033[1m── %s ─────────────────────────────\033[0m\n' "$1"; }
kv()      { printf '  %-26s %s\n' "$1" "$2"; }

# curl이 있으면 JSON을 받아온다. 실패해도 스크립트를 멈추지 않는다.
fetch() { curl -fsS --max-time 5 "$BASE$1" 2>/dev/null; }

# python3가 있다고 표시돼도 실제로 동작하지 않는 환경이 있어 실행까지 확인한다.
PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys' >/dev/null 2>&1; then
        PY="$cand"; break
    fi
done
has_py() { [ -n "$PY" ]; }

# ── 1. 서비스 응답 ──────────────────────────────────
section "서비스"
if HEALTH=$(fetch /health/detail); then
    kv "응답" "정상"
    echo "$HEALTH" | tr ',' '\n' | sed 's/[{}"]//g' | sed 's/^/    /'
else
    kv "응답" "❌ $BASE 에 연결 실패"
fi

if command -v systemctl >/dev/null 2>&1; then
    kv "systemd" "$(systemctl is-active rookery 2>/dev/null || echo '(미등록)')"
    kv "부팅 시 자동시작" "$(systemctl is-enabled rookery 2>/dev/null || echo '(미등록)')"
fi

# ── 2. 실행 중인 프로세스 ───────────────────────────
section "프로세스"
kv "uvicorn" "$(pgrep -fc 'uvicorn.*app.main' 2>/dev/null || echo 0)개"
kv "yt-dlp (녹화/다운로드)" "$(pgrep -fc 'yt-dlp' 2>/dev/null || echo 0)개"
kv "ffmpeg" "$(pgrep -fc 'ffmpeg' 2>/dev/null || echo 0)개"
echo "  ── 가동 시간 ──"
pgrep -f 'uvicorn.*app.main' 2>/dev/null | head -3 | while read -r pid; do
    printf '    pid %-8s %s\n' "$pid" "$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')"
done

# ── 3. 채널 및 녹화 상태 ────────────────────────────
section "채널 / 녹화"
if CH=$(fetch /api/platforms/channels); then
    if has_py; then
        # heredoc이 stdin을 차지하므로 데이터는 환경변수로 넘긴다.
        CHANNELS_JSON="$CH" "$PY" <<'PYEOF'
import json, os

try:
    rows = json.loads(os.environ["CHANNELS_JSON"])
except Exception as e:
    print(f"  (응답 파싱 실패: {e})")
    raise SystemExit

print(f"  등록 채널: {len(rows)}개")
live = [c for c in rows if c.get("is_live")]
rec = [c for c in rows if (c.get("recording") or {}).get("is_recording")]
print(f"  라이브: {len(live)}개 / 녹화 중: {len(rec)}개")

for c in rec:
    r = c.get("recording") or {}
    name = c.get("channel_name") or c.get("channel_id")
    dur = r.get("duration_seconds") or 0
    size_mb = (r.get("file_size_bytes") or 0) / 1024 / 1024
    hours, mins = int(dur // 3600), int((dur % 3600) // 60)
    print(f"    [REC] {name}  {hours}시간 {mins}분  {size_mb:,.0f}MB")

for c in live:
    if c in rec:
        continue
    name = c.get("channel_name") or c.get("channel_id")
    auto = "자동녹화 ON" if c.get("auto_record") else "자동녹화 OFF"
    print(f"    [LIVE] {name}  ({auto}) — 녹화 안 함")

errs = [c for c in rows if c.get("last_error")]
if errs:
    print(f"  [!] 오류 상태 채널 {len(errs)}개:")
    for c in errs[:5]:
        print(f"    - {c.get('composite_key')}: {str(c.get('last_error'))[:90]}")
PYEOF
    else
        kv "채널 수" "$(printf '%s' "$CH" | grep -o 'composite_key' | wc -l)"
    fi
else
    kv "조회" "실패 — API에 접근할 수 없습니다"
fi

# ── 4. 알림 파이프라인 ──────────────────────────────
section "Discord 알림"
if NS=$(fetch /api/settings/discord/status); then
    echo "$NS" | tr ',' '\n' | sed 's/[{}"]//g' | sed 's/^/    /'
else
    kv "조회" "❌ 실패 (구버전이면 이 엔드포인트가 없습니다)"
fi

# ── 5. 저장소 ───────────────────────────────────────
section "저장소"
DB=""
# 앱을 아직 한 번도 띄우지 않았으면 이관이 안 돌아 구버전 파일명 그대로다.
for cand in \
    "$APP_DIR/backend/data/rookery.db" ./backend/data/rookery.db \
    "$APP_DIR/backend/data/signal_recorder.db" ./backend/data/signal_recorder.db; do
    [ -f "$cand" ] && DB="$cand" && break
done

if [ -n "$DB" ]; then
    kv "DB 파일" "$DB ($(du -h "$DB" 2>/dev/null | cut -f1))"
    if has_py; then
        # 읽기 전용으로만 연다 — 실행 중인 앱의 쓰기를 방해하지 않는다.
        "$PY" - "$DB" <<'PYEOF'
import sqlite3, sys
try:
    con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True, timeout=3)
    ver = con.execute("PRAGMA user_version").fetchone()[0]
    print(f"  스키마 버전: v{ver}")
    for t in ("channels","live_history","live_detections","vod_tasks","tags","pending_notifications"):
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"    {t:<24} {n:>8,}행")
        except sqlite3.Error as e:
            print(f"    {t:<24} (없음: {e})")
    con.close()
except Exception as e:
    print(f"  ❌ DB 조회 실패: {e}")
PYEOF
    fi
    # 이관 흔적 확인 (구버전에서 올라온 서버인지)
    LEFT=$(ls "$(dirname "$DB")"/*.json 2>/dev/null | wc -l)
    MIGR=$(ls "$(dirname "$DB")"/*.migrated 2>/dev/null | wc -l)
    kv "미이관 JSON" "${LEFT}개"
    kv "이관 완료(.migrated)" "${MIGR}개"
else
    kv "DB 파일" "❌ 찾지 못함 (구버전이면 JSON을 씁니다)"
    ls -la "$APP_DIR/backend/data/" 2>/dev/null | sed 's/^/    /'
fi

# ── 6. 디스크 ───────────────────────────────────────
section "디스크"
df -h "$APP_DIR" 2>/dev/null | tail -1 | awk '{printf "  %-26s %s 중 %s 사용 (%s), 여유 %s\n","녹화 파티션",$2,$3,$5,$4}'
for d in "$APP_DIR/backend/recordings" "$APP_DIR/recordings"; do
    [ -d "$d" ] && kv "녹화 폴더" "$(du -sh "$d" 2>/dev/null | cut -f1)  ($d)"
done

# ── 7. 로그 ─────────────────────────────────────────
section "로그"
for L in "$APP_DIR/logs/service.log" "$APP_DIR/backend/logs/service.log"; do
    if [ -f "$L" ]; then
        kv "파일" "$L ($(du -h "$L" | cut -f1))"
        kv "ERROR 총합" "$(grep -c 'ERROR' "$L" 2>/dev/null || echo 0)건"
        kv "오늘 ERROR" "$(grep -c "^$(date +%Y-%m-%d).*ERROR" "$L" 2>/dev/null || echo 0)건"
        echo "  ── 최근 ERROR 5건 ──"
        grep 'ERROR' "$L" 2>/dev/null | tail -5 | cut -c1-160 | sed 's/^/    /'
    fi
done

# ── 8. 버전 ─────────────────────────────────────────
section "버전"
[ -f "$APP_DIR/backend/app/version.py" ] && kv "소스 버전" "$(grep -oE '[0-9]+\.[0-9]+\.[0-9]+' "$APP_DIR/backend/app/version.py" | head -1)"
if [ -d "$APP_DIR/.git" ]; then
    kv "git 브랜치" "$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null)"
    kv "git 커밋" "$(git -C "$APP_DIR" log --oneline -1 2>/dev/null)"
fi
command -v ffmpeg >/dev/null 2>&1 && kv "ffmpeg" "$(ffmpeg -version 2>/dev/null | head -1 | cut -c1-60)"
command -v yt-dlp >/dev/null 2>&1 && kv "yt-dlp" "$(yt-dlp --version 2>/dev/null)"
has_py && kv "python" "$($PY --version 2>&1)"

printf '\n\033[1m점검 완료 — 아무것도 변경하지 않았습니다.\033[0m\n'
