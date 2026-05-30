import base64
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib import request

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont


ROOT = Path.cwd()
HISTORY = Path(__file__).with_name("topic-history.json")
OUT = ROOT / "output" / datetime.now().strftime("%Y%m%d")
WIDTH, HEIGHT, FPS = 1920, 1080, 30

TOPICS = [
    {
        "id": "study-score-plateau",
        "topic": "교육: 공부를 오래 해도 성적이 안 오르는 이유",
        "title": "공부를 오래 해도 성적이 안 오르는 이유",
        "description": "공부 시간이 늘었는데 성적이 오르지 않는다면, 문제는 의지보다 공부 방식일 수 있습니다.\n\n오답 분석, 간격 복습, 작은 테스트가 성적을 바꾸는 이유를 설명합니다.\n\n#공부법 #성적향상 #교육 #복습법 #학습전략",
        "tags": ["공부법", "성적향상", "교육", "복습법", "학습전략", "시험공부"],
        "subject": "Korean student studying late at a desk, tired but focused, realistic documentary style",
        "problem": "공부 시간은 길지만 틀린 문제를 고치는 과정이 부족함",
        "solution": "오답 분석, 간격 복습, 작은 테스트로 피드백 루프를 만드는 것",
    },
    {
        "id": "meeting-no-decision",
        "topic": "조직문화: 회의는 많은데 왜 결정은 안 날까?",
        "title": "회의는 많은데 왜 결정은 안 날까?",
        "description": "회의가 많아도 결정이 나지 않는 조직에는 공통점이 있습니다.\n\n목적, 결정권자, 다음 행동이 없으면 회의는 일하는 척하는 시간이 됩니다.\n\n#조직문화 #회의문화 #업무효율 #리더십 #생산성",
        "tags": ["조직문화", "회의문화", "업무효율", "리더십", "생산성", "직장생활"],
        "subject": "Korean office meeting room, many documents, people unable to decide, realistic documentary style",
        "problem": "회의 목적, 결정권자, 다음 행동이 불명확함",
        "solution": "회의 전 결정 질문을 정하고 끝에는 담당자와 마감일을 남기는 것",
    },
    {
        "id": "online-review-trust",
        "topic": "소비자이슈: 온라인 리뷰를 어디까지 믿어야 할까?",
        "title": "온라인 리뷰를 어디까지 믿어야 할까?",
        "description": "리뷰가 많다고 항상 믿을 수 있는 것은 아닙니다.\n\n좋은 리뷰와 위험한 리뷰를 구분하려면 별점보다 패턴과 구체성을 봐야 합니다.\n\n#온라인리뷰 #소비자이슈 #쇼핑팁 #리뷰분석 #플랫폼",
        "tags": ["온라인리뷰", "소비자이슈", "쇼핑팁", "리뷰분석", "플랫폼"],
        "subject": "Korean consumer reviewing online shopping ratings on a laptop, realistic documentary style",
        "problem": "별점만 보고 구매하면 광고성 리뷰와 반복 패턴을 놓칠 수 있음",
        "solution": "구체적인 사용 후기, 반복 표현, 낮은 별점의 이유를 함께 보는 것",
    },
    {
        "id": "sleep-quality",
        "topic": "건강생활: 오래 자도 피곤한 이유",
        "title": "오래 자도 피곤한 이유",
        "description": "수면 시간은 충분한데 계속 피곤하다면, 문제는 잠의 양이 아니라 질일 수 있습니다.\n\n수면의 질을 떨어뜨리는 습관과 회복감을 높이는 기본 원칙을 설명합니다.\n\n#수면 #건강생활 #피로 #생활습관 #수면의질",
        "tags": ["수면", "건강생활", "피로", "생활습관", "수면의질"],
        "subject": "Korean office worker waking up tired in the morning, realistic documentary style",
        "problem": "불규칙한 수면 시간, 늦은 화면 사용, 낮은 수면의 질",
        "solution": "일정한 기상 시간, 빛 노출 조절, 잠들기 전 루틴을 만드는 것",
    },
]

LAYOUT_TITLES = [
    "오늘의 질문",
    "겉으로 보이는 문제",
    "실제 원인",
    "첫 번째 원인",
    "두 번째 원인",
    "세 번째 원인",
    "놓치기 쉬운 지점",
    "문제가 커지는 순간",
    "위험도를 나누는 기준",
    "해결의 순서",
    "좋은 방식의 공통점",
    "간단한 예시",
    "실행은 연결입니다",
    "오늘 바로 할 일",
    "작은 실험",
    "마지막 점검",
    "결론",
]


def load_history():
    if not HISTORY.exists():
        return []
    return json.loads(HISTORY.read_text(encoding="utf-8"))


def save_history(history):
    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def pick_topic(history):
    used = {x.get("topic") for x in history}
    for topic in TOPICS:
        if topic["topic"] not in used:
            return topic
    raise SystemExit("No unused topics remain. Add more topics to TOPICS.")


def build_scenes(topic):
    narrations = [
        f"{topic['title']}라는 질문은 많은 사람이 겪지만 쉽게 설명하지 못하는 문제입니다. 오늘은 이 문제를 결과가 아니라 구조로 나누어 보겠습니다.",
        f"겉으로 보이는 현상만 보면 원인을 놓치기 쉽습니다. 핵심은 {topic['problem']}이라는 구조를 보는 것입니다.",
        "한 번의 우연보다 중요한 것은 반복되는 패턴입니다. 같은 문제가 반복된다면 개인의 의지보다 방식과 환경을 먼저 봐야 합니다.",
        "첫 번째 원인은 기준이 흐린 상태입니다. 무엇을 확인해야 하는지 분명하지 않으면 사람은 익숙한 방식대로 움직입니다.",
        "두 번째 원인은 피드백이 늦다는 점입니다. 잘못된 결과를 바로 확인하지 못하면 같은 행동을 계속 반복하게 됩니다.",
        "세 번째 원인은 기록이 부족하다는 점입니다. 무엇을 했고 무엇이 달라졌는지 남기지 않으면 개선은 감각에만 의존합니다.",
        "사람들이 자주 놓치는 지점은 작은 차이입니다. 작은 생략과 미루기가 쌓이면 나중에는 큰 차이를 만듭니다.",
        "상황이 커지는 순간은 문제를 알고도 넘길 때입니다. 지금은 괜찮겠지라고 생각하는 순간 해결 신호가 뒤로 밀립니다.",
        "위험도를 보려면 자주 일어나는지와 한 번 일어났을 때 영향이 큰지를 함께 봐야 합니다.",
        f"해결의 순서는 단순합니다. 문제를 작게 나누고, 반복 원인을 찾고, 마지막으로 {topic['solution']}을 실행해야 합니다.",
        "좋은 방식은 말로 끝나지 않습니다. 진행 상황이 기록되고 결과가 비교되고 다음 행동이 정해져야 실제 변화가 생깁니다.",
        f"예를 들어 {topic['subject']} 상황을 떠올려보세요. 보이는 문제와 실제 원인은 다를 수 있습니다.",
        "실행은 혼자 끝나는 일이 아닙니다. 확인한 내용이 다음 행동으로 이어지고 그 행동이 다시 결과 확인으로 연결되어야 합니다.",
        "오늘 바로 할 일은 문제를 한 문장으로 적는 것입니다. 막연한 불편함을 구체적인 문장으로 바꾸면 해결 가능성이 올라갑니다.",
        "두 번째는 작은 실험입니다. 한 번에 모든 것을 바꾸려 하지 말고 가장 영향이 큰 행동 하나를 바꿔 결과를 확인해야 합니다.",
        "마지막 점검은 세 가지입니다. 원인이 구체적인가, 행동이 작게 정해졌는가, 결과를 다시 확인할 시간이 있는가입니다.",
        f"결론은 분명합니다. {topic['solution']}이 쌓일 때 문제는 막연한 불안이 아니라 관리 가능한 과제가 됩니다.",
    ]
    scenes = []
    for index, narration in enumerate(narrations):
        title = LAYOUT_TITLES[index]
        scenes.append({
            "title": title,
            "caption": narration.split(".")[0].strip() + ".",
            "narration": narration,
            "visual": f"{topic['subject']}. Scene focus: {title}. No text, no logos, no watermark.",
            "provider": "openai" if index % 2 == 0 else "gemini",
        })
    return scenes


def font(size):
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size, index=0)
    return ImageFont.load_default()


def generate_openai(prompt, path):
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    result = client.images.generate(
        model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
        prompt=prompt,
        size=os.getenv("OPENAI_IMAGE_SIZE", "1536x1024"),
        quality=os.getenv("OPENAI_IMAGE_QUALITY", "medium"),
        n=1,
    )
    path.write_bytes(base64.b64decode(result.data[0].b64_json))


def generate_gemini(prompt, path):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ["GOOGLE_API_KEY"])
    response = client.models.generate_content(
        model=os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image"),
        contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
    )
    for part in response.candidates[0].content.parts:
        if getattr(part, "inline_data", None):
            path.write_bytes(part.inline_data.data)
            return
    raise RuntimeError("Gemini did not return image data")


def fit_background(path):
    img = Image.open(path).convert("RGB")
    target = WIDTH / HEIGHT
    ratio = img.width / img.height
    if ratio > target:
        new_w = int(img.height * target)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / target)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))
    return img.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


def draw_wrapped(draw, text, xy, fnt, max_width, fill, spacing=12):
    x, y = xy
    lines, line = [], ""
    for ch in text:
        trial = line + ch
        box = draw.textbbox((0, 0), trial, font=fnt)
        if box[2] - box[0] <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = ch
    if line:
        lines.append(line)
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        box = draw.textbbox((0, 0), line, font=fnt)
        y += box[3] - box[1] + spacing


def render_scene_image(scene, index, total, raw_dir, frame_dir):
    raw = raw_dir / f"scene-{index + 1:02}-{scene['provider']}.png"
    frame = frame_dir / f"scene-{index + 1:02}.jpg"
    prompt = (
        "Realistic cinematic Korean YouTube documentary still, no text, no logos, no watermark, 16:9. "
        "Leave clean darker space on the left for title overlay. "
        f"{scene['visual']} Narration context: {scene['narration']}"
    )
    if not raw.exists():
        if scene["provider"] == "openai":
            generate_openai(prompt, raw)
        else:
            generate_gemini(prompt, raw)
    img = fit_background(raw).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((0, 0, 930, HEIGHT), fill=(5, 8, 14, 188))
    draw.rounded_rectangle((72, 70, 338, 132), radius=28, fill=(255, 205, 77, 255))
    draw.text((102, 88), f"SCENE {index + 1:02}", font=font(30), fill=(8, 10, 14, 255))
    draw_wrapped(draw, scene["title"], (72, 210), font(70), 760, (255, 255, 255, 255), 16)
    draw_wrapped(draw, scene["caption"], (72, 420), font(39), 760, (230, 236, 246, 255), 13)
    draw.line((72, 994, 1848, 994), fill=(255, 255, 255, 70), width=6)
    draw.line((72, 994, 72 + int(1776 * ((index + 1) / total)), 994), fill=(255, 205, 77, 255), width=8)
    Image.alpha_composite(img, overlay).convert("RGB").save(frame, quality=94)
    return frame


def elevenlabs_tts(text, path):
    payload = json.dumps({
        "text": text,
        "model_id": os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
        "voice_settings": {
            "stability": float(os.getenv("ELEVENLABS_STABILITY", "0.70")),
            "similarity_boost": float(os.getenv("ELEVENLABS_SIMILARITY", "0.84")),
            "style": float(os.getenv("ELEVENLABS_STYLE", "0.0")),
            "use_speaker_boost": os.getenv("ELEVENLABS_SPEAKER_BOOST", "true").lower() != "false",
            "speed": float(os.getenv("ELEVENLABS_SPEED", "0.94")),
        },
    }).encode("utf-8")
    req = request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{os.environ['ELEVENLABS_VOICE_ID']}",
        data=payload,
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=180) as response:
        path.write_bytes(response.read())


def duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def srt_time(seconds):
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def render_video(topic, scenes):
    OUT.mkdir(parents=True, exist_ok=True)
    raw_dir, frame_dir = OUT / "raw", OUT / "frames"
    raw_dir.mkdir(exist_ok=True)
    frame_dir.mkdir(exist_ok=True)

    narration_text = "\n\n".join(scene["narration"] for scene in scenes)
    raw_audio = OUT / "narration.mp3"
    wav_audio = OUT / "narration.wav"
    elevenlabs_tts(narration_text, raw_audio)
    subprocess.run(["ffmpeg", "-y", "-i", str(raw_audio), "-ar", "48000", "-ac", "2", str(wav_audio)], check=True)
    total = duration(wav_audio)
    weights = [len(scene["narration"]) for scene in scenes]
    scene_durations = [total * weight / sum(weights) for weight in weights]

    for idx, scene in enumerate(scenes):
        render_scene_image(scene, idx, len(scenes), raw_dir, frame_dir)

    concat = OUT / "concat.txt"
    lines = []
    for idx, dur in enumerate(scene_durations):
        lines += [f"file 'frames/scene-{idx + 1:02}.jpg'", f"duration {dur:.3f}"]
    lines.append(f"file 'frames/scene-{len(scenes):02}.jpg'")
    concat.write_text("\n".join(lines), encoding="utf-8")

    srt = OUT / "subtitles.srt"
    now = 0.0
    blocks = []
    for idx, (scene, dur) in enumerate(zip(scenes, scene_durations), 1):
        blocks.append(f"{idx}\n{srt_time(now)} --> {srt_time(now + dur)}\n{scene['caption']}\n")
        now += dur
    srt.write_text("\n".join(blocks), encoding="utf-8")

    silent = OUT / "silent.mp4"
    bgm = OUT / "bgm.wav"
    mixed = OUT / "mixed.m4a"
    video = OUT / "final.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-vf", f"scale={WIDTH}:{HEIGHT},format=yuv420p", "-r", str(FPS), "-c:v", "libx264", "-crf", "19", str(silent)], check=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=82:sample_rate=48000:duration={total + 1}", "-filter_complex", "volume=0.010", str(bgm)], check=True)
    subprocess.run(["ffmpeg", "-y", "-i", str(wav_audio), "-i", str(bgm), "-filter_complex", "[0:a]volume=1.0[a0];[1:a]volume=0.20[a1];[a0][a1]amix=inputs=2:duration=first", "-c:a", "aac", "-b:a", "192k", str(mixed)], check=True)
    subprocess.run(["ffmpeg", "-y", "-i", str(silent), "-i", str(mixed), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-shortest", str(video)], check=True)
    return video, srt


def youtube_service():
    creds = Credentials.from_authorized_user_file("token.json", ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"])
    return build("youtube", "v3", credentials=creds)


def upload(topic, video, srt):
    service = youtube_service()
    body = {
        "snippet": {
            "title": topic["title"],
            "description": topic["description"],
            "tags": topic["tags"],
            "categoryId": "27",
            "defaultLanguage": "ko",
            "defaultAudioLanguage": "ko",
        },
        "status": {"privacyStatus": os.getenv("YOUTUBE_PRIVACY", "private"), "selfDeclaredMadeForKids": False},
    }
    req = service.videos().insert(part="snippet,status", body=body, media_body=MediaFileUpload(str(video), chunksize=-1, resumable=True))
    response = None
    while response is None:
        _, response = req.next_chunk()
    video_id = response["id"]
    service.captions().insert(
        part="snippet",
        body={"snippet": {"videoId": video_id, "language": "ko", "name": "Korean", "isDraft": False}},
        media_body=MediaFileUpload(str(srt), mimetype="application/x-subrip"),
    ).execute()
    print(f"Uploaded: https://www.youtube.com/watch?v={video_id}")


def main():
    history = load_history()
    topic = pick_topic(history)
    scenes = build_scenes(topic)
    video, srt = render_video(topic, scenes)
    if not 180 <= duration(video) <= 360:
        raise RuntimeError("Generated video duration is outside 3-6 minutes")
    upload(topic, video, srt)
    history.append({"topic": topic["topic"], "title": topic["title"], "created_at": datetime.now().isoformat(timespec="seconds"), "automated": True})
    save_history(history)


if __name__ == "__main__":
    main()
