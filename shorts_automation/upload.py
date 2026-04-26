from __future__ import annotations

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def upload_video(
    video_path: Path,
    metadata_path: Path,
    client_secrets_file: Path,
    token_file: Path,
    visibility: str,
    category_id: str,
) -> dict:
    credentials = _load_credentials(client_secrets_file, token_file)
    youtube = build("youtube", "v3", credentials=credentials)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata["tags"],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": visibility,
            "selfDeclaredMadeForKids": False,
        },
    }

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(video_path), chunksize=-1, resumable=True),
    )
    response = None
    while response is None:
        _, response = request.next_chunk()
    return response


def _load_credentials(client_secrets_file: Path, token_file: Path) -> Credentials:
    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if _is_noninteractive_env():
            raise RuntimeError(
                "비대화형 환경에서는 새 OAuth 인증을 시작할 수 없습니다. "
                "GitHub Actions에서는 유효한 token.json 을 Secret으로 제공해야 합니다."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), SCOPES)
        creds = flow.run_local_server(port=0)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _is_noninteractive_env() -> bool:
    import os

    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
