from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

LINE_DURATION = 9.5
LINE_GAP = 0.5
LEAD_PADDING = 1.0
TAIL_PADDING = 2.5
MIN_TOTAL_DURATION = 15.0


@dataclass
class EssayScript:
    topic: str
    lines: List[str]
    author_line: str
    source_line: str
    is_original: bool
    visual_style: str
    image_prompt_en: str
    bgm_prompt_en: str
    bgm_mood: str
    mood: str
    title: str
    description: str
    tags: List[str] = field(default_factory=list)
    total_duration: float = 0.0

    def __post_init__(self) -> None:
        if self.total_duration == 0.0:
            n = len(self.lines)
            self.total_duration = round(
                LEAD_PADDING + n * LINE_DURATION + (n - 1) * LINE_GAP + TAIL_PADDING,
                2,
            )
        if self.total_duration < MIN_TOTAL_DURATION:
            self.total_duration = MIN_TOTAL_DURATION
