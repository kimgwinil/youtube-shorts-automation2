from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import List

from .ffmpeg_utils import resolve_ffmpeg
from .script_builder import EssayScript, LEAD_PADDING, LINE_DURATION, LINE_GAP


SUBTITLE_LEAD = 0.15
SUBTITLE_TAIL = 0.5


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
    google_tts_credentials: str = "",
    google_tts_api_key: str = "",
    voice: str = "ko-KR-Chirp3-HD-Aoede",
    speaking_rate: float = 0.85,
    pitch: float = -1.5,
) -> NarrationResult | None:
    try:
        from google.cloud import texttospeech
        from google.api_core.client_options import ClientOptions
    except ImportError as exc:
        raise RuntimeError(
            "`google-cloud-texttospeech` 패키지가 필요합니다: "
            "pip install google-cloud-texttospeech"
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)

    if google_tts_credentials:
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(
            google_tts_credentials,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        client = texttospeech.TextToSpeechClient(credentials=credentials)
    elif google_tts_api_key:
        client = texttospeech.TextToSpeechClient(
            client_options=ClientOptions(api_key=google_tts_api_key)
        )
    else:
        print("[narration] TTS 인증 정보 없음 (GOOGLE_TTS_CREDENTIALS 또는 GOOGLE_TTS_API_KEY 필요) — 나레이션 건너뜀")
        return None

    lang_code = "-".join(voice.split("-")[:2])
    voice_params = texttospeech.VoiceSelectionParams(
        language_code=lang_code,
        name=voice,
    )
    supports_pitch = "Chirp" not in voice
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=speaking_rate,
        **({"pitch": pitch} if supports_pitch else {}),
    )

    lines: List[NarrationLine] = []
    cursor = LEAD_PADDING

    for index, line_text in enumerate(script.lines, start=1):
        text = line_text.strip()
        if not text:
            cursor += LINE_DURATION + LINE_GAP
            continue
        path = output_dir / f"{signature}_narration_{index}.mp3"
        synthesis_input = texttospeech.SynthesisInput(text=text)
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice_params,
            audio_config=audio_config,
        )
        path.write_bytes(response.audio_content)

        duration = probe_audio_duration(path)
        if duration <= 0:
            duration = LINE_DURATION

        lines.append(NarrationLine(audio_path=path, start=cursor, duration=duration))
        cursor += LINE_DURATION + LINE_GAP

    if not lines:
        return None

    print(f"[narration] {len(lines)}개 라인 TTS 생성 완료 (voice={voice})")
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
