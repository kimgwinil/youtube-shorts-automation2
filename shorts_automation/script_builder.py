from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import random
from typing import List

import yaml

from .state_store import load_state, save_state


@dataclass
class QuoteEntry:
    author: str
    source: str
    quote: str
    interpretation: str
    mood: str
    visual_style: str = "photoreal"
    bgm_mood: str = "meditative"
    context: str = ""

    @property
    def quote_id(self) -> str:
        raw = (
            f"{self.author}|{self.source}|{self.quote}|{self.interpretation}|"
            f"{self.mood}|{self.visual_style}|{self.bgm_mood}|{self.context}"
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass
class VideoScript:
    quote: QuoteEntry
    title: str
    description: str
    tags: List[str]
    lines: List[str]
    author_line: str
    source_line: str
    visual_prompt: str
    image_prompt_en: str
    bgm_prompt_en: str
    visual_style: str
    total_duration: float

def _load_quotes(quotes_file: Path) -> List[QuoteEntry]:
    raw = yaml.safe_load(quotes_file.read_text(encoding="utf-8")) or []
    return [QuoteEntry(**item) for item in raw]


def pick_next_quote(quotes_file: Path, state_file: Path) -> QuoteEntry:
    quotes = _load_quotes(quotes_file)
    if not quotes:
        raise RuntimeError("content/quotes.yaml 에 명언이 없습니다.")

    state = load_state(state_file)
    used_quotes = set(state.get("used_quotes", []))
    candidates = [quote for quote in quotes if quote.quote_id not in used_quotes]
    if not candidates:
        state["used_quotes"] = []
        save_state(state_file, state)
        candidates = quotes

    quote = random.choice(candidates)
    state = load_state(state_file)
    state.setdefault("used_quotes", []).append(quote.quote_id)
    save_state(state_file, state)
    return quote


def build_script(quote: QuoteEntry, visual_style_override: str | None = None) -> VideoScript:
    visual_style = visual_style_override or quote.visual_style
    quote_chunks = _split_text(quote.quote, max_len=20, target_lines=2)
    interpretation_chunks = _split_text(quote.interpretation, max_len=24, target_lines=2)
    lines = [
        _build_hook(quote),
        f"{quote.author}의 말",
        *quote_chunks,
        *interpretation_chunks,
        _build_closing(quote),
    ]

    title = f"{_author_display_name(quote.author)} | {quote_chunks[0]} #shorts"
    description = "\n".join(
        [
            f"저자: {_author_display_name(quote.author)}",
            f"출전: {quote.source}",
            f"명언: {quote.quote}",
            f"해석: {quote.interpretation}",
            f"배경 스타일: {visual_style}",
            f"배경음악 분위기: {quote.bgm_mood}",
            "",
            "#shorts #명언 #고전 #자기계발",
        ]
    )
    tags = ["shorts", "명언", "자기계발", _author_display_name(quote.author), visual_style]
    return VideoScript(
        quote=quote,
        title=title[:90],
        description=description,
        tags=tags,
        lines=lines,
        author_line=_author_display_name(quote.author),
        source_line=quote.source,
        visual_prompt=_build_visual_prompt(quote, visual_style),
        image_prompt_en=_build_visual_prompt_en(quote, visual_style),
        bgm_prompt_en=_build_bgm_prompt_en(quote),
        visual_style=visual_style,
        total_duration=max(24.0, len(lines) * 3.8),
    )


def _build_hook(quote: QuoteEntry) -> str:
    hooks = {
        "Confucius": "삶의 무게는 말보다 행동에서 드러난다",
        "Mencius": "마음이 흔들릴수록 중심을 더 깊게 붙잡아야 한다",
        "Peter Drucker": "내일은 저절로 오지 않고 오늘의 실행으로 만들어진다",
    }
    return _compact_text(hooks.get(quote.author, "오늘을 바로 세우는 문장을 천천히 읽어 본다"), limit=34)


def _build_closing(quote: QuoteEntry) -> str:
    closings = {
        "dawn": "오늘의 첫 마음을 잃지 않고 조용히 앞으로 나아간다",
        "rain": "흔들리더라도 마음의 뿌리를 지키면 다시 바로 설 수 있다",
        "city": "생각을 계획으로, 계획을 실행으로 옮길 때 미래가 바뀐다",
    }
    return _compact_text(closings.get(quote.mood, "한 문장을 오래 붙들면 오늘의 방향이 달라진다"), limit=38)


def _build_visual_prompt(quote: QuoteEntry, visual_style: str) -> str:
    subject = quote.context or quote.interpretation
    style_map = {
        "photoreal": "실사 사진처럼 정교한 빛과 질감",
        "watercolor": "은은한 번짐과 종이 결이 살아있는 수채화",
        "ink": "먹의 농담과 여백이 살아있는 수묵화",
        "calligraphy": "동양 서화풍의 붓결과 고요한 여백",
    }
    style_desc = style_map.get(visual_style, style_map["photoreal"])
    mood_desc = {
        "dawn": "새벽빛, 안개, 고요한 공기",
        "rain": "비 내리는 창가, 젖은 돌길, 차분한 분위기",
        "city": "이른 아침 도시, 창문 불빛, 정돈된 움직임",
    }.get(quote.mood, "고요하고 사색적인 장면")
    return (
        f"{style_desc}, {mood_desc}, {subject}, 인물은 작게 혹은 뒷모습으로, "
        "세로형 9:16 구도, 텍스트를 올릴 여백이 충분한 중앙 하단 구성"
    )


def _build_visual_prompt_en(quote: QuoteEntry, visual_style: str) -> str:
    style_map = {
        "photoreal": "photorealistic cinematic photography",
        "watercolor": "soft watercolor illustration with visible paper texture",
        "ink": "East Asian ink wash painting with expressive brushwork",
        "calligraphy": "East Asian ink wash painting with elegant empty space, without calligraphy, script, or glyph-like marks",
    }
    mood_desc = {
        "dawn": "dawn light, mist, calm air",
        "rain": "rainy window, wet stone path, reflective quiet mood",
        "city": "early morning city atmosphere, restrained motion, organized space",
    }.get(quote.mood, "quiet contemplative atmosphere")
    subject = quote.context or quote.interpretation
    return (
        f"{style_map.get(visual_style, style_map['photoreal'])}, "
        f"{mood_desc}, {subject}, vertical 9:16 composition, "
        "background-focused scene, no central character, clean lower center for subtitles, no text or glyph-like marks"
    )


def _build_bgm_prompt_en(quote: QuoteEntry) -> str:
    mood_map = {
        "meditative": "warm meditative ambient with gentle piano and airy resonance",
        "reflective": "reflective ambient with soft piano, restrained strings, and emotional control",
        "focused": "focused modern ambient with a clear pulse and light rhythmic motion",
    }
    return (
        f"{mood_map.get(quote.bgm_mood, 'balanced inspirational ambient')}, "
        f"inspired by {quote.interpretation}, no heavy bass, no vocals"
    )


def _split_text(text: str, max_len: int, target_lines: int) -> List[str]:
    text = " ".join(text.strip().split())
    if len(text) <= max_len:
        return [text]

    segments: List[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            segments.append(remaining)
            break

        split_at = remaining.rfind(" ", 0, max_len + 1)
        if split_at < max_len // 2:
            split_at = max_len
        segments.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    if len(segments) < target_lines:
        return segments
    return segments[:target_lines - 1] + [" ".join(segments[target_lines - 1 :])]


def _author_display_name(author: str) -> str:
    names = {
        "Confucius": "공자",
        "Mencius": "맹자",
        "Peter Drucker": "피터 드러커",
    }
    return names.get(author, author)


def _compact_text(text: str, limit: int) -> str:
    text = " ".join(text.strip().split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
