#!/bin/bash
# macOS LaunchAgent 설치 스크립트
# 컴퓨터 시작/로그인 시 자동으로 오늘 업로드 여부를 확인하고 재시도합니다.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_SRC="$PROJECT_DIR/launchd/com.gikim.essay-shorts-retry.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.gikim.essay-shorts-retry.plist"

echo "프로젝트 경로: $PROJECT_DIR"

# plist에 실제 경로 주입
sed "s|__PROJECT_DIR__|$PROJECT_DIR|g" "$PLIST_SRC" > "$PLIST_DEST"

# 권한 설정
chmod 644 "$PLIST_DEST"
chmod +x "$PROJECT_DIR/scripts/local_retry.sh"

# LaunchAgent 로드
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo "✅ LaunchAgent 설치 완료: $PLIST_DEST"
echo "   컴퓨터 시작/로그인 시 자동으로 오늘 업로드를 확인합니다."
echo "   로그 위치: /tmp/essay-shorts-retry.log"
echo ""
echo "제거하려면: launchctl unload $PLIST_DEST && rm $PLIST_DEST"
