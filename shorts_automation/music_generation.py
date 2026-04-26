from __future__ import annotations

import asyncio
import base64
import contextlib
import random
import subprocess
from hashlib import sha1
from pathlib import Path

from .ffmpeg_utils import resolve_ffmpeg
from .script_builder import EssayScript


_MUSIC_VERSION = "gemini-v1"
_PCM_SAMPLE_RATE = 48_000
_PCM_CHANNELS = 2
_PCM_SAMPLE_WIDTH = 2
_AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".aac"}

_GEMINI_MOOD_PROFILES: dict = {
    "meditative": {
        "bpm": 66,
        "temperature": 0.7,
        "guidance": 4.5,
        "mute_drums": True,
        "prompts": [
            ("classical solo instrument, piano or harp or guitar, no bass, no sub-bass, no low frequencies", 1.2),
            ("acoustic piano upper register, gentle sparse melody, or harp arpeggios, no vocals, no drums", 1.0),
            ("serene classical chamber, dawn stillness, pure tone, no bass rumble, no low drone", 0.8),
        ],
    },
    "reflective": {
        "bpm": 72,
        "temperature": 0.8,
        "guidance": 4.3,
        "mute_drums": True,
        "prompts": [
            ("classical solo or duet, piano violin or cello upper register, no bass drum, no sub-bass", 1.2),
            ("acoustic piano melody, or violin legato, or guitar fingerpicking, no vocals, no percussion", 1.0),
            ("introspective classical, warm midrange tone, no bass drone, no low rumble, restrained", 0.8),
        ],
    },
    "focused": {
        "bpm": 84,
        "temperature": 0.85,
        "guidance": 4.0,
        "mute_drums": False,
        "prompts": [
            ("classical piano or guitar, clear bright melody, light rhythmic pulse, no heavy bass", 1.2),
            ("acoustic piano bright arpeggios, or guitar clean picking, forward motion, no vocals", 1.0),
            ("uplifting classical chamber, crisp upper register, disciplined, no bass rumble", 0.7),
        ],
    },
}

_INSTRUMENT_POOLS: dict[str, list[str]] = {
    "meditative": [
        "solo piano, gentle upper register melody, sparse soft touch, pianissimo, no bass notes",
        "classical harp, delicate arpeggios, shimmering harmonics, ethereal, no low strings",
        "nylon string guitar, slow fingerpicking, warm midrange, solo, no bass strings",
        "solo violin, soft sustained melody, pianissimo bowing, serene, no accompaniment",
        "cello playing in upper register, lyrical bow strokes, warm mid-tone, no low drone",
        "piano and harp duet, gentle interplay, upper register only, peaceful, no bass",
    ],
    "reflective": [
        "grand piano, expressive rubato melody, mid and upper register, no heavy bass pedal",
        "violin, singing legato melody, heartfelt bowing, warm tone, solo, no percussion",
        "cello, lyrical mid-register melody, expressive, no low open strings, bowed gently",
        "classical guitar, fingerpicked arpeggios, warm nylon tone, melancholic, no bass strings",
        "harp, flowing arpeggios, shimmering texture, emotional, mid and upper register only",
        "piano and violin duet, tender intertwining melody, upper register, no bass drum",
    ],
    "focused": [
        "piano, clear bright articulate melody, upper register, steady gentle pulse, no bass",
        "classical guitar, clean bright fingerpicking, forward motion, positive, no bass strings",
        "violin, bright clear bowing, light staccato phrases, energetic but delicate, no bass",
        "harp, rhythmic bright arpeggios, uplifting, clear tone, mid and upper register",
        "piano and cello duet, bright mid-register melody, disciplined, clear, no low drone",
        "guitar and violin, complementary bright melody, warm, forward moving, no bass",
    ],
}

_LOCAL_MOOD_PROFILES: dict = {
    "meditative": {
        "freqs": [392.00, 523.25, 587.33, 659.25, 783.99],
        "tone_volume": 0.12,
        "noise_volume": 0.012,
        "lowpass": 2400,
        "highpass": 340,
        "noise_highpass": 900,
        "echo": "aecho=0.65:0.40:220|480:0.12|0.06",
    },
    "reflective": {
        "freqs": [440.00, 523.25, 659.25, 698.46, 880.00],
        "tone_volume": 0.11,
        "noise_volume": 0.010,
        "lowpass": 2200,
        "highpass": 380,
        "noise_highpass": 1050,
        "echo": "aecho=0.60:0.36:260|560:0.10|0.05",
    },
    "focused": {
        "freqs": [493.88, 587.33, 659.25, 783.99, 987.77],
        "tone_volume": 0.10,
        "noise_volume": 0.008,
        "lowpass": 2800,
        "highpass": 420,
        "noise_highpass": 1200,
        "echo": "aecho=0.50:0.30:150|320:0.09|0.04",
    },
}


def generate_music(
    script: EssayScript,
    signature: str,
    output_dir: Path,
    gemini_api_key: str = "",
    gemini_model: str = "models/lyria-realtime-exp",
    prefer_gemini: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if prefer_gemini and gemini_api_key:
        try:
            return asyncio.run(
                _generate_music_with_gemini(
                    script=script,
                    signature=signature,
                    output_dir=output_dir,
                    gemini_api_key=gemini_api_key,
                    gemini_model=gemini_model,
                )
            )
        except Exception as exc:
            print(f"[music] Gemini 음악 생성 실패, 로컬 fallback 사용: {exc}")

    print("[music] 로컬 합성 fallback 사용")
    return _generate_music_locally(script=script, signature=signature, output_dir=output_dir)


async def _generate_music_with_gemini(
    script: EssayScript,
    signature: str,
    output_dir: Path,
    gemini_api_key: str,
    gemini_model: str,
) -> Path:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("`google-genai` 패키지가 필요합니다.") from exc

    raw_path = output_dir / f"{signature}_{_MUSIC_VERSION}.pcm"
    output_path = output_dir / f"{signature}_{_MUSIC_VERSION}.m4a"
    profile = _GEMINI_MOOD_PROFILES.get(script.bgm_mood, _GEMINI_MOOD_PROFILES["reflective"])
    prompt_seed = _build_gemini_prompts(script, profile["prompts"], signature)
    bytes_written = 0

    client = genai.Client(api_key=gemini_api_key, http_options={"api_version": "v1alpha"})

    async def receive_audio(session, handle) -> None:
        nonlocal bytes_written
        async for message in session.receive():
            server_content = getattr(message, "server_content", None)
            chunks = getattr(server_content, "audio_chunks", None) if server_content else None
            if not chunks:
                continue
            for chunk in chunks:
                data = getattr(chunk, "data", b"")
                if isinstance(data, str):
                    data = base64.b64decode(data)
                if not data:
                    continue
                handle.write(data)
                bytes_written += len(data)

    with raw_path.open("wb") as handle:
        async with client.aio.live.music.connect(model=gemini_model) as session:
            receiver = asyncio.create_task(receive_audio(session, handle))
            try:
                await session.set_weighted_prompts(
                    prompts=[types.WeightedPrompt(text=text, weight=weight) for text, weight in prompt_seed]
                )
                await session.set_music_generation_config(
                    config=types.LiveMusicGenerationConfig(
                        bpm=profile["bpm"],
                        temperature=profile["temperature"],
                        guidance=profile["guidance"],
                        mute_bass=True,
                        mute_drums=profile["mute_drums"],
                    )
                )
                await session.play()
                await asyncio.sleep(max(script.total_duration, 24.0) + 1.8)
                with contextlib.suppress(Exception):
                    await session.stop()
                await asyncio.sleep(1.0)
            finally:
                receiver.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await receiver

    if bytes_written <= _PCM_SAMPLE_RATE * _PCM_CHANNELS * _PCM_SAMPLE_WIDTH:
        raise RuntimeError("Gemini 음악 스트림이 충분한 PCM 데이터를 반환하지 않았습니다.")

    _transcode_pcm_to_m4a(raw_path=raw_path, output_path=output_path, duration=script.total_duration)
    raw_path.unlink(missing_ok=True)
    return output_path


def _pick_instrument(bgm_mood: str, signature: str) -> str:
    pool = _INSTRUMENT_POOLS.get(bgm_mood, _INSTRUMENT_POOLS["reflective"])
    seeded = random.Random(f"{signature}|instrument-pick")
    return seeded.choice(pool)


def _build_gemini_prompts(script: EssayScript, base_prompts: list[tuple[str, float]], signature: str = "") -> list[tuple[str, float]]:
    instrument = _pick_instrument(script.bgm_mood, signature)
    print(f"[music] 악기 선택: {instrument[:60]}")
    prompts = list(base_prompts)
    prompts.append((instrument, 1.15))
    prompts.append((f"{script.mood} mood, {script.visual_style} visual atmosphere", 0.55))
    prompts.append((f"theme: {script.topic}", 0.50))
    prompts.append((script.bgm_prompt_en, 1.1))
    prompts.append((_essay_music_direction(script), 0.60))
    prompts.append(("no sub-bass, no low frequency drone, no bass rumble, clean high-mid spectrum only", 0.80))
    prompts.append(("background score for short inspirational essay video, varied melodic arrangement, airy and clear", 0.55))
    return prompts


def _essay_music_direction(script: EssayScript) -> str:
    topic = script.topic
    if topic in ("사랑", "그리움", "이별", "눈물", "외로움"):
        return "reflective texture, soft felt piano, restrained strings, emotional but controlled, no bass drone"
    if topic in ("희망", "용기", "도전", "성장", "꿈", "설렘"):
        return "uplifting ambient texture, bright melodic arpeggios, gentle piano, light strings, hopeful tone, no bass rumble"
    if topic in ("아침", "새벽", "햇살", "봄", "자연", "바람"):
        return "quiet meditative space, airy atmospheric pads, warm resonance, minimal low end, contemplative pacing"
    if topic in ("친구", "가족", "감사", "만남", "웃음"):
        return "warm ambient texture, gentle guitar or piano, bright tone, nostalgic warmth, no bass"
    if topic in ("고독", "침묵", "고요", "겨울", "비"):
        return "sparse cinematic ambient, distant reverb, sparse piano, no heavy bass, timeless stillness"
    if topic in ("지혜", "믿음", "평화", "용서", "치유"):
        return "gentle meditative tone, soft strings, warm pads, peaceful resolution, no bass rumble"
    return "balanced inspirational ambient, warm midrange clarity, light melodic contour, no heavy bass"


def _transcode_pcm_to_m4a(raw_path: Path, output_path: Path, duration: float) -> None:
    cmd = [
        resolve_ffmpeg(),
        "-y",
        "-f", "s16le",
        "-ar", str(_PCM_SAMPLE_RATE),
        "-ac", str(_PCM_CHANNELS),
        "-i", str(raw_path),
        "-af",
        (
            "highpass=f=440,lowpass=f=5400,"
            "equalizer=f=100:t=q:w=1.5:g=-20,"
            "equalizer=f=160:t=q:w=1.5:g=-18,"
            "equalizer=f=280:t=q:w=2:g=-12,"
            "dynaudnorm=f=500:g=3,alimiter=limit=0.84,"
            f"afade=t=in:st=0:d=1.8,afade=t=out:st={max(duration - 2.0, 0):.2f}:d=2.0"
        ),
        "-t", f"{duration:.2f}",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)


def _generate_music_locally(script: EssayScript, signature: str, output_dir: Path) -> Path:
    output_path = output_dir / f"{signature}_local-v3_bgm.m4a"
    seed = int(sha1(signature.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    profile = _LOCAL_MOOD_PROFILES.get(script.bgm_mood, _LOCAL_MOOD_PROFILES["reflective"])

    freqs = rng.sample(profile["freqs"], 3)
    cmd = [resolve_ffmpeg(), "-y"]
    for freq in freqs:
        f = round(freq * (1 + rng.uniform(-0.004, 0.004)), 2)
        cmd.extend(["-f", "lavfi", "-i", f"sine=frequency={f}:sample_rate=44100:duration=70"])
    cmd.extend(["-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.25:sample_rate=44100:d=70"])

    noise_index = len(freqs)
    noise_chain = (
        f"[{noise_index}:a]highpass=f={profile['noise_highpass']},"
        "lowpass=f=3200,"
        f"volume={profile['noise_volume'] * 0.7:.4f},"
        f"afade=t=in:st=0:d=3,afade=t=out:st=62:d=5,"
        "pan=stereo|c0=0.72*c0|c1=0.72*c0[n0]"
    )

    tone_chains = []
    for index in range(len(freqs)):
        volume = round(profile["tone_volume"] * rng.uniform(0.82, 0.98), 3)
        vibrato_freq = round(rng.uniform(2.2, 3.6), 2)
        vibrato_depth = round(rng.uniform(0.015, 0.028), 3)
        left = round(rng.uniform(0.50, 0.88), 2)
        right = round(rng.uniform(0.50, 0.88), 2)
        tone_chains.append(
            f"[{index}:a]highpass=f={profile['highpass']},"
            f"lowpass=f={profile['lowpass'] + 500},"
            f"volume={volume},"
            f"vibrato=f={vibrato_freq}:d={vibrato_depth},"
            "afade=t=in:st=0:d=2.5,afade=t=out:st=62:d=5,"
            f"pan=stereo|c0={left}*c0|c1={right}*c0[t{index}]"
        )

    mix_inputs = "".join(f"[t{index}]" for index in range(len(freqs))) + "[n0]"
    fc = (
        ";".join([*tone_chains, noise_chain])
        + ";"
        + f"{mix_inputs}amix=inputs={len(freqs) + 1}:normalize=0,"
        f"{profile['echo']},"
        "equalizer=f=220:t=q:w=1.2:g=-7,"
        "equalizer=f=320:t=q:w=1.0:g=-5,"
        "equalizer=f=2600:t=q:w=1.0:g=2.5,"
        "dynaudnorm=f=500:g=3,"
        "alimiter=limit=0.80,"
        "volume=1.10[aout]"
    )
    cmd.extend([
        "-filter_complex", fc,
        "-map", "[aout]",
        "-t", f"{script.total_duration:.2f}",
        "-c:a", "aac",
        "-b:a", "160k",
        str(output_path),
    ])
    subprocess.run(cmd, check=True)
    return output_path
