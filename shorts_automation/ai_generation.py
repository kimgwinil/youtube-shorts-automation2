from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from pathlib import Path

from .daily_context import DailyContext
from .script_builder import EssayScript
from .state_store import load_state


ESSAY_TOPICS = [
    "사랑", "희망", "용기", "아침", "새벽", "친구", "도전", "감사",
    "성장", "자연", "봄", "여름", "가을", "겨울", "용서", "꿈",
    "시간", "기억", "그리움", "행복", "고독", "변화", "믿음", "여행",
    "가족", "이별", "만남", "눈물", "웃음", "바람", "별", "달",
    "비", "눈", "햇살", "고요", "침묵", "설렘", "위로", "치유",
    "정직", "겸손", "인내", "노력", "지혜", "평화", "자유", "창의",
]

VISUAL_STYLES = [
    "photoreal",
    "watercolor",
    "ink",
    "oil_painting",
    "pencil_sketch",
    "photography",
]

_STYLE_PREFIX: dict[str, str] = {
    "photoreal": "photorealistic, ultra-detailed, 8k, cinematic lighting, no text, no people",
    "watercolor": "beautiful watercolor painting, soft color washes, delicate brushstrokes, artistic, no text",
    "ink": "traditional East Asian ink painting, sumi-e style, minimal, flowing brushwork, no text",
    "oil_painting": "impressionist oil painting, rich impasto texture, vivid brushstrokes, museum quality, no text",
    "pencil_sketch": "detailed pencil sketch, fine linework, crosshatching, monochrome, artistic, no text",
    "photography": "professional photography, natural light, photojournalistic, shallow depth of field, no text",
}


@dataclass
class EssayPackage:
    script: EssayScript
    background_path: Path
    bgm_signature: str


def build_essay_package(
    state_file: Path,
    output_dir: Path,
    openai_api_key: str,
    text_model: str,
    image_model: str,
    gemini_api_key: str,
    context: DailyContext,
    variation_seed: str = "",
) -> EssayPackage:
    state = load_state(state_file)
    topic = _pick_topic(state=state, date_iso=context.date_iso, variation_seed=variation_seed)
    visual_style = _pick_visual_style(state=state, date_iso=context.date_iso, variation_seed=variation_seed)

    script = _generate_essay(
        topic=topic,
        visual_style=visual_style,
        context=context,
        openai_api_key=openai_api_key,
        text_model=text_model,
        variation_seed=variation_seed,
    )

    background_path = _generate_background(
        script=script,
        output_dir=output_dir,
        gemini_api_key=gemini_api_key,
        image_model=image_model,
        date_iso=context.date_iso,
        variation_seed=variation_seed,
    )

    sig_base = f"{context.date_iso}_{topic[:8]}{variation_seed[:6]}"
    bgm_signature = sig_base[:20].replace(" ", "_")

    return EssayPackage(script=script, background_path=background_path, bgm_signature=bgm_signature)


def _pick_topic(state: dict, date_iso: str, variation_seed: str) -> str:
    recent = state.get("recent_topics", [])[-6:]
    candidates = [t for t in ESSAY_TOPICS if t not in recent]
    seeded = random.Random(f"{date_iso}|topic|{variation_seed}")
    return seeded.choice(candidates or ESSAY_TOPICS)


def _pick_visual_style(state: dict, date_iso: str, variation_seed: str) -> str:
    recent = state.get("recent_visual_styles", [])[-3:]
    candidates = [s for s in VISUAL_STYLES if s not in recent]
    seeded = random.Random(f"{date_iso}|style|{variation_seed}")
    return seeded.choice(candidates or VISUAL_STYLES)


def _generate_essay(
    topic: str,
    visual_style: str,
    context: DailyContext,
    openai_api_key: str,
    text_model: str,
    variation_seed: str,
) -> EssayScript:
    from openai import OpenAI

    client = OpenAI(api_key=openai_api_key)

    system_prompt = (
        "당신은 감성적인 한국어 에세이 작가입니다.\n"
        "매일 아침 유튜브 숏츠용 짧은 에세이를 작성합니다.\n"
        "에세이는 화면에 5개의 문장/구절로 나뉘어 순차적으로 표시됩니다.\n"
        "각 구절은 약 9~10초 동안 화면에 표시되므로, 한 번에 읽기 좋은 분량(25~45자)으로 작성하세요.\n"
        "반드시 JSON만 출력하세요. 마크다운 코드블록 없이 순수 JSON으로만 응답합니다."
    )

    seed_note = f"\n(오늘의 창작 변주 번호: {variation_seed[:8]})" if variation_seed else ""
    user_prompt = (
        f"오늘의 배경 정보:\n"
        f"- 날짜: {context.date_iso} ({context.weekday_name_ko})\n"
        f"- 계절: {context.season_ko}\n"
        f"- 날씨 공기감: {context.weather_summary_ko}\n"
        f"- 주제: {topic}\n"
        f"- 이미지 스타일: {visual_style}{seed_note}\n\n"
        "요구사항:\n"
        "1. 위 주제로 감동적이고 아름다운 짧은 에세이를 정확히 5개의 구절로 작성하세요.\n"
        "2. 각 구절: 25~45자 (독립적으로 화면에 표시됨).\n"
        "3. 기존 문학·시·노래 문구를 인용한 경우 반드시 is_original=false, author=저자명, source=작품명 으로 설정하세요.\n"
        "4. 완전히 새롭게 창작한 경우 is_original=true, author='gikim', source='gikim'.\n"
        "5. 에세이 분위기에 맞는 배경 이미지와 음악 방향을 영어로 작성하세요.\n\n"
        "다음 JSON 형식으로만 응답하세요:\n"
        "{\n"
        '  "topic": "에세이 주제",\n'
        '  "lines": ["구절1", "구절2", "구절3", "구절4", "구절5"],\n'
        '  "is_original": true,\n'
        '  "author": "gikim",\n'
        '  "source": "gikim",\n'
        '  "mood": "calm",\n'
        '  "bgm_mood": "reflective",\n'
        '  "title": "유튜브 제목 (22자 이내, 해시태그 제외)",\n'
        '  "description": "에세이 내용 요약 (80자 이내)",\n'
        '  "tags": ["에세이", "감성", "아침"],\n'
        '  "image_prompt_en": "영어로 된 배경 이미지 프롬프트 (장소·빛·분위기 묘사, 사람 없이)"\n'
        '  "bgm_prompt_en": "영어로 된 BGM 프롬프트 (악기·분위기·템포 묘사)"\n'
        "}\n"
        "bgm_mood 옵션: meditative, reflective, focused\n"
        "mood 옵션: calm, hopeful, melancholic, peaceful, energetic"
    )

    response = client.chat.completions.create(
        model=text_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.85,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    data = json.loads(raw)

    lines = data.get("lines", [])
    if len(lines) != 5:
        lines = (lines + [""] * 5)[:5]

    is_original = bool(data.get("is_original", True))
    author = data.get("author", "gikim")
    source = data.get("source", "gikim")
    author_line = f"✍ {author}" if is_original else f"📖 {author}"
    source_line = source if is_original else f"출처: {source}"

    title_raw = data.get("title", f"{topic}에 대하여")
    title = title_raw if "#shorts" in title_raw.lower() else f"{title_raw} #Shorts"

    description = data.get("description", "\n".join(lines[:2]))
    tags = data.get("tags", ["에세이", "감성", topic])
    if "에세이" not in tags:
        tags.insert(0, "에세이")

    image_prompt_en = data.get("image_prompt_en", f"{topic} mood, {visual_style} art style, no people, serene")
    bgm_prompt_en = data.get("bgm_prompt_en", f"gentle ambient music matching {topic} theme, no bass")
    bgm_mood = data.get("bgm_mood", "reflective")
    if bgm_mood not in ("meditative", "reflective", "focused"):
        bgm_mood = "reflective"
    mood = data.get("mood", "calm")

    shorts_hashtags = "#Shorts #쇼츠 #에세이 #감성 #아침"
    full_description = f"{description}\n\n{shorts_hashtags}"

    return EssayScript(
        topic=topic,
        lines=lines,
        author_line=author_line,
        source_line=source_line,
        is_original=is_original,
        visual_style=visual_style,
        image_prompt_en=image_prompt_en,
        bgm_prompt_en=bgm_prompt_en,
        bgm_mood=bgm_mood,
        mood=mood,
        title=title[:100],
        description=full_description,
        tags=tags,
    )


def _generate_background(
    script: EssayScript,
    output_dir: Path,
    gemini_api_key: str,
    image_model: str,
    date_iso: str,
    variation_seed: str,
) -> Path:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("`google-genai` 패키지가 필요합니다.") from exc

    client = genai.Client(api_key=gemini_api_key)
    style_prefix = _STYLE_PREFIX.get(script.visual_style, "artistic, no text")
    base_prompt = script.image_prompt_en
    seed_suffix = f", variation {variation_seed[:6]}" if variation_seed else ""

    prompts = [
        f"{style_prefix}, {base_prompt}{seed_suffix}",
        f"{style_prefix}, {script.topic} theme, serene atmosphere, no people{seed_suffix}",
        f"{style_prefix}, abstract mood representing {script.mood}, beautiful composition{seed_suffix}",
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    sig = f"{date_iso}_{script.topic[:6]}{variation_seed[:4]}".replace(" ", "_")
    output_path = output_dir / f"{sig}_bg.png"

    for attempt, prompt in enumerate(prompts):
        try:
            result = client.models.generate_images(
                model=image_model,
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="9:16",
                    person_generation="dont_allow",
                ),
            )
            images = getattr(result, "generated_images", None) or []
            if not images:
                raise ValueError("빈 결과")
            image_bytes = images[0].image.image_bytes
            output_path.write_bytes(image_bytes)
            print(f"[image] 배경 생성 완료 (시도 {attempt + 1}): {output_path.name} / 주제: {script.topic} / 스타일: {script.visual_style}")
            return output_path
        except Exception as exc:
            print(f"[image] 시도 {attempt + 1} 실패: {exc}")

    raise RuntimeError(f"배경 이미지 생성 실패 (3회 시도): {script.topic}")
