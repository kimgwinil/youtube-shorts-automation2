from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import List

from .ffmpeg_utils import resolve_ffmpeg
from .script_builder import EssayScript, LEAD_PADDING, LINE_DURATION, LINE_GAP


SUBTITLE_LEAD = 0.15
SUBTITLE_TAIL = 0.8


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


def _text_to_ssml(text: str) -> str:
    """쉼표·마침표 등 구두점에 자연스러운 SSML break 삽입."""
    t = text.strip()
    t = re.sub(r',\s*', ',<break time="250ms"/> ', t)
    t = re.sub(r'、\s*', '、<break time="200ms"/> ', t)
    t = re.sub(r'([。.])\s*', r'\1<break time="450ms"/> ', t)
    t = re.sub(r'([!?！？])\s*', r'\1<break time="400ms"/> ', t)
    t = re.sub(r'[…]|\.{2,}', '<break time="400ms"/> ', t)
    t = re.sub(r'\s*[—–]\s*', '<break time="300ms"/> ', t)
    return f'<speak>{t.strip()}</speak>'


def generate_narration(
    script: EssayScript,
    signature: str,
    output_dir: Path,
    elevenlabs_api_key: str = "",
    elevenlabs_voice_id: str = "yIiJDIlA4V9TvoOO12TS",
    elevenlabs_model: str = "eleven_multilingual_v2",
    google_tts_credentials: str = "",
    google_tts_api_key: str = "",
    voice: str = "ko-KR-Chirp3-HD-Aoede",
    speaking_rate: float = 0.85,
    pitch: float = -1.5,
) -> NarrationResult | None:
    output_dir.mkdir(parents=True, exist_ok=True)

    text_lines = [t.strip() for t in script.lines if t.strip()]
    if not text_lines:
        return None

    # 1순위: ElevenLabs
    if elevenlabs_api_key:
        lines = _generate_elevenlabs(
            text_lines, signature, output_dir,
            elevenlabs_api_key, elevenlabs_voice_id, elevenlabs_model,
        )
        if lines is not None:
            print(f"[narration] {len(lines)}개 라인 생성 완료 (engine=ElevenLabs, voice={elevenlabs_voice_id})")
            return NarrationResult(lines=lines)
        print("[narration] ElevenLabs 실패 — Google TTS로 fallback")

    # 2순위: Google TTS
    lines = _generate_google_tts(
        text_lines, signature, output_dir,
        google_tts_credentials, google_tts_api_key, voice, speaking_rate, pitch,
    )
    if lines is not None:
        print(f"[narration] {len(lines)}개 라인 생성 완료 (engine=Google TTS, voice={voice})")
        return NarrationResult(lines=lines)

    print("[narration] 모든 TTS 엔진 실패 — 나레이션 건너뜀")
    return None


# ── ElevenLabs ────────────────────────────────────────────────────────────────

def _generate_elevenlabs(
    text_lines: List[str],
    signature: str,
    output_dir: Path,
    api_key: str,
    voice_id: str,
    model: str,
) -> List[NarrationLine] | None:
    try:
        from elevenlabs.client import ElevenLabs
    except ImportError:
        print("[narration] elevenlabs 패키지 없음: pip install elevenlabs")
        return None

    try:
        client = ElevenLabs(api_key=api_key)
        lines: List[NarrationLine] = []
        cursor = LEAD_PADDING

        for index, text in enumerate(text_lines, start=1):
            path = output_dir / f"{signature}_narration_{index}.mp3"
            ssml_text = _text_to_ssml(text)
            audio_iter = client.text_to_speech.convert(
                voice_id=voice_id,
                text=ssml_text,
                model_id=model,
                output_format="mp3_44100_128",
            )
            path.write_bytes(b"".join(audio_iter))

            duration = probe_audio_duration(path)
            if duration <= 0:
                duration = LINE_DURATION

            lines.append(NarrationLine(audio_path=path, start=cursor, duration=duration))
            cursor += LINE_DURATION + LINE_GAP

        return lines if lines else None

    except Exception as exc:
        reason = str(exc)
        if "quota" in reason.lower() or "limit" in reason.lower() or "429" in reason:
            print("[narration] ElevenLabs 크레딧/쿼터 초과 — Google TTS로 fallback")
        elif "401" in reason or "unauthorized" in reason.lower():
            print("[narration] ElevenLabs 인증 오류 — Google TTS로 fallback")
        elif "voice" in reason.lower() and ("not found" in reason.lower() or "404" in reason):
            print("[narration] ElevenLabs 보이스 ID 없음 — Google TTS로 fallback")
        else:
            print(f"[narration] ElevenLabs 오류 ({type(exc).__name__}: {exc}) — Google TTS로 fallback")
        return None


# ── Google TTS ────────────────────────────────────────────────────────────────

def _generate_google_tts(
    text_lines: List[str],
    signature: str,
    output_dir: Path,
    credentials: str,
    api_key: str,
    voice: str,
    speaking_rate: float,
    pitch: float,
) -> List[NarrationLine] | None:
    try:
        from google.cloud import texttospeech
        from google.api_core.client_options import ClientOptions
    except ImportError:
        print("[narration] google-cloud-texttospeech 패키지 없음")
        return None

    if not credentials and not api_key:
        print("[narration] Google TTS 인증 정보 없음 (GOOGLE_TTS_CREDENTIALS 또는 GOOGLE_TTS_API_KEY 필요)")
        return None

    try:
        if credentials:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(
                credentials,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            client = texttospeech.TextToSpeechClient(credentials=creds)
        else:
            client = texttospeech.TextToSpeechClient(
                client_options=ClientOptions(api_key=api_key)
            )

        lang_code = "-".join(voice.split("-")[:2])
        voice_params = texttospeech.VoiceSelectionParams(language_code=lang_code, name=voice)
        supports_pitch = "Chirp" not in voice
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=speaking_rate,
            **({"pitch": pitch} if supports_pitch else {}),
        )

        lines: List[NarrationLine] = []
        cursor = LEAD_PADDING

        for index, text in enumerate(text_lines, start=1):
            path = output_dir / f"{signature}_narration_{index}.mp3"
            ssml = _text_to_ssml(text)
            try:
                response = client.synthesize_speech(
                    input=texttospeech.SynthesisInput(ssml=ssml),
                    voice=voice_params,
                    audio_config=audio_config,
                )
            except Exception as ssml_err:
                print(f"[narration] SSML 미지원 — plain text로 재시도 (line {index}): {ssml_err}")
                response = client.synthesize_speech(
                    input=texttospeech.SynthesisInput(text=text),
                    voice=voice_params,
                    audio_config=audio_config,
                )
            path.write_bytes(response.audio_content)

            duration = probe_audio_duration(path)
            if duration <= 0:
                duration = LINE_DURATION

            lines.append(NarrationLine(audio_path=path, start=cursor, duration=duration))
            cursor += LINE_DURATION + LINE_GAP

        return lines if lines else None

    except Exception as exc:
        print(f"[narration] Google TTS 오류 ({type(exc).__name__}: {exc})")
        return None


# ── 공통 ──────────────────────────────────────────────────────────────────────

def probe_audio_duration(audio_path: Path) -> float:
    cmd = [resolve_ffmpeg(), "-i", str(audio_path), "-hide_banner", "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    for line in proc.stderr.splitlines():
        if "Duration:" in line:
            stamp = line.split("Duration:")[1].split(",")[0].strip()
            try:
                h, m, s = stamp.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
            except ValueError:
                return 0.0
    return 0.0
