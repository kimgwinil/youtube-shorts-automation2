from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import List

from .ffmpeg_utils import resolve_ffmpeg
from .script_builder import EssayScript, LEAD_PADDING, LINE_DURATION, LINE_GAP


SUBTITLE_LEAD = 0.15
SUBTITLE_TAIL = 0.5

NARRATION_STYLE_INSTRUCTIONS = (
    "Speak the line slowly and warmly in Korean, like reading a contemplative essay aloud."
    " Use a calm, gentle, slightly low pitch with natural pauses between phrases."
    " Avoid sounding robotic or rushed; keep an introspective, mature tone."
)


@dataclass
class NarrationLine:
    audio_path: Path
    start: float
    duration: float


@dataclass
class NarrationResult:
    lines: List[NarrationLine]

    @property
    def line_audio_paths(self) -> List[Path]:
        return [line.audio_path for line in self.lines]

    @property
    def line_start_times(self) -> List[float]:
        return [line.start for line in self.lines]

    @property
    def line_durations(self) -> List[float]:
        return [line.duration for line in self.lines]


def generate_narration(
    script: EssayScript,
    signature: str,
    output_dir: Path,
    openai_api_key: str,
    voice: str = "coral",
    model: str = "gpt-4o-mini-tts",
) -> NarrationResult | None:
    if not openai_api_key:
        print("[narration] OPENAI_API_KEY 없음 - 나래이션 생략")
        return None

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("`openai` 패키지가 필요합니다.") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    client = OpenAI(api_key=openai_api_key)

    lines: List[NarrationLine] = []
    cursor = LEAD_PADDING
    supports_instructions = model.startswith("gpt-4o")

    for index, line_text in enumerate(script.lines, start=1):
        text = line_text.strip()
        if not text:
            cursor += LINE_DURATION + LINE_GAP
            continue
        path = output_dir / f"{signature}_narration_{index}.mp3"
        try:
            kwargs = dict(model=model, voice=voice, input=text, response_format="mp3")
            if supports_instructions:
                kwargs["instructions"] = NARRATION_STYLE_INSTRUCTIONS
            with client.audio.speech.with_streaming_response.create(**kwargs) as response:
                response.stream_to_file(path)
        except Exception as exc:
            print(f"[narration] 라인 {index} TTS 실패: {exc}")
            return None

        duration = probe_audio_duration(path)
        if duration <= 0:
            duration = LINE_DURATION

        lines.append(NarrationLine(audio_path=path, start=cursor, duration=duration))
        cursor += LINE_DURATION + LINE_GAP

    if not lines:
        return None

    print(f"[narration] {len(lines)}개 라인 TTS 생성 완료 (voice={voice}, model={model})")
    return NarrationResult(lines=lines)


def probe_audio_duration(audio_path: Path) -> float:
    cmd = [
        resolve_ffmpeg(),
        "-i", str(audio_path),
        "-hide_banner",
        "-f", "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    output = proc.stderr
    for line in output.splitlines():
        if "Duration:" in line:
            stamp = line.split("Duration:")[1].split(",")[0].strip()
            try:
                h, m, s = stamp.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
            except ValueError:
                return 0.0
    return 0.0
