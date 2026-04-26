from __future__ import annotations

import os


def resolve_ffmpeg() -> str:
    explicit = os.environ.get("FFMPEG_BIN", "").strip()
    if explicit:
        return explicit
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"
