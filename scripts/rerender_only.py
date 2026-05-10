from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shorts_automation.config import load_config  # noqa: E402
from shorts_automation.ffmpeg_utils import resolve_ffmpeg  # noqa: E402
from shorts_automation.render import _build_render_cmd  # noqa: E402
from shorts_automation.narration import NarrationLine, NarrationResult  # noqa: E402
from shorts_automation.script_builder import LEAD_PADDING, LINE_DURATION, LINE_GAP  # noqa: E402


def main() -> int:
    metadata_path = Path(sys.argv[1])
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    config = load_config(PROJECT_ROOT)

    base_stem = metadata_path.stem
    line_overlays = sorted(metadata_path.parent.glob(f"{base_stem}_line_*.png"))
    header_overlay = metadata_path.parent / f"{base_stem}_header.png"
    if not line_overlays or not header_overlay.exists():
        print(f"기존 오버레이 PNG를 찾을 수 없습니다: {base_stem}_line_*.png / _header.png", file=sys.stderr)
        return 1

    narration_paths = [Path(p) for p in (metadata.get("narration") or [])]
    narration = None
    if narration_paths:
        lines = []
        cursor = LEAD_PADDING
        for p in narration_paths:
            lines.append(NarrationLine(audio_path=p, start=cursor, duration=LINE_DURATION))
            cursor += LINE_DURATION + LINE_GAP
        narration = NarrationResult(lines=lines)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_video = config.output_dir / f"{timestamp}_{metadata['topic']}.mp4"
    output_meta = config.output_dir / f"{timestamp}_{metadata['topic']}.json"

    cmd = _build_render_cmd(
        background=Path(metadata["background"]),
        bgm=Path(metadata["bgm"]) if metadata.get("bgm") else None,
        line_overlays=line_overlays,
        header_overlay=header_overlay,
        output=output_video,
        duration=float(metadata["duration_seconds"]),
        narration=narration,
    )
    subprocess.run(cmd, check=True)

    new_meta = dict(metadata)
    output_meta.write_text(json.dumps(new_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"video_path": str(output_video), "metadata_path": str(output_meta)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
