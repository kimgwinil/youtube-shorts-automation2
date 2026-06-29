from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import json
import os
from pathlib import Path
import random
from typing import Any, Dict, List

from openai import OpenAI
from google import genai
from google.genai import types

from .daily_context import DailyContext
from .script_builder import QuoteEntry, VideoScript, _load_quotes
from .state_store import load_state, save_state


@dataclass
class DailyPackage:
    script: VideoScript
    background_path: Path | None
    bgm_signature: str


@dataclass
class CreativeDirection:
    theme: str
    emotion: str
    visual_style: str
    scene_hint_ko: str
    scene_prompt_en: str
    bgm_mode: str
    bgm_prompt_en: str
    avoid: List[str]


def build_daily_package(
    quotes_file: Path,
    state_file: Path,
    output_dir: Path,
    openai_api_key: str,
    text_model: str,
    image_model: str,
    gemini_api_key: str,
    context: DailyContext,
    variation_seed: str = "",
) -> DailyPackage:
    state = load_state(state_file)
    quote = _choose_quote(quotes_file, state, context, variation_seed=variation_seed)
    try:
        direction = _classify_creative_direction(quote, state, openai_api_key, text_model, context, variation_seed=variation_seed)
    except Exception as exc:
        print(f"[text] OpenAI creative direction failed; trying Gemini fallback: {exc}")
        direction = _classify_creative_direction_with_gemini(
            quote, state, gemini_api_key, context, variation_seed=variation_seed
        )
    # 배경 이미지: GPT-4o 생성 프롬프트를 거치지 않고 scene_hint를 Imagen에 직접 전달
    background_path: Path | None = None
    try:
        background_path = _generate_background_from_direction(
            direction, quote, output_dir, gemini_api_key, image_model,
            openai_api_key=openai_api_key, variation_seed=variation_seed,
        )
    except Exception as exc:
        print(f"[image] Gemini/Imagen 배경 생성 실패, 로컬 fallback 사용: {exc}")
    try:
        script = _generate_unique_script(quote, direction, state, openai_api_key, text_model, context)
    except Exception as exc:
        print(f"[text] OpenAI script generation failed; trying Gemini fallback: {exc}")
        script = _generate_unique_script_with_gemini(quote, direction, state, gemini_api_key, context)
    bgm_signature = _music_signature(script, context)

    _append_unique(state, "used_quotes", quote.quote_id, 120)
    _append_unique(state, "recent_quote_ids", quote.quote_id, 20)
    _append_unique(state, "recent_titles", script.title, 20)
    _append_unique(state, "recent_visual_styles", script.visual_style, 20)
    _append_unique(state, "recent_image_fingerprints", _image_fingerprint(script), 20)
    _append_unique(state, "recent_music_signatures", bgm_signature, 20)
    _append_unique(state, "recent_dates", context.date_iso, 20)
    save_state(state_file, state)

    return DailyPackage(script=script, background_path=background_path, bgm_signature=bgm_signature)


def _generate_unique_script(
    quote: QuoteEntry,
    direction: CreativeDirection,
    state: Dict[str, Any],
    api_key: str,
    text_model: str,
    context: DailyContext,
) -> VideoScript:
    recent_titles = set(state.get("recent_titles", [])[-12:])
    recent_fingerprints = set(state.get("recent_image_fingerprints", [])[-12:])
    avoid_note = ""
    script: VideoScript | None = None
    for attempt in range(4):
        script = _generate_script_with_ai(
            quote,
            direction,
            state,
            api_key,
            text_model,
            context,
            avoid_note=avoid_note,
        )
        if script.title not in recent_titles and _image_fingerprint(script) not in recent_fingerprints:
            return script
        avoid_note = (
            "이전 결과와 너무 비슷합니다. 제목 표현과 시각 묘사를 더 다르게 바꾸고, "
            "도입 문장과 마무리 문장도 전혀 다른 리듬으로 작성하세요."
        )
    if script is None:
        raise RuntimeError("AI 스크립트 생성에 실패했습니다.")
    return script


def _generate_unique_script_with_gemini(
    quote: QuoteEntry,
    direction: CreativeDirection,
    state: Dict[str, Any],
    api_key: str,
    context: DailyContext,
) -> VideoScript:
    if not api_key:
        raise RuntimeError("Gemini API key is not configured.")
    recent_titles = set(state.get("recent_titles", [])[-12:])
    recent_fingerprints = set(state.get("recent_image_fingerprints", [])[-12:])
    avoid_note = ""
    script: VideoScript | None = None
    for _ in range(3):
        script = _generate_script_with_gemini(
            quote,
            direction,
            state,
            api_key,
            context,
            avoid_note=avoid_note,
        )
        if script.title not in recent_titles and _image_fingerprint(script) not in recent_fingerprints:
            return script
        avoid_note = (
            "이전 결과와 너무 비슷합니다. 제목 표현과 시각 묘사를 더 다르게 바꾸고, "
            "도입 문장과 마무리 문장도 전혀 다른 리듬으로 작성하세요."
        )
    if script is None:
        raise RuntimeError("Gemini 스크립트 생성에 실패했습니다.")
    return script


def _choose_quote(quotes_file: Path, state: Dict[str, Any], context: DailyContext, variation_seed: str = "") -> QuoteEntry:
    quotes = _load_quotes(quotes_file)
    recent_ids = set(state.get("recent_quote_ids", []))
    candidates = [quote for quote in quotes if quote.quote_id not in recent_ids]
    if not candidates:
        candidates = quotes

    mood_matched = [quote for quote in candidates if quote.mood == context.mood_hint]
    pool = mood_matched or candidates
    seed_str = f"{context.date_iso}|{context.weekday_name_ko}|{context.weather_summary_ko}|{variation_seed}"
    seeded = random.Random(seed_str)
    return seeded.choice(pool)


def _generate_script_with_ai(
    quote: QuoteEntry,
    direction: CreativeDirection,
    state: Dict[str, Any],
    api_key: str,
    text_model: str,
    context: DailyContext,
    avoid_note: str = "",
) -> VideoScript:
    client = OpenAI(api_key=api_key)
    recent_titles = state.get("recent_titles", [])[-8:]
    recent_visual_fingerprints = state.get("recent_image_fingerprints", [])[-8:]
    recent_visual_styles = state.get("recent_visual_styles", [])[-6:]
    prompt = f"""
너는 한국어 유튜브 쇼츠 작가다.
다음 고정 명언을 바탕으로 오늘 업로드할 한국어 쇼츠용 결과를 JSON으로만 출력하라.

오늘 정보:
- 날짜: {context.date_iso}
- 요일: {context.weekday_name_ko}
- 계절: {context.season_ko}
- 날씨 공기감: {context.weather_summary_ko}
- 추천 분위기: {context.mood_hint}

고정 명언 정보:
- author: {quote.author}
- source: {quote.source}
- quote: {quote.quote}
- interpretation: {quote.interpretation}
- mood: {quote.mood}
- visual_style: {direction.visual_style}
- bgm_mood: {quote.bgm_mood}
- context: {quote.context}

최근 제목:
{json.dumps(recent_titles, ensure_ascii=False)}

최근 시각 fingerprint:
{json.dumps(recent_visual_fingerprints, ensure_ascii=False)}

최근 사용 스타일:
{json.dumps(recent_visual_styles, ensure_ascii=False)}

이번 장면 힌트:
- style: {direction.visual_style}
- scene_ko: {direction.scene_hint_ko}
- scene_en: {direction.scene_prompt_en}

분류 트랙 결과:
- theme: {direction.theme}
- emotion: {direction.emotion}
- bgm_mode: {direction.bgm_mode}
- bgm_prompt_en: {direction.bgm_prompt_en}
- avoid: {json.dumps(direction.avoid, ensure_ascii=False)}

규칙:
1. 명언 원문은 바꾸지 말 것.
2. lines는 6개, 7개, 또는 8개 (명언의 깊이와 전개에 맞게 선택).
3. 모든 문장은 한국어.
4. 첫 줄은 시선이 멈추는 도입 — 구체적 장면이나 질문으로 시작할 것.
5. 명언 원문 또는 그 번역은 반드시 한 줄로 독립 배치할 것.
6. 마지막 줄은 긴 여운이 남는 마무리 — 추상적 격언이 아닌 감각적 문장으로 끝낼 것.
7. title은 최근 제목과 겹치지 않게, 클릭을 유도하는 제목으로.
8. visual_prompt는 오늘 날씨와 계절감이 드러나게.
9. JSON 외 다른 텍스트 금지.
10. 최근 결과와 비슷한 표현을 반복하지 말 것.
11. 각 lines 문장은 30~55자 내외로 나레이션으로 들었을 때 자연스럽게 끊길 것.
10. visual_prompt는 인물 중심 캐릭터 이미지가 아니라 배경 중심 장면이어야 한다.
11. 얼굴 클로즈업, 반복 가능한 동일 캐릭터, 애니풍 주인공, 마스코트형 인물은 금지한다.
12. 사람이 필요하면 작고 익명적인 실루엣 또는 뒷모습 한 명 이하만 허용한다.
13. 소품, 건축, 자연, 빛, 날씨 묘사를 우선하고 장면의 주인공은 분위기여야 한다.
14. 특정 도시의 랜드마크·스카이라인·도심 전경을 반복하지 말 것. 제목에 도시명을 넣지 말 것.
15. 장면은 아래 중 명언 분위기에 맞는 것을 골라 매번 다르게 변주할 것:
    동양: 산사 처마, 대나무 숲 오솔길, 고요한 연못, 한지 마루, 먹물 서재, 돌담 골목, 강변 정자
    자연: 안개 낀 산릉, 이슬 맺힌 풀밭, 폭우 뒤 하늘, 설원 침엽수, 사막 능선의 빛, 해안 절벽
    실내: 오래된 유럽 도서관, 스칸디나비아 미니멀 작업실, 빈티지 서재, 캔들 켜진 다락방, 박물관 복도
    도시: 이른 새벽 골목, 기차역 플랫폼, 빗속의 카페 창가, 공원 벤치, 지하철 창문
16. visual_style은 반드시 `{direction.visual_style}`로 유지할 것.
17. image_prompt_en은 자연스러운 영어 한 문단으로 작성하고, 이미지 생성 모델에 직접 넣을 수 있어야 한다.
18. bgm_prompt_en은 자연스러운 영어 한 문단으로 작성하고, 음악 생성 모델에 직접 넣을 수 있어야 한다.

추가 지시:
{avoid_note or "없음"}

필수 JSON 스키마:
{{
  "title": "...",
  "description": "...",
  "tags": ["...", "..."],
  "lines": ["...", "..."],
  "author_line": "...",
  "source_line": "...",
  "visual_prompt": "...",
  "image_prompt_en": "...",
  "bgm_prompt_en": "...",
  "visual_style": "{direction.visual_style}",
  "bgm_mood": "{quote.bgm_mood}",
  "total_duration": 24.0
}}
"""
    response = client.chat.completions.create(
        model=text_model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or ""
    parsed = json.loads(raw)
    return VideoScript(
        quote=quote,
        title=parsed["title"][:90],
        description=parsed["description"],
        tags=parsed["tags"],
        lines=parsed["lines"],
        author_line=parsed["author_line"],
        source_line=parsed["source_line"],
        visual_prompt=parsed["visual_prompt"],
        image_prompt_en=parsed.get(
            "image_prompt_en",
            _build_image_prompt_en(parsed["visual_prompt"], direction.visual_style, direction.scene_prompt_en),
        ),
        bgm_prompt_en=parsed.get("bgm_prompt_en", direction.bgm_prompt_en),
        visual_style=parsed.get("visual_style", direction.visual_style),
        total_duration=float(parsed.get("total_duration", max(24.0, len(parsed["lines"]) * 3.8))),
    )


def _generate_script_with_gemini(
    quote: QuoteEntry,
    direction: CreativeDirection,
    state: Dict[str, Any],
    api_key: str,
    context: DailyContext,
    avoid_note: str = "",
) -> VideoScript:
    from google import genai
    from google.genai import types

    recent_titles = state.get("recent_titles", [])[-8:]
    recent_visual_fingerprints = state.get("recent_image_fingerprints", [])[-8:]
    recent_visual_styles = state.get("recent_visual_styles", [])[-6:]
    prompt = f"""
너는 한국어 유튜브 쇼츠 작가다.
다음 고정 명언을 바탕으로 오늘 업로드할 한국어 쇼츠용 결과를 JSON으로만 출력하라.

오늘 정보:
- 날짜: {context.date_iso}
- 요일: {context.weekday_name_ko}
- 계절: {context.season_ko}
- 날씨 공기감: {context.weather_summary_ko}
- 추천 분위기: {context.mood_hint}

고정 명언 정보:
- author: {quote.author}
- source: {quote.source}
- quote: {quote.quote}
- interpretation: {quote.interpretation}
- mood: {quote.mood}
- visual_style: {direction.visual_style}
- bgm_mood: {quote.bgm_mood}
- context: {quote.context}

최근 제목:
{json.dumps(recent_titles, ensure_ascii=False)}

최근 시각 fingerprint:
{json.dumps(recent_visual_fingerprints, ensure_ascii=False)}

최근 사용 스타일:
{json.dumps(recent_visual_styles, ensure_ascii=False)}

이번 장면 힌트:
- style: {direction.visual_style}
- scene_ko: {direction.scene_hint_ko}
- scene_en: {direction.scene_prompt_en}

분류 트랙 결과:
- theme: {direction.theme}
- emotion: {direction.emotion}
- bgm_mode: {direction.bgm_mode}
- bgm_prompt_en: {direction.bgm_prompt_en}
- avoid: {json.dumps(direction.avoid, ensure_ascii=False)}

규칙:
1. 명언 원문은 바꾸지 말 것.
2. lines는 6개, 7개, 또는 8개.
3. 모든 문장은 한국어.
4. 첫 줄은 구체적 장면이나 질문으로 시작할 것.
5. 명언 원문 또는 그 번역은 반드시 한 줄로 독립 배치할 것.
6. 마지막 줄은 감각적 문장으로 끝낼 것.
7. title은 최근 제목과 겹치지 않게 작성할 것.
8. visual_prompt는 배경 중심 장면이어야 하며 인물 중심 캐릭터, 얼굴 클로즈업, 애니풍 주인공은 금지한다.
9. visual_style은 반드시 `{direction.visual_style}`로 유지할 것.
10. image_prompt_en과 bgm_prompt_en은 자연스러운 영어 한 문단으로 작성할 것.
11. JSON 외 다른 텍스트 금지.

추가 지시:
{avoid_note or "없음"}

필수 JSON 스키마:
{{
  "title": "...",
  "description": "...",
  "tags": ["...", "..."],
  "lines": ["...", "..."],
  "author_line": "...",
  "source_line": "...",
  "visual_prompt": "...",
  "image_prompt_en": "...",
  "bgm_prompt_en": "...",
  "visual_style": "{direction.visual_style}",
  "bgm_mood": "{quote.bgm_mood}",
  "total_duration": 24.0
}}
"""
    client = genai.Client(api_key=api_key)
    model = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.85,
            response_mime_type="application/json",
        ),
    )
    parsed = json.loads(response.text or "{}")
    return VideoScript(
        quote=quote,
        title=parsed["title"][:90],
        description=parsed["description"],
        tags=parsed["tags"],
        lines=parsed["lines"],
        author_line=parsed["author_line"],
        source_line=parsed["source_line"],
        visual_prompt=parsed["visual_prompt"],
        image_prompt_en=parsed.get(
            "image_prompt_en",
            _build_image_prompt_en(parsed["visual_prompt"], direction.visual_style, direction.scene_prompt_en),
        ),
        bgm_prompt_en=parsed.get("bgm_prompt_en", direction.bgm_prompt_en),
        visual_style=parsed.get("visual_style", direction.visual_style),
        total_duration=float(parsed.get("total_duration", max(24.0, len(parsed["lines"]) * 3.8))),
    )


_STYLE_DESC: dict[str, str] = {
    "photoreal": (
        "photorealistic DSLR photography, 8K resolution, physically accurate lighting, "
        "sharp focus, single coherent scene, cinematic color grading, natural depth of field, "
        "award-winning landscape photography quality"
    ),
    "watercolor": "soft watercolor illustration with delicate brushwork and paper texture, single unified composition",
    "ink": "East Asian ink wash painting with expressive brushwork and generous empty space, single unified composition",
    "calligraphy": "East Asian ink wash painting style with elegant brushwork and serene empty space, no fake script or unreadable glyph-like marks, single unified composition",
}

_THEME_SCENE_FALLBACK: dict[str, str] = {
    "dawn": "misty mountain temple path at dawn, stone steps covered in morning dew, soft golden light filtering through pine branches",
    "rain": "old wooden pavilion beside a still pond in gentle rain, ripples on the water surface, foggy distant hills",
    "city": "quiet candlelit reading room with tall bookshelves, warm amber light, leather-bound books, a wooden writing desk",
}


def _dalle3_prompt(style_desc: str, scene: str) -> str:
    return (
        f"Background image for a Korean inspirational quote short video. "
        f"Style: {style_desc}. Scene: {scene}. "
        "Do not invent any background text or symbols. "
        "No inaccurate Korean, no pseudo-letters, no unreadable glyph-like marks, no brush strokes that resemble writing, "
        "no signs, no banners, no stamps, no watermarks, no captions, no labels. "
        "Korean title/subtitle text will be rendered later by the video pipeline, not inside the background image. "
        "LAYOUT ZONES (strict): "
        "① BOTTOM 40% of frame: kept completely plain, calm, and empty — "
        "no objects, no detail, no text — reserved for subtitle text overlay. "
        "② TOP-LEFT corner (left 55%, top 14%): plain and uncluttered — "
        "reserved for author name overlay. "
        "③ CENTER and upper-right: main visual subject and atmosphere. "
        "Single unified scene only — no collage, no montage, no split frame. "
        "No people, no faces, no anime characters. "
        "Vertical 9:16 portrait orientation."
    )


TARGET_RESOLUTION = (1080, 1920)  # 9:16 세로 쇼츠


def _normalize_to_9_16(image_path: Path, target: tuple[int, int] = TARGET_RESOLUTION) -> None:
    """생성된 배경 이미지를 정확한 9:16(1080x1920) 프레임으로 맞춘다.

    GPT Image portrait output uses 1024x1536 and DALL-E 3 uses 1024x1792;
    Imagen can still return slightly different dimensions by model, so this
    enforces the final frame.
    이렇게 하면 저장되는 배경 자체가 9:16이 되어 렌더 단계의 추가 크롭이
    예측 가능해지고, 배경 비율이 9:16이 아닌 문제를 방지한다.
    """
    try:
        from PIL import Image, ImageOps

        with Image.open(image_path) as im:
            im = im.convert("RGB")
            fitted = ImageOps.fit(im, target, method=Image.LANCZOS, centering=(0.5, 0.5))
            fitted.save(image_path)
    except Exception as exc:  # 정규화 실패 시 원본을 그대로 두고 렌더 단계 크롭에 위임
        print(f"[image] 9:16 정규화 실패(원본 유지): {exc}")


def _try_openai_image(prompt: str, output_path: Path, openai_api_key: str) -> str | None:
    if not openai_api_key:
        return None
    import base64
    import urllib.request
    from openai import OpenAI

    client = OpenAI(api_key=openai_api_key)
    preferred_model = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
    quality = os.environ.get("OPENAI_IMAGE_QUALITY", "low")
    ordered_models = [preferred_model, "gpt-image-1", "gpt-image-1-mini", "dall-e-3", "dall-e-2"]
    candidates: list[tuple[str, dict[str, str]]] = []
    for model in ordered_models:
        if any(existing == model for existing, _ in candidates):
            continue
        if model.startswith("gpt-image-"):
            candidates.append((model, {"size": "1024x1536", "quality": quality}))
        elif model == "dall-e-3":
            candidates.append((model, {"size": "1024x1792", "quality": "hd"}))
        elif model == "dall-e-2":
            candidates.append((model, {"size": "1024x1024"}))
        else:
            candidates.append((model, {"size": "1024x1536", "quality": quality}))

    for model, params in candidates:
        try:
            resp = client.images.generate(model=model, prompt=prompt, n=1, **params)
            image_data = resp.data[0]
            b64_json = getattr(image_data, "b64_json", None)
            if b64_json:
                image_bytes = base64.b64decode(b64_json)
            else:
                image_url = getattr(image_data, "url", None)
                if not image_url:
                    raise ValueError("이미지 응답에 b64_json/url이 없습니다.")
                with urllib.request.urlopen(image_url, timeout=60) as response:
                    image_bytes = response.read()
            output_path.write_bytes(image_bytes)
            _normalize_to_9_16(output_path)
            return model
        except Exception as exc:
            print(f"[image] OpenAI 이미지 모델 실패 ({model}): {exc}")
    return None


def _generate_background_from_direction(
    direction: CreativeDirection,
    quote: QuoteEntry,
    output_dir: Path,
    api_key: str,
    image_model: str,
    openai_api_key: str = "",
    variation_seed: str = "",
) -> Path:
    if not api_key:
        raise RuntimeError("Gemini API 키가 없어 배경 이미지를 생성할 수 없습니다.")
    client = genai.Client(api_key=api_key)
    output_dir.mkdir(parents=True, exist_ok=True)

    seed = sha1(
        (direction.scene_prompt_en + direction.visual_style + quote.quote_id + variation_seed).encode("utf-8")
    ).hexdigest()[:12]
    filename = output_dir / f"{seed}_bg.png"

    style_desc = _STYLE_DESC.get(direction.visual_style, _STYLE_DESC["photoreal"])
    theme_fallback = _THEME_SCENE_FALLBACK.get(direction.theme, _THEME_SCENE_FALLBACK["dawn"])

    no_text = (
        "Do not invent any background text or symbols. No inaccurate Korean, no fake letters, "
        "no unreadable glyph-like marks, no brush strokes resembling writing or glyphs, no signage, "
        "no watermark, no stamp, no label, no caption. Pure image only."
    )
    no_collage = (
        "Single unified scene — no collage, no double exposure, no montage, "
        "no multiple overlapping images, no split frame, no image-within-image."
    )
    layout = (
        "LAYOUT ZONES (strict): "
        "① TOP-LEFT corner (roughly left 55%, top 14% of frame) must be kept plain and uncluttered — "
        "no busy detail, no text, no objects — reserved for author name overlay. "
        "② BOTTOM 38% of frame must be kept plain, calm, and free of all detail — "
        "no objects, no text, no strong lines — reserved for subtitle text overlay. "
        "③ CENTER and upper-right area carry the main visual subject and atmosphere."
    )
    base_suffix = (
        f"Vertical 9:16 format. {no_collage} {no_text} {layout} "
        "No city skyline, no Seoul landmarks, no recurring character, "
        "no anime, no mascot, no portrait, no close-up face. "
        "If a person appears, keep them tiny, distant, or shown from behind only."
    )

    # ── 1차: OpenAI 이미지 모델 (GPT Image 우선, DALL-E는 fallback) ──
    openai_prompt = _dalle3_prompt(style_desc, direction.scene_prompt_en)
    openai_model = _try_openai_image(openai_prompt, filename, openai_api_key)
    if openai_model:
        print(f"[image] OpenAI 배경 생성 완료 ({openai_model}): {filename.name} / scene: {direction.scene_hint_ko}")
        return filename

    # ── 2차 fallback: Imagen ──
    safe_prompts = [
        f"{style_desc}. {direction.scene_prompt_en}. {base_suffix}",
        f"{style_desc}. {direction.scene_prompt_en[:180].rstrip()}. {no_collage} {no_text} {layout} Atmospheric background, no people, vertical 9:16.",
        f"{style_desc}. {theme_fallback}. {no_collage} {no_text} {layout} Peaceful atmosphere, no figures, vertical 9:16.",
    ]

    image_bytes: bytes | None = None
    used_attempt = 0
    for attempt, attempt_prompt in enumerate(safe_prompts):
        try:
            response = client.models.generate_images(
                model=image_model,
                prompt=attempt_prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="9:16",
                    output_mime_type="image/png",
                    person_generation="dont_allow",
                ),
            )
            generated = response.generated_images[0] if response.generated_images else None
            image = generated.image if generated else None
            if image and image.image_bytes:
                image_bytes = image.image_bytes
                used_attempt = attempt + 1
                break
        except Exception as exc:
            print(f"[image] Imagen 시도 {attempt + 1} 실패: {exc}")

    if not image_bytes:
        raise RuntimeError("배경 이미지 생성 결과가 비어 있습니다. (3회 재시도 모두 실패)")

    filename.write_bytes(image_bytes)
    _normalize_to_9_16(filename)
    retry_note = f" (재시도 {used_attempt}회)" if used_attempt > 1 else ""
    print(f"[image] Gemini Imagen 배경 생성 완료{retry_note}: {filename.name} / scene: {direction.scene_hint_ko}")
    return filename


def _generate_background_image(
    script: VideoScript,
    output_dir: Path,
    api_key: str,
    image_model: str,
) -> Path:
    if not api_key:
        raise RuntimeError("Gemini API 키가 없어 배경 이미지를 생성할 수 없습니다.")
    client = genai.Client(api_key=api_key)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"{sha1((script.title + script.image_prompt_en).encode('utf-8')).hexdigest()[:12]}_bg.png"
    prompt = _build_image_prompt(script)
    response = client.models.generate_images(
        model=image_model,
        prompt=prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="9:16",
            output_mime_type="image/png",
            person_generation="dont_allow",
            include_rai_reason=True,
            include_safety_attributes=True,
        ),
    )
    generated = response.generated_images[0] if response.generated_images else None
    image = generated.image if generated else None
    if not image or not image.image_bytes:
        raise RuntimeError("배경 이미지 생성 결과가 비어 있습니다.")
    filename.write_bytes(image.image_bytes)
    _normalize_to_9_16(filename)
    return filename


def _build_image_prompt(script: VideoScript) -> str:
    composition_variants = [
        "empty foreground with atmospheric depth",
        "still-life composition with architecture or nature as the subject",
        "wide environmental scene with no central figure",
        "quiet landscape or interior with generous negative space",
        "subtle symbolic objects instead of a person",
        "distant tiny silhouette only if absolutely needed, never a portrait",
    ]
    variant = composition_variants[
        int(sha1((script.title + script.quote.quote_id).encode("utf-8")).hexdigest()[:2], 16) % len(composition_variants)
    ]
    return (
        f"{script.image_prompt_en}. "
        f"{variant}. "
        f"Render this in {script.visual_style} style. "
        "Background for a Korean quote short video. "
        "Single unified scene — no collage, no double exposure, no montage, no split frame. "
        "Do not invent any background text or symbols: no inaccurate Korean, "
        "no fake letters, no unreadable glyph-like marks, "
        "no signage, no watermark, no label. "
        "LAYOUT ZONES: "
        "top-left (55% wide, 14% tall) kept plain and empty — author name overlay goes here; "
        "bottom 38% kept plain, calm, and empty — subtitle text overlay goes here; "
        "center and upper-right hold the main atmospheric scene. "
        "No recurring character, no anime, no mascot, no portrait, no close-up face. "
        "No Seoul skyline, no N Seoul Tower, no repeated landmark. "
        "Choose ONE motif that fits the quote: "
        "East Asian (garden, bamboo forest, temple eaves, ink study, stone path, river pavilion), "
        "Nature (misty mountain, dewy meadow, snowy pine forest, sea cliff, desert dune), "
        "Interior (Victorian library, Scandinavian studio, candlelit attic, museum corridor), "
        "Urban (dawn alley, train platform, rainy cafe window, park bench in mist). "
        "If a person appears, keep them tiny, turned away, not identifiable."
    )


def _build_image_prompt_en(visual_prompt_ko: str, visual_style: str, scene_hint: str) -> str:
    style_map = {
        "photoreal": "photorealistic cinematic image",
        "watercolor": "soft watercolor illustration",
        "ink": "East Asian ink wash painting",
        "calligraphy": "East Asian ink wash painting without calligraphy, script, or glyph-like marks",
    }
    return (
        f"{style_map.get(visual_style, 'background-focused image')}, "
        f"{scene_hint}, inspired by this Korean brief: {visual_prompt_ko}. "
        "Atmospheric background only, no central character, no portrait, clean subtitle-safe lower center. "
        "Zero text anywhere, no fake letters, no glyph-like marks, no calligraphy script, no signage."
    )


def _classify_creative_direction(
    quote: QuoteEntry,
    state: Dict[str, Any],
    api_key: str,
    text_model: str,
    context: DailyContext,
    variation_seed: str = "",
) -> CreativeDirection:
    if not api_key:
        visual_style = _choose_visual_style(quote, state, context, variation_seed=variation_seed)
        scene_hint = _choose_scene_hint(quote, context, variation_seed=variation_seed)
        return CreativeDirection(
            theme=quote.mood,
            emotion=quote.bgm_mood,
            visual_style=visual_style,
            scene_hint_ko=scene_hint,
            scene_prompt_en=scene_hint,
            bgm_mode=quote.bgm_mood,
            bgm_prompt_en=f"inspirational instrumental background score, {quote.interpretation}, no heavy bass, no vocals",
            avoid=["Seoul skyline", "repeated character", "heavy bass drone"],
        )

    client = OpenAI(api_key=api_key)
    recent_styles = state.get("recent_visual_styles", [])[-4:]
    recent_titles = state.get("recent_titles", [])[-6:]
    fallback_style = _choose_visual_style(quote, state, context, variation_seed=variation_seed)
    fallback_scene = _choose_scene_hint(quote, context, variation_seed=variation_seed)
    prompt = f"""
너는 쇼츠 제작을 위한 분류기다. 아래 명언에 대해 생성 트랙이 바로 사용할 JSON만 출력하라.

오늘 정보:
- 날짜: {context.date_iso}
- 요일: {context.weekday_name_ko}
- 계절: {context.season_ko}
- 날씨 공기감: {context.weather_summary_ko}

명언 정보:
- author: {quote.author}
- source: {quote.source}
- quote: {quote.quote}
- interpretation: {quote.interpretation}
- mood: {quote.mood}
- visual_style default: {quote.visual_style}
- bgm_mood default: {quote.bgm_mood}
- context: {quote.context}

최근 스타일:
{json.dumps(recent_styles, ensure_ascii=False)}

최근 제목:
{json.dumps(recent_titles, ensure_ascii=False)}

규칙:
1. 이미지와 음악 생성에 모두 쓸 수 있는 결정값만 출력.
2. 특정 도시 랜드마크·스카이라인·도시명을 scene에 넣지 말 것.
3. 실사, 수채화, 수묵화, 서화 중 하나를 고르고 최근 스타일과 반복을 피할 것.
4. scene_hint_ko는 한국어 한 문장, scene_prompt_en과 bgm_prompt_en은 반드시 영어로만 작성할 것 (한국어 혼용 금지).
5. scene_prompt_en은 Imagen 이미지 생성 모델에 직접 입력할 수 있어야 하므로, 명확한 영어 장면 묘사로 작성할 것.
6. avoid에는 반복을 막을 금지 요소 3~5개를 넣을 것.
7. 장면은 동양 전통 공간, 자연 풍경, 유럽 인테리어, 미니멀 공간 등을 명언 분위기에 맞게 다양하게 선택할 것.
8. scene_prompt_en에 사람·얼굴·캐릭터 묘사를 넣지 말 것. 배경·빛·소품·자연 묘사만 사용할 것.

JSON 스키마:
{{
  "theme": "...",
  "emotion": "...",
  "visual_style": "{fallback_style}",
  "scene_hint_ko": "{fallback_scene}",
  "scene_prompt_en": "...",
  "bgm_mode": "{quote.bgm_mood}",
  "bgm_prompt_en": "...",
  "avoid": ["...", "..."]
}}
"""
    response = client.chat.completions.create(
        model=text_model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    parsed = json.loads(response.choices[0].message.content or "{}")
    return CreativeDirection(
        theme=parsed.get("theme", quote.mood),
        emotion=parsed.get("emotion", quote.bgm_mood),
        visual_style=parsed.get("visual_style", fallback_style),
        scene_hint_ko=parsed.get("scene_hint_ko", fallback_scene),
        scene_prompt_en=parsed.get("scene_prompt_en", fallback_scene),
        bgm_mode=parsed.get("bgm_mode", quote.bgm_mood),
        bgm_prompt_en=parsed.get(
            "bgm_prompt_en",
            f"inspirational instrumental background score, {quote.interpretation}, no heavy bass, no vocals",
        ),
        avoid=parsed.get("avoid", ["Seoul skyline", "repeated character", "heavy bass drone"]),
    )


def _classify_creative_direction_with_gemini(
    quote: QuoteEntry,
    state: Dict[str, Any],
    api_key: str,
    context: DailyContext,
    variation_seed: str = "",
) -> CreativeDirection:
    if not api_key:
        raise RuntimeError("Gemini API key is not configured.")
    from google import genai
    from google.genai import types

    recent_styles = state.get("recent_visual_styles", [])[-4:]
    recent_titles = state.get("recent_titles", [])[-6:]
    fallback_style = _choose_visual_style(quote, state, context, variation_seed=variation_seed)
    fallback_scene = _choose_scene_hint(quote, context, variation_seed=variation_seed)
    prompt = f"""
너는 쇼츠 제작을 위한 분류기다. 아래 명언에 대해 생성 트랙이 바로 사용할 JSON만 출력하라.

오늘 정보:
- 날짜: {context.date_iso}
- 요일: {context.weekday_name_ko}
- 계절: {context.season_ko}
- 날씨 공기감: {context.weather_summary_ko}

명언 정보:
- author: {quote.author}
- source: {quote.source}
- quote: {quote.quote}
- interpretation: {quote.interpretation}
- mood: {quote.mood}
- visual_style default: {quote.visual_style}
- bgm_mood default: {quote.bgm_mood}
- context: {quote.context}

최근 스타일:
{json.dumps(recent_styles, ensure_ascii=False)}

최근 제목:
{json.dumps(recent_titles, ensure_ascii=False)}

규칙:
1. 이미지와 음악 생성에 모두 쓸 수 있는 결정값만 출력.
2. 특정 도시 랜드마크·스카이라인·도시명을 scene에 넣지 말 것.
3. 실사, 수채화, 수묵화, 서화 중 하나를 고르고 최근 스타일과 반복을 피할 것.
4. scene_hint_ko는 한국어 한 문장, scene_prompt_en과 bgm_prompt_en은 반드시 영어로만 작성할 것.
5. scene_prompt_en에 사람·얼굴·캐릭터 묘사를 넣지 말 것. 배경·빛·소품·자연 묘사만 사용할 것.
6. avoid에는 반복을 막을 금지 요소 3~5개를 넣을 것.
7. JSON 외 다른 텍스트 금지.

JSON 스키마:
{{
  "theme": "...",
  "emotion": "...",
  "visual_style": "{fallback_style}",
  "scene_hint_ko": "{fallback_scene}",
  "scene_prompt_en": "...",
  "bgm_mode": "{quote.bgm_mood}",
  "bgm_prompt_en": "...",
  "avoid": ["...", "..."]
}}
"""
    client = genai.Client(api_key=api_key)
    model = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.8,
            response_mime_type="application/json",
        ),
    )
    parsed = json.loads(response.text or "{}")
    return CreativeDirection(
        theme=parsed.get("theme", quote.mood),
        emotion=parsed.get("emotion", quote.bgm_mood),
        visual_style=parsed.get("visual_style", fallback_style),
        scene_hint_ko=parsed.get("scene_hint_ko", fallback_scene),
        scene_prompt_en=parsed.get("scene_prompt_en", fallback_scene),
        bgm_mode=parsed.get("bgm_mode", quote.bgm_mood),
        bgm_prompt_en=parsed.get(
            "bgm_prompt_en",
            f"inspirational instrumental background score, {quote.interpretation}, no heavy bass, no vocals",
        ),
        avoid=parsed.get("avoid", ["Seoul skyline", "repeated character", "heavy bass drone"]),
    )


def _music_signature(script: VideoScript, context: DailyContext) -> str:
    raw = (
        f"{script.quote.quote_id}|{script.title}|{script.quote.bgm_mood}|"
        f"{script.visual_style}|{context.date_iso}|{context.weather_summary_ko}"
    )
    return sha1(raw.encode("utf-8")).hexdigest()[:12]


def _image_fingerprint(script: VideoScript) -> str:
    raw = f"{script.quote.quote_id}|{script.visual_prompt}|{script.title}"
    return sha1(raw.encode("utf-8")).hexdigest()[:16]


def _append_unique(state: Dict[str, Any], key: str, value: str, limit: int) -> None:
    items = [item for item in state.get(key, []) if item != value]
    items.append(value)
    state[key] = items[-limit:]


def _choose_visual_style(quote: QuoteEntry, state: Dict[str, Any], context: DailyContext, variation_seed: str = "") -> str:
    style_pools = {
        "dawn": ["photoreal", "watercolor", "ink"],
        "rain": ["ink", "watercolor", "photoreal"],
        "city": ["photoreal", "watercolor", "ink"],
    }
    pool = style_pools.get(quote.mood, ["photoreal", "watercolor", "ink"])
    recent_styles = state.get("recent_visual_styles", [])[-3:]
    candidates = [style for style in pool if style not in recent_styles]
    candidates = candidates or pool
    seeded = random.Random(f"{quote.quote_id}|{context.date_iso}|{context.weather_summary_ko}|visual-style|{variation_seed}")
    return seeded.choice(candidates)


def _choose_scene_hint(quote: QuoteEntry, context: DailyContext, variation_seed: str = "") -> str:
    scene_map = {
        "dawn": [
            "새벽 정원과 얇은 안개",
            "햇살이 스미는 서재와 책상",
            "조용한 강변 산책길",
            "한지와 붓이 놓인 마루",
            "안개 속 산사(山寺)의 처마와 이끼 낀 돌계단",
            "이슬 맺힌 대나무 숲 오솔길",
            "오래된 유럽 도서관의 새벽 빛과 먼지 입자",
            "설원 침엽수 숲의 첫 햇살",
            "사막 능선 위 새벽 하늘과 모래 물결",
            "연못가 정자와 수면에 비친 새벽빛",
            "스칸디나비아 통나무집 창가와 초원",
            "고요한 수도원 회랑과 촛불 그림자",
        ],
        "rain": [
            "비 내리는 창가와 젖은 돌길",
            "고요한 회랑과 빗물 고인 마당",
            "안개 낀 산길과 젖은 대나무",
            "조용한 작업실과 흐린 빛",
            "빗물 맺힌 기차 창문과 흐릿한 풍경",
            "지중해 골목의 비 내리는 오후와 빨래줄",
            "가을 낙엽 위로 내리는 빗속의 공원 벤치",
            "먹물이 번지는 한지와 빗소리",
            "젖은 돌담과 이끼, 흐린 산길",
            "빗속 카페 창가와 김이 오르는 찻잔",
            "폭우 뒤 잦아드는 하늘과 먼 산 능선",
        ],
        "city": [
            "정돈된 작업실과 창가 책상",
            "고요한 회의실과 노트",
            "이른 새벽 골목과 긴 그림자",
            "빈티지 아카이브 서가와 양피지 문서",
            "런던 빅토리아풍 도서관과 나무 계단",
            "스칸디나비아 미니멀 오피스와 흰 벽",
            "다락방 작업실과 비스듬히 드는 아침 빛",
            "새벽 기차역 플랫폼과 텅 빈 레일",
            "파리 아파르트망 창가의 이른 아침 커피",
            "박물관 복도와 오래된 액자들",
            "오래된 카페 카운터와 스팀 커피 머신",
            "열람실 창가와 쌓인 책들",
        ],
    }
    pool = scene_map.get(quote.mood, scene_map[context.mood_hint if context.mood_hint in scene_map else "dawn"])
    seeded = random.Random(f"{quote.quote_id}|{context.date_iso}|scene-hint|{variation_seed}")
    return seeded.choice(pool)
