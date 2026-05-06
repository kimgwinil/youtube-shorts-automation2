from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import subprocess
from typing import List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from .ffmpeg_utils import resolve_ffmpeg
from .narration import NarrationResult
from .script_builder import EssayScript, LINE_DURATION, LINE_GAP, LEAD_PADDING


@dataclass
class RenderResult:
    video_path: Path
    metadata_path: Path


def render_short(
    script: EssayScript,
    output_dir: Path,
    font_file: Path,
    shorts_hashtags: str,
    background_path: Path,
    bgm_path: Path | None = None,
    narration: NarrationResult | None = None,
) -> RenderResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    if narration is not None and narration.lines:
        last = narration.lines[-1]
        needed = last.start + last.duration + 2.5
        if needed > script.total_duration:
            script.total_duration = round(needed, 2)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"{timestamp}_{script.topic}"
    video_path = output_dir / f"{stem}.mp4"
    metadata_path = output_dir / f"{stem}.json"

    line_overlays = [
        output_dir / f"{stem}_line_{i + 1}.png"
        for i in range(len(script.lines))
    ]
    header_overlay = output_dir / f"{stem}_header.png"

    for overlay_path, line in zip(line_overlays, script.lines):
        _render_line_overlay(
            text=line,
            font_file=font_file,
            output_path=overlay_path,
        )

    _render_header_overlay(
        topic=script.topic,
        author_line=script.author_line,
        source_line=script.source_line,
        font_file=font_file,
        output_path=header_overlay,
    )

    title = (
        script.title
        if "#shorts" in script.title.lower()
        else f"{script.title} #Shorts"
    )
    description_hashtags = (
        shorts_hashtags
        if "#shorts" in shorts_hashtags.lower()
        else f"#Shorts {shorts_hashtags}"
    )

    metadata_path.write_text(
        json.dumps(
            {
                "title": title[:100],
                "description": f"{script.description}\n\n{description_hashtags}",
                "tags": script.tags,
                "topic": script.topic,
                "lines": list(script.lines),
                "is_original": script.is_original,
                "author": script.author_line,
                "source": script.source_line,
                "mood": script.mood,
                "visual_style": script.visual_style,
                "bgm_mood": script.bgm_mood,
                "image_prompt_en": script.image_prompt_en,
                "bgm_prompt_en": script.bgm_prompt_en,
                "background": str(background_path),
                "bgm": str(bgm_path) if bgm_path else None,
                "narration": [str(p) for p in narration.line_audio_paths] if narration else None,
                "duration_seconds": script.total_duration,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    cmd = _build_render_cmd(
        background=background_path,
        bgm=bgm_path,
        line_overlays=line_overlays,
        header_overlay=header_overlay,
        output=video_path,
        duration=script.total_duration,
        narration=narration,
    )
    subprocess.run(cmd, check=True)
    return RenderResult(video_path=video_path, metadata_path=metadata_path)


def _build_render_cmd(
    background: Path,
    bgm: Path | None,
    line_overlays: Sequence[Path],
    header_overlay: Path,
    output: Path,
    duration: float,
    narration: NarrationResult | None = None,
) -> List[str]:
    cmd = [resolve_ffmpeg(), "-y"]
    suffix = background.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png"}:
        cmd.extend(["-loop", "1", "-i", str(background)])
    else:
        cmd.extend(["-stream_loop", "-1", "-i", str(background)])

    for overlay_path in line_overlays:
        cmd.extend(["-i", str(overlay_path)])
    cmd.extend(["-i", str(header_overlay)])

    bgm_input_index: int | None = None
    if bgm:
        bgm_input_index = 1 + len(line_overlays) + 1
        cmd.extend(["-stream_loop", "-1", "-i", str(bgm)])

    narration_input_indices: List[int] = []
    if narration:
        next_idx = 1 + len(line_overlays) + 1 + (1 if bgm else 0)
        for path in narration.line_audio_paths:
            cmd.extend(["-i", str(path)])
            narration_input_indices.append(next_idx)
            next_idx += 1

    filter_complex, video_map, audio_map = _filter_graph(
        num_lines=len(line_overlays),
        bgm_index=bgm_input_index,
        narration_indices=narration_input_indices,
        narration_starts=list(narration.line_start_times) if narration else [],
        duration=duration,
    )
    cmd.extend(["-t", f"{duration:.2f}", "-filter_complex", filter_complex, "-map", video_map])
    if audio_map:
        cmd.extend(["-map", audio_map, "-c:a", "aac", "-b:a", "192k", "-shortest"])
    else:
        cmd.append("-an")

    cmd.extend(["-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)])
    return cmd


def _filter_graph(
    num_lines: int,
    bgm_index: int | None,
    narration_indices: Sequence[int],
    narration_starts: Sequence[float],
    duration: float,
) -> Tuple[str, str, str | None]:
    timings = _line_timings(num_lines)
    parts = ["[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[v0]"]
    current = "[v0]"

    for index, (start, end) in enumerate(timings, start=1):
        next_label = f"[v{index}]"
        parts.append(
            f"{current}[{index}:v]overlay=0:0:enable='between(t,{start:.2f},{end:.2f})'{next_label}"
        )
        current = next_label

    header_index = num_lines + 1
    final_label = f"[v{header_index}]"
    parts.append(f"{current}[{header_index}:v]overlay=0:0{final_label}")

    audio_streams: List[str] = []
    has_narration = bool(narration_indices)
    bgm_volume = 0.07 if has_narration else 0.32

    if bgm_index is not None:
        bgm_chain = (
            f"[{bgm_index}:a]highpass=f=420,lowpass=f=5200,"
            "equalizer=f=120:t=q:w=1.5:g=-16,equalizer=f=200:t=q:w=2:g=-12,"
        )
        if has_narration:
            bgm_chain += "equalizer=f=2400:t=q:w=2.0:g=-6,"
            bgm_chain += (
                f"volume={bgm_volume:.3f},"
                f"afade=t=in:st=0:d=1.5,afade=t=out:st={max(duration - 2.0, 0):.2f}:d=2,"
                "alimiter=limit=0.85[abgm]"
            )
        else:
            bgm_chain += (
                f"volume={bgm_volume:.2f},"
                f"afade=t=in:st=0:d=1.5,afade=t=out:st={max(duration - 2.0, 0):.2f}:d=2,"
                "dynaudnorm=f=500:g=3,alimiter=limit=0.85[abgm]"
            )
        parts.append(bgm_chain)
        audio_streams.append("[abgm]")

    for slot, (input_idx, start) in enumerate(zip(narration_indices, narration_starts)):
        delay_ms = max(int(start * 1000), 0)
        label = f"[anar{slot}]"
        parts.append(
            f"[{input_idx}:a]aresample=48000,"
            f"adelay={delay_ms}|{delay_ms},"
            "volume=1.85,"
            "highpass=f=90,lowpass=f=11000,"
            "equalizer=f=2800:t=q:w=1.6:g=2.5,"
            "dynaudnorm=f=400:g=5"
            f"{label}"
        )
        audio_streams.append(label)

    audio_map = None
    if audio_streams:
        if len(audio_streams) == 1:
            parts.append(f"{audio_streams[0]}alimiter=limit=0.95[aout]")
        else:
            mix_inputs = "".join(audio_streams)
            parts.append(
                f"{mix_inputs}amix=inputs={len(audio_streams)}:normalize=0:dropout_transition=0,"
                "alimiter=limit=0.95[aout]"
            )
        audio_map = "[aout]"

    return ";".join(parts), final_label, audio_map


def _line_timings(num_lines: int) -> List[Tuple[float, float]]:
    timings: List[Tuple[float, float]] = []
    cursor = LEAD_PADDING
    for _ in range(num_lines):
        timings.append((cursor, cursor + LINE_DURATION))
        cursor += LINE_DURATION + LINE_GAP
    return timings


def _render_line_overlay(text: str, font_file: Path, output_path: Path) -> None:
    width, height = 1080, 1920
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_file), 58)
    max_width = width - 160

    wrapped = _wrap_text(draw, text, font, max_width)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=20, align="center", stroke_width=2)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (width - text_w) / 2
    y = 1300

    pad_x, pad_y = 44, 32
    draw.rounded_rectangle(
        [x - pad_x, y - pad_y, x + text_w + pad_x, y + text_h + pad_y],
        radius=30,
        fill=(15, 20, 30, 165),
    )
    draw.multiline_text(
        (x, y),
        wrapped,
        font=font,
        fill=(255, 252, 240, 255),
        spacing=20,
        align="center",
        stroke_width=2,
        stroke_fill=(15, 20, 30, 255),
    )
    image.save(output_path)


def _render_header_overlay(
    topic: str,
    author_line: str,
    source_line: str,
    font_file: Path,
    output_path: Path,
) -> None:
    width, height = 1080, 1920
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    topic_font = ImageFont.truetype(str(font_file), 40)
    attr_font = ImageFont.truetype(str(font_file), 28)

    box = [60, 72, 520, 240]
    draw.rounded_rectangle(box, radius=28, fill=(240, 235, 220, 215))
    draw.text((100, 95), f"✦ {topic}", font=topic_font, fill=(40, 35, 25, 255))
    draw.text((102, 150), author_line, font=attr_font, fill=(70, 65, 55, 255))
    draw.text((102, 190), source_line, font=attr_font, fill=(100, 90, 75, 255))
    image.save(output_path)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    words = text.split()
    if len(words) <= 1:
        return _wrap_chars(draw, text, font, max_width)
    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return "\n".join(lines)


def _wrap_chars(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    lines: List[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)
