from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from .ai_generation import build_essay_package
from .config import load_config
from .daily_context import build_daily_context
from .music_generation import generate_music
from .narration import generate_narration
from .render import render_short
from .state_store import load_state, save_state
from .upload import upload_video


def run_pipeline(project_root: Path, dry_run: bool = False, force: bool = False) -> dict:
    config = load_config(project_root)
    context = build_daily_context(
        timezone_name=config.timezone_name,
        location_name=config.location_name,
        latitude=config.location_latitude,
        longitude=config.location_longitude,
    )

    today = datetime.now(ZoneInfo(config.timezone_name)).strftime("%Y-%m-%d")
    state = load_state(config.state_file)
    if not force and not dry_run and today in state.get("recent_dates", []):
        return {"skipped": True, "reason": f"이미 오늘({today}) 영상이 업로드되었습니다. --force로 강제 실행 가능."}

    variation_seed = str(int(time.time())) if force else ""

    package = build_essay_package(
        state_file=config.state_file,
        output_dir=config.output_dir,
        openai_api_key=config.openai_api_key,
        text_model=config.openai_text_model,
        image_model=config.gemini_image_model,
        gemini_api_key=config.gemini_api_key,
        context=context,
        variation_seed=variation_seed,
    )

    bgm_path = generate_music(
        script=package.script,
        signature=package.bgm_signature,
        output_dir=config.output_dir,
        gemini_api_key=config.gemini_api_key,
        gemini_model=config.gemini_music_model,
        prefer_gemini=config.enable_gemini_music,
    )

    narration = None
    if config.enable_narration:
        narration = generate_narration(
            script=package.script,
            signature=package.bgm_signature,
            output_dir=config.output_dir,
            openai_api_key=config.openai_api_key,
            voice=config.narration_voice,
            model=config.narration_model,
        )

    render_result = render_short(
        script=package.script,
        output_dir=config.output_dir,
        font_file=config.font_file,
        shorts_hashtags=config.shorts_hashtags,
        background_path=package.background_path,
        bgm_path=bgm_path,
        narration=narration,
    )

    if dry_run:
        return {
            "video_path": str(render_result.video_path),
            "metadata_path": str(render_result.metadata_path),
            "youtube_video_id": None,
            "uploaded": False,
        }

    upload_result = upload_video(
        video_path=render_result.video_path,
        metadata_path=render_result.metadata_path,
        client_secrets_file=config.youtube_client_secrets_file,
        token_file=config.youtube_token_file,
        visibility=config.default_visibility,
        category_id=config.default_category_id,
    )

    current_state = load_state(config.state_file)

    dates = [d for d in current_state.get("recent_dates", []) if d != today]
    dates.append(today)
    current_state["recent_dates"] = dates[-20:]

    topics = [t for t in current_state.get("recent_topics", []) if t != package.script.topic]
    topics.append(package.script.topic)
    current_state["recent_topics"] = topics[-20:]

    styles = [s for s in current_state.get("recent_visual_styles", []) if s != package.script.visual_style]
    styles.append(package.script.visual_style)
    current_state["recent_visual_styles"] = styles[-10:]

    save_state(config.state_file, current_state)

    return {
        "video_path": str(render_result.video_path),
        "metadata_path": str(render_result.metadata_path),
        "youtube_video_id": upload_result["id"],
        "uploaded": True,
        "topic": package.script.topic,
        "visual_style": package.script.visual_style,
    }
