"""16:9 롱폼 클립 → 9:16 숏폼 리프레이밍 (stdlib only, ffmpeg-full 필요).

모드:
  crop  — 지정 초점(x 비율) 중심으로 세로 크롭 (기본, 화질 최상)
  blur  — 원본 전체 보존 + 위아래 블러 배경 (화면 정보가 좌우로 퍼져있을 때)

Usage:
    python helpers/reframe916.py <in.mp4> -o <out.mp4> [--mode crop|blur] [--focus 0.5]
    --focus 0.5 = 화면 중앙, 0.3 = 좌측 30% 지점 (인물이 왼쪽에 있을 때)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def probe(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    return s["width"], s["height"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--mode", choices=["crop", "blur"], default="crop")
    ap.add_argument("--focus", type=float, default=0.5,
                    help="crop 모드 초점 x 비율 0.0~1.0 (기본 0.5=중앙)")
    args = ap.parse_args()

    src = args.input.resolve()
    if not src.exists():
        sys.exit(f"input not found: {src}")
    w, h = probe(src)

    if args.mode == "crop":
        # 세로 9:16 크롭 폭 = 높이 * 9/16, 초점 중심으로 x 오프셋 (경계 클램프)
        crop_w = int(h * 9 / 16)
        if crop_w > w:
            sys.exit(f"원본이 이미 세로형에 가까움 ({w}x{h}) — blur 모드를 쓰세요")
        max_x = w - crop_w
        x = min(max(int(w * args.focus - crop_w / 2), 0), max_x)
        vf = f"crop={crop_w}:{h}:{x}:0,scale=1080:1920:flags=lanczos"
    else:
        # 배경: 확대+블러, 전경: 원본 전체를 폭 맞춤
        vf = ("split[bg][fg];"
              "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
              "crop=1080:1920,gblur=sigma=28,eq=brightness=-0.08[b];"
              "[fg]scale=1080:-2[f];[b][f]overlay=(W-w)/2:(H-h)/2")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(src),
           "-filter_complex" if args.mode == "blur" else "-vf", vf,
           "-c:v", "libx264", "-preset", "slow", "-crf", "19",
           "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
           str(args.output)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed:\n{r.stderr[-600:]}")

    ow, oh = probe(args.output)
    print(f"reframed: {args.output} ({ow}x{oh}, mode={args.mode})")


if __name__ == "__main__":
    main()
