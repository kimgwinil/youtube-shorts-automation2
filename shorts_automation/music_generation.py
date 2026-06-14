from __future__ import annotations

import asyncio
import base64
import contextlib
import random
import subprocess
from hashlib import sha1
from pathlib import Path

from .ffmpeg_utils import resolve_ffmpeg
from .script_builder import VideoScript


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
            ("calm solo piano instrumental, gentle upper register melody, soft felt piano, no bass, no sub-bass", 1.5),
            ("peaceful acoustic piano arpeggios, sparse warm notes, no vocals, no drums, no low drone", 1.2),
            ("serene piano background music, delicate touch, bright midrange, no rumble, no ambient bass", 0.9),
        ],
    },
    "reflective": {
        "bpm": 72,
        "temperature": 0.8,
        "guidance": 4.3,
        "mute_drums": True,
        "prompts": [
            ("soft solo piano instrumental, reflective melody, warm upper register, no bass, no sub-bass", 1.5),
            ("gentle acoustic piano, emotional sparse arpeggios, no vocals, no percussion, no drone", 1.2),
            ("introspective piano background music, clear midrange, restrained, no low rumble", 0.9),
        ],
    },
    "focused": {
        "bpm": 84,
        "temperature": 0.85,
        "guidance": 4.0,
        "mute_drums": False,
        "prompts": [
            ("bright calm solo piano instrumental, light arpeggio pulse, no bass, no drums, no sub-bass", 1.5),
            ("acoustic piano bright upper register, gentle forward motion, no vocals, no percussion", 1.2),
            ("uplifting piano background music, crisp melody, clear tone, no low rumble", 0.8),
        ],
    },
}

_INSTRUMENT_POOLS: dict[str, list[str]] = {
    "meditative": [
        "solo piano, gentle upper register melody, sparse soft touch, pianissimo, no bass notes",
        "felt piano, delicate arpeggios, warm midrange, sparse and peaceful, no low notes",
        "acoustic piano, slow broken chords, soft sustain, upper register only, no bass",
        "solo piano, light melodic fragments, clean resonance, meditative, no drone",
    ],
    "reflective": [
        "grand piano, expressive rubato melody, mid and upper register, no heavy bass pedal",
        "felt piano, reflective sparse melody, soft pedal, clear upper notes, no bass",
        "acoustic piano, emotional arpeggios, tender touch, no low drone, no percussion",
        "solo piano, warm lyrical upper register, restrained and calm, no bass notes",
    ],
    "focused": [
        "piano, clear bright articulate melody, upper register, steady gentle pulse, no bass",
        "bright felt piano, gentle repeated arpeggios, clean attack, no bass, no drums",
        "acoustic piano, light rhythmic broken chords, optimistic but quiet, no low notes",
        "solo piano, crisp upper register pattern, calm focused mood, no bass drone",
    ],
}

_LOCAL_MOOD_PROFILES: dict = {
    "meditative": {
        "freqs": [392.00, 523.25, 587.33, 659.25, 783.99],
        "tone_volume": 0.085,
        "lowpass": 6400,
        "highpass": 520,
        "echo": "aecho=0.45:0.28:180|360:0.08|0.04",
    },
    "reflective": {
        "freqs": [440.00, 523.25, 659.25, 698.46, 880.00],
        "tone_volume": 0.080,
        "lowpass": 6200,
        "highpass": 540,
        "echo": "aecho=0.42:0.26:220|440:0.08|0.04",
    },
    "focused": {
        "freqs": [493.88, 587.33, 659.25, 783.99, 987.77],
        "tone_volume": 0.075,
        "lowpass": 6800,
        "highpass": 560,
        "echo": "aecho=0.38:0.24:160|320:0.07|0.035",
    },
}


def generate_music(
    script: VideoScript,
    signature: str,
    output_dir: Path,
    music_dir: Path | None = None,
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

    library_track = _pick_library_track(music_dir=music_dir, mood=script.quote.bgm_mood, signature=signature)
    if library_track:
        varied_track = _render_library_variation(
            source_track=library_track,
            script=script,
            signature=signature,
            output_dir=output_dir,
        )
        print(f"[music] 라이브러리 음원 변주 사용: {varied_track} (source: {library_track})")
        return varied_track

    print("[music] 라이브러리 음원이 없어 로컬 합성 fallback 사용")
    return _generate_music_locally(script=script, signature=signature, output_dir=output_dir)


def _pick_library_track(music_dir: Path | None, mood: str, signature: str) -> Path | None:
    if not music_dir:
        return None

    candidates: list[Path] = []
    for candidate_dir in [music_dir / mood, music_dir / "default"]:
        if not candidate_dir.exists():
            continue
        candidates.extend(
            sorted(
                path
                for path in candidate_dir.iterdir()
                if path.is_file() and path.suffix.lower() in _AUDIO_EXTS
            )
        )
        if candidates:
            break

    if not candidates:
        return None

    seeded = random.Random(f"{mood}|{signature}")
    return seeded.choice(candidates)


def _render_library_variation(
    source_track: Path,
    script: VideoScript,
    signature: str,
    output_dir: Path,
) -> Path:
    output_path = output_dir / f"{signature}_library_mix.m4a"
    profile = _library_filter_profile(script=script, signature=signature)
    cmd = [
        resolve_ffmpeg(),
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(source_track),
        "-t",
        f"{script.total_duration:.2f}",
        "-af",
        profile,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)
    return output_path


def _library_filter_profile(script: VideoScript, signature: str) -> str:
    style_seed = int(sha1(f"{signature}|{script.visual_style}|{script.quote.quote_id}".encode("utf-8")).hexdigest()[:8], 16)
    variants = {
        "meditative": [
            "highpass=f=520,lowpass=f=7600,equalizer=f=180:t=q:w=1.4:g=-16,equalizer=f=300:t=q:w=1.1:g=-10,equalizer=f=2300:t=q:w=1.0:g=1.8,aecho=0.45:0.28:180|360:0.07|0.035,volume=0.86",
            "highpass=f=540,lowpass=f=7400,atempo=0.98,equalizer=f=200:t=q:w=1.3:g=-15,equalizer=f=2600:t=q:w=1.0:g=2.0,volume=0.84",
            "highpass=f=520,lowpass=f=7800,equalizer=f=220:t=q:w=1.4:g=-14,equalizer=f=3000:t=q:w=0.9:g=1.8,volume=0.83",
        ],
        "reflective": [
            "highpass=f=540,lowpass=f=7600,equalizer=f=180:t=q:w=1.5:g=-16,equalizer=f=280:t=q:w=1.2:g=-10,equalizer=f=2200:t=q:w=1.0:g=1.8,aecho=0.42:0.26:220|440:0.07|0.035,volume=0.86",
            "highpass=f=560,lowpass=f=7800,atempo=0.99,equalizer=f=200:t=q:w=1.3:g=-15,equalizer=f=3000:t=q:w=0.9:g=2.0,volume=0.84",
            "highpass=f=540,lowpass=f=7400,equalizer=f=220:t=q:w=1.4:g=-14,extrastereo=m=1.25,equalizer=f=2600:t=q:w=1.1:g=1.6,volume=0.83",
        ],
        "focused": [
            "highpass=f=560,lowpass=f=8200,atempo=1.01,equalizer=f=200:t=q:w=1.4:g=-15,equalizer=f=300:t=q:w=1.0:g=-9,equalizer=f=3200:t=q:w=0.8:g=2.0,volume=0.86",
            "highpass=f=580,lowpass=f=8400,atempo=1.01,equalizer=f=180:t=q:w=1.3:g=-15,extrastereo=m=1.2,equalizer=f=2800:t=q:w=1.1:g=1.8,volume=0.84",
            "highpass=f=560,lowpass=f=8000,equalizer=f=220:t=q:w=1.4:g=-14,equalizer=f=2600:t=q:w=1.0:g=1.7,volume=0.83",
        ],
    }
    base_profile = variants.get(script.quote.bgm_mood, variants["meditative"])
    profile = base_profile[style_seed % len(base_profile)]
    fade = (
        f"afade=t=in:st=0:d=1.5,"
        f"afade=t=out:st={max(script.total_duration - 2.0, 0):.2f}:d=2.0,"
        "dynaudnorm=f=500:g=3,alimiter=limit=0.84"
    )
    return f"{profile},{fade}"


async def _generate_music_with_gemini(
    script: VideoScript,
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
    profile = _GEMINI_MOOD_PROFILES.get(script.quote.bgm_mood, _GEMINI_MOOD_PROFILES["meditative"])
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


def _build_gemini_prompts(script: VideoScript, base_prompts: list[tuple[str, float]], signature: str = "") -> list[tuple[str, float]]:
    instrument = _pick_instrument(script.quote.bgm_mood, signature)
    print(f"[music] 악기 선택: {instrument[:60]}")
    prompts = list(base_prompts)
    prompts.append((instrument, 1.15))
    prompts.append((f"{script.quote.mood} mood, {script.visual_style} visual atmosphere", 0.55))
    prompts.append((f"inspired by: {script.quote.interpretation}", 0.50))
    prompts.append((f"theme: {script.quote.context}", 0.40))
    prompts.append((script.bgm_prompt_en, 1.1))
    prompts.append((_quote_music_direction(script), 0.60))
    prompts.append(("solo calm piano only, no bass instrument, no synthesizer drone, no low frequency rumble", 1.00))
    prompts.append(("background score for short inspirational video, gentle piano arpeggios, airy and clear", 0.55))
    return prompts


def _quote_music_direction(script: VideoScript) -> str:
    text = f"{script.quote.quote} {script.quote.interpretation} {script.quote.context}".lower()
    if any(keyword in text for keyword in ["행동", "실천", "실행", "관리", "측정", "혁신", "리더십", "성과", "목표", "전략", "경영"]):
        return "piano clear melody upper register, or guitar bright fingerpicking, forward motion, disciplined, no bass"
    if any(keyword in text for keyword in ["반성", "근심", "비", "흔들", "부끄러움", "사랑", "적자의 마음", "외로움", "슬픔", "그리움"]):
        return "piano or violin, expressive lyrical melody, emotional rubato, no bass drum, no low drone"
    if any(keyword in text for keyword in ["배움", "새벽", "지혜", "여백", "마루", "정원", "대나무", "자연", "산", "바람", "하늘", "고요"]):
        return "harp gentle arpeggios or piano sparse upper notes, meditative, pure tone, no bass, no low end"
    if any(keyword in text for keyword in ["용기", "도전", "희망", "의지", "극복", "성장", "변화", "열정"]):
        return "violin bright melody, or piano uplifting arpeggios, hopeful, light bowing, no bass rumble"
    if any(keyword in text for keyword in ["시간", "인생", "삶", "죽음", "운명", "철학", "존재", "의미"]):
        return "cello upper register or piano, sparse melody, contemplative, timeless, no heavy bass"
    return "piano or guitar or violin, warm melodic upper register, light and clear, no bass, no low frequency drone"


def _transcode_pcm_to_m4a(raw_path: Path, output_path: Path, duration: float) -> None:
    cmd = [
        resolve_ffmpeg(),
        "-y",
        "-f",
        "s16le",
        "-ar",
        str(_PCM_SAMPLE_RATE),
        "-ac",
        str(_PCM_CHANNELS),
        "-i",
        str(raw_path),
        "-af",
        (
            "highpass=f=520,lowpass=f=7600,"
            "equalizer=f=100:t=q:w=1.5:g=-20,"
            "equalizer=f=160:t=q:w=1.5:g=-18,"
            "equalizer=f=280:t=q:w=2:g=-16,"
            "equalizer=f=360:t=q:w=1.8:g=-10,"
            "equalizer=f=2200:t=q:w=1.0:g=2.0,"
            "dynaudnorm=f=500:g=3,alimiter=limit=0.84,"
            f"afade=t=in:st=0:d=1.8,afade=t=out:st={max(duration - 2.0, 0):.2f}:d=2.0"
        ),
        "-t",
        f"{duration:.2f}",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)


def _generate_music_locally(script: VideoScript, signature: str, output_dir: Path) -> Path:
    output_path = output_dir / f"{signature}_local-v3_bgm.m4a"

    seed = int(sha1(signature.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    profile = _LOCAL_MOOD_PROFILES.get(script.quote.bgm_mood, _LOCAL_MOOD_PROFILES["meditative"])

    note_count = max(10, min(34, int(script.total_duration / 1.05) + 2))
    freqs = [profile["freqs"][index % len(profile["freqs"])] for index in range(note_count)]
    rng.shuffle(freqs)
    cmd = [resolve_ffmpeg(), "-y"]
    note_duration = 0.82
    step = max(script.total_duration / note_count, 0.68)
    for freq in freqs:
        f = round(freq * (1 + rng.uniform(-0.003, 0.003)), 2)
        cmd.extend(["-f", "lavfi", "-i", f"sine=frequency={f}:sample_rate=44100:duration={note_duration:.2f}"])
    tone_chains = []
    for index in range(len(freqs)):
        volume = round(profile["tone_volume"] * rng.uniform(0.82, 0.98), 3)
        delay_ms = int(index * step * 1000)
        left = round(rng.uniform(0.50, 0.88), 2)
        right = round(rng.uniform(0.50, 0.88), 2)
        tone_chains.append(
            f"[{index}:a]highpass=f={profile['highpass']},"
            f"lowpass=f={profile['lowpass']},"
            f"volume={volume},"
            "afade=t=in:st=0:d=0.015,afade=t=out:st=0.22:d=0.58,"
            f"adelay={delay_ms}|{delay_ms},"
            f"pan=stereo|c0={left}*c0|c1={right}*c0[t{index}]"
        )

    mix_inputs = "".join(f"[t{index}]" for index in range(len(freqs)))
    fc = (
        ";".join(tone_chains)
        + ";"
        + f"{mix_inputs}amix=inputs={len(freqs)}:normalize=0,"
        f"{profile['echo']},"
        "highpass=f=520,lowpass=f=7200,"
        "equalizer=f=180:t=q:w=1.2:g=-14,"
        "equalizer=f=260:t=q:w=1.0:g=-10,"
        "equalizer=f=2400:t=q:w=1.0:g=2.0,"
        "alimiter=limit=0.80,"
        "volume=1.05[aout]"
    )
    cmd.extend([
        "-filter_complex",
        fc,
        "-map",
        "[aout]",
        "-t",
        "34",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        str(output_path),
    ])
    subprocess.run(cmd, check=True)
    return output_path
