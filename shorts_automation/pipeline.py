from __future__ import annotations

from datetime import datetime
from pathlib import Path
import random
import time
from zoneinfo import ZoneInfo

from .ai_generation import build_daily_package
from .daily_context import build_daily_context
from .config import load_config
from .music_generation import generate_music
from .narration import generate_narration
from .render import render_short
from .script_builder import build_script, pick_next_quote
from .state_store import load_state, save_state
from .upload import upload_video


def run_pipeline(project_root: Path, dry_run: bool = False, force: bool = False) -> dict:
    config = load_config(project_root)
    background_override = None
    bgm_override = None
    bgm_signature = None
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

    if config.enable_ai_generation and (config.openai_api_key or config.gemini_api_key):
        variation_seed = str(int(time.time())) if force else ""
        try:
            package = build_daily_package(
                quotes_file=config.quotes_file,
                state_file=config.state_file,
                output_dir=config.output_dir,
                openai_api_key=config.openai_api_key,
                text_model=config.openai_text_model,
                image_model=config.gemini_image_model,
                gemini_api_key=config.gemini_api_key,
                context=context,
                variation_seed=variation_seed,
            )
            script = package.script
            background_override = package.background_path
            bgm_signature = package.bgm_signature
        except Exception as exc:
            print(f"[pipeline] AI 생성 실패, fallback 사용: {exc}")
            quote = pick_next_quote(config.quotes_file, config.state_file)
            selected_visual_style = _select_non_ai_visual_style(quote=quote, state=state, date_iso=context.date_iso)
            script = build_script(quote, visual_style_override=selected_visual_style)
            bgm_signature = f"{today}_{script.quote.quote_id[:12]}"
    else:
        quote = pick_next_quote(config.quotes_file, config.state_file)
        selected_visual_style = _select_non_ai_visual_style(quote=quote, state=state, date_iso=context.date_iso)
        script = build_script(quote, visual_style_override=selected_visual_style)
        bgm_signature = f"{today}_{script.quote.quote_id[:12]}"

    bgm_override = generate_music(
        script=script,
        signature=bgm_signature,
        output_dir=config.output_dir,
        music_dir=config.music_dir,
        gemini_api_key=config.gemini_api_key,
        gemini_model=config.gemini_music_model,
        prefer_gemini=config.enable_gemini_music,
    )

    narration = None
    if config.enable_narration:
        narration = generate_narration(
            script=script,
            signature=bgm_signature,
            output_dir=config.output_dir,
            elevenlabs_api_key=config.elevenlabs_api_key,
            elevenlabs_voice_id=config.elevenlabs_voice_id,
            elevenlabs_model=config.elevenlabs_model,
            google_tts_credentials=config.google_tts_credentials,
            google_tts_api_key=config.google_tts_api_key,
            voice=config.narration_voice,
        )

    render_result = render_short(
        script=script,
        background_dir=config.background_dir,
        output_dir=config.output_dir,
        font_file=config.font_file,
        shorts_hashtags=config.shorts_hashtags,
        background_override=background_override,
        bgm_override=bgm_override,
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
    styles = [style for style in current_state.get("recent_visual_styles", []) if style != script.visual_style]
    styles.append(script.visual_style)
    current_state["recent_visual_styles"] = styles[-20:]
    save_state(config.state_file, current_state)
    return {
        "video_path": str(render_result.video_path),
        "metadata_path": str(render_result.metadata_path),
        "youtube_video_id": upload_result["id"],
        "uploaded": True,
    }


def _select_non_ai_visual_style(quote, state: dict, date_iso: str) -> str:
    style_pools = {
        "dawn": ["photoreal", "watercolor", "ink"],
        "rain": ["ink", "watercolor", "photoreal"],
        "city": ["photoreal", "watercolor", "ink"],
    }
    pool = style_pools.get(quote.mood, ["photoreal", "watercolor", "ink"])
    recent_styles = state.get("recent_visual_styles", [])[-3:]
    candidates = [style for style in pool if style not in recent_styles]
    seeded = random.Random(f"{quote.quote_id}|{date_iso}|non-ai-visual-style")
    return seeded.choice(candidates or pool)
