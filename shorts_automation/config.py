from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass
class AppConfig:
    project_root: Path
    state_file: Path
    output_dir: Path
    font_file: Path
    youtube_client_secrets_file: Path
    youtube_token_file: Path
    default_visibility: str
    default_category_id: str
    shorts_hashtags: str
    timezone_name: str
    location_name: str
    location_latitude: float
    location_longitude: float
    openai_api_key: str
    openai_text_model: str
    gemini_api_key: str
    gemini_image_model: str
    gemini_music_model: str
    enable_gemini_music: bool


def load_config(project_root: Path) -> AppConfig:
    load_dotenv(project_root / ".env")
    return AppConfig(
        project_root=project_root,
        state_file=project_root / "data" / "state.json",
        output_dir=project_root / "output",
        font_file=Path(os.environ["FONT_FILE"]),
        youtube_client_secrets_file=Path(os.environ["YOUTUBE_CLIENT_SECRETS_FILE"]),
        youtube_token_file=Path(os.environ["YOUTUBE_TOKEN_FILE"]),
        default_visibility=os.environ.get("DEFAULT_VISIBILITY", "private"),
        default_category_id=os.environ.get("DEFAULT_CATEGORY_ID", "27"),
        shorts_hashtags=os.environ.get("SHORTS_HASHTAGS", "#Shorts #쇼츠 #에세이"),
        timezone_name=os.environ.get("TIMEZONE_NAME", "Asia/Seoul"),
        location_name=os.environ.get("LOCATION_NAME", "Seoul, KR"),
        location_latitude=float(os.environ.get("LOCATION_LATITUDE", "37.5665")),
        location_longitude=float(os.environ.get("LOCATION_LONGITUDE", "126.9780")),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_text_model=os.environ.get("OPENAI_TEXT_MODEL", "gpt-4o"),
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        gemini_image_model=os.environ.get("GEMINI_IMAGE_MODEL", "imagen-4.0-fast-generate-001"),
        gemini_music_model=os.environ.get("GEMINI_MUSIC_MODEL", "models/lyria-realtime-exp"),
        enable_gemini_music=os.environ.get("ENABLE_GEMINI_MUSIC", "true").lower() == "true",
    )
