"""GitHub Actions 검증: 자동 생성 쇼츠 배경이 정확히 9:16으로 렌더되는지 확인.

API 키나 YouTube 업로드 없이, 실제 프로덕션 코드 경로
(``_normalize_to_9_16`` → ``render_short``)를 그대로 구동해 출력 영상이
1080x1920 / DAR 9:16 인지 ffprobe로 검증한다. 조건을 만족하지 못하면
비정상 종료(exit 1)하여 워크플로가 실패하도록 한다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OUT = REPO / "output" / "verify"
OUT.mkdir(parents=True, exist_ok=True)
report: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    report.append(msg)


# ── 1) 비-9:16 AI 배경 모사 (gpt-image-1 은 1024x1536 = 2:3 을 반환) ──
src = OUT / "ai_background_2x3.png"
img = Image.new("RGB", (1024, 1536), (38, 54, 82))
draw = ImageDraw.Draw(img)
draw.rectangle([0, 0, 64, 1536], fill=(220, 48, 48))       # 좌측 가장자리(크롭되어야 함)
draw.rectangle([960, 0, 1024, 1536], fill=(220, 48, 48))   # 우측 가장자리(크롭되어야 함)
draw.ellipse([362, 668, 662, 868], fill=(235, 220, 120))   # 중앙 주제(보존되어야 함)
img.save(src)
w0, h0 = Image.open(src).size
log(f"[1] AI 배경 원본(gpt-image-1 모사): {w0}x{h0}  ratio={w0 / h0:.4f}  (2:3=0.6667)")

# ── 2) 프로덕션 정규화 적용 ──
from shorts_automation.ai_generation import TARGET_RESOLUTION, _normalize_to_9_16  # noqa: E402

_normalize_to_9_16(src)
w1, h1 = Image.open(src).size
log(f"[2] _normalize_to_9_16 적용 후: {w1}x{h1}  ratio={w1 / h1:.4f}  (목표={TARGET_RESOLUTION})")
assert (w1, h1) == (1080, 1920), f"정규화 결과가 9:16이 아님: {w1}x{h1}"

# ── 3) 실제 렌더 파이프라인 구동 (render_short) ──
from shorts_automation.render import render_short  # noqa: E402
from shorts_automation.script_builder import QuoteEntry, VideoScript  # noqa: E402

font = Path(os.environ["FONT_FILE"])
quote = QuoteEntry(
    author="검증", source="CI", quote="9:16 비율 검증", interpretation="-",
    mood="city", visual_style="photoreal", bgm_mood="meditative",
)
script = VideoScript(
    quote=quote, title="9:16 검증", description="-", tags=["verify"],
    lines=["9:16 비율 자동 검증"], author_line="검증", source_line="CI",
    visual_prompt="", image_prompt_en="", bgm_prompt_en="",
    visual_style="photoreal", total_duration=3.0,
)
result = render_short(
    script=script,
    background_dir=REPO / "content" / "backgrounds",
    output_dir=OUT,
    font_file=font,
    shorts_hashtags="#verify",
    background_override=src,
    bgm_override=None,
)
video = result.video_path
log(f"[3] 렌더 완료: {video.relative_to(REPO)}")


# ── 4) ffprobe 로 출력 영상 비율 검증 ──
def probe(path: Path) -> dict[str, str]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe 를 찾을 수 없습니다.")
    out = subprocess.run(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height,sample_aspect_ratio,display_aspect_ratio",
            "-of", "default=noprint_wrappers=1", str(path),
        ],
        capture_output=True, text=True, check=True,
    ).stdout
    info: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
    return info


info = probe(video)
log(
    f"[4] ffprobe 결과: width={info.get('width')} height={info.get('height')} "
    f"SAR={info.get('sample_aspect_ratio')} DAR={info.get('display_aspect_ratio')}"
)

# ── 5) 프레임 추출(육안 확인용 아티팩트) ──
from shorts_automation.ffmpeg_utils import resolve_ffmpeg  # noqa: E402

frame = OUT / "output_frame.png"
subprocess.run(
    [resolve_ffmpeg(), "-y", "-i", str(video), "-ss", "0.5", "-frames:v", "1", str(frame)],
    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
log(f"[5] 출력 프레임 추출: {frame.relative_to(REPO)}")

# ── 검증 단언 ──
errors: list[str] = []
if info.get("width") != "1080":
    errors.append(f"width={info.get('width')} (기대값 1080)")
if info.get("height") != "1920":
    errors.append(f"height={info.get('height')} (기대값 1920)")
if info.get("display_aspect_ratio") != "9:16":
    errors.append(f"DAR={info.get('display_aspect_ratio')} (기대값 9:16)")

(OUT / "REPORT.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

if errors:
    log("[X] 검증 실패: " + "; ".join(errors))
    sys.exit(1)
log("[OK] 검증 통과: 출력 영상이 1080x1920 / DAR 9:16 입니다.")
