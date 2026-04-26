from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


DEFAULT_STATE: Dict[str, Any] = {
    "recent_topics": [],
    "recent_visual_styles": [],
    "recent_music_signatures": [],
    "recent_dates": [],
}


def load_state(state_file: Path) -> Dict[str, Any]:
    if not state_file.exists():
        return DEFAULT_STATE.copy()
    data = json.loads(state_file.read_text(encoding="utf-8"))
    merged = DEFAULT_STATE.copy()
    merged.update(data)
    return merged


def save_state(state_file: Path, state: Dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
