#!/bin/bash
# 컴퓨터 시작 시 오늘 업로드가 안 되었으면 자동으로 실행합니다.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_FILE="$PROJECT_DIR/data/state.json"
LOG_FILE="/tmp/essay-shorts-retry.log"
TODAY=$(TZ=Asia/Seoul date +%Y-%m-%d)

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "=== Essay Shorts 로컬 재시도 시작 (오늘: $TODAY) ==="

# 오늘 이미 업로드됐는지 확인
if [ -f "$STATE_FILE" ]; then
    if python3 -c "
import json, sys
try:
    state = json.load(open('$STATE_FILE'))
    sys.exit(0 if '$TODAY' in state.get('recent_dates', []) else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        log "오늘($TODAY) 이미 업로드 완료. 재시도 불필요."
        exit 0
    fi
fi

log "오늘 업로드 기록 없음. 파이프라인 실행 시작..."

# Python 환경 찾기 (venv 우선)
PYTHON=""
for candidate in \
    "$PROJECT_DIR/.venv/bin/python3" \
    "$HOME/.venv/bin/python3" \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3" \
    "python3"; do
    if command -v "$candidate" &>/dev/null || [ -f "$candidate" ]; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    log "오류: python3를 찾을 수 없습니다."
    exit 1
fi

log "Python: $PYTHON"

# .env 로드
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

cd "$PROJECT_DIR" || exit 1
"$PYTHON" scripts/run_daily.py >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    log "업로드 성공."
elif [ $EXIT_CODE -eq 2 ]; then
    log "이미 오늘 업로드됨 (건너뜀)."
else
    log "오류 발생 (exit code: $EXIT_CODE). 로그: $LOG_FILE"
fi

exit $EXIT_CODE
