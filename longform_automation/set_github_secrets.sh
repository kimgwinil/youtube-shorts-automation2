#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-kimgwinil/youtube-shorts-automation}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
TOKEN_FILE="$ROOT/token.json"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is not installed."
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "gh is not authenticated. Run: gh auth login -h github.com"
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo ".env not found at $ENV_FILE"
  exit 1
fi

if [[ ! -f "$TOKEN_FILE" ]]; then
  echo "token.json not found at $TOKEN_FILE"
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

required=(
  ELEVENLABS_API_KEY
  ELEVENLABS_VOICE_ID
  OPENAI_API_KEY
  GEMINI_API_KEY
)

for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "$name is missing in .env"
    exit 1
  fi
done

printf '%s' "$ELEVENLABS_API_KEY" | gh secret set ELEVENLABS_API_KEY --repo "$REPO"
printf '%s' "$ELEVENLABS_VOICE_ID" | gh secret set ELEVENLABS_VOICE_ID --repo "$REPO"
printf '%s' "$OPENAI_API_KEY" | gh secret set OPENAI_API_KEY --repo "$REPO"
printf '%s' "$GEMINI_API_KEY" | gh secret set GEMINI_API_KEY --repo "$REPO"
gh secret set YOUTUBE_TOKEN_JSON --repo "$REPO" < "$TOKEN_FILE"

echo "GitHub Actions secrets are configured for $REPO."
