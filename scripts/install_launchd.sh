#!/bin/zsh
set -euo pipefail

PROJECT_DIR="/Users/kimgwonil/youtube-shorts-automation"
USER_DOMAIN="gui/$(id -u)"
PLIST_NAMES=(
  "com.kimgwonil.youtube-shorts-daily.plist"
  "com.kimgwonil.youtube-shorts-sync.plist"
  "com.kimgwonil.youtube-shorts-catchup.plist"
)

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$PROJECT_DIR/logs"
chmod +x "$PROJECT_DIR/scripts/sync_repo_on_boot.sh"
chmod +x "$PROJECT_DIR/scripts/catch_up_upload_on_boot.sh"

for PLIST_NAME in "${PLIST_NAMES[@]}"; do
  TARGET_PLIST="$HOME/Library/LaunchAgents/$PLIST_NAME"
  launchctl bootout "$USER_DOMAIN" "$TARGET_PLIST" >/dev/null 2>&1 || true
  launchctl unload "$TARGET_PLIST" >/dev/null 2>&1 || true
  if [[ -f "$TARGET_PLIST" ]]; then
    rm -f "$TARGET_PLIST"
    echo "removed: $TARGET_PLIST"
  else
    echo "not present: $TARGET_PLIST"
  fi
done

echo "Local launchd automation removed."
echo "Daily uploads are now intended to run only from GitHub Actions at 06:00 KST."
