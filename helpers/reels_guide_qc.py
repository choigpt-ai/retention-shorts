"""릴스 가이드박스 세이프존 QC — 발행 전 필수 관문.

발행 전 안전지대(safe-zone) 검수: 편집 전 가이드박스를 세팅하고, 헤더(타이틀)가
박스 안에 들어왔을 때만 발행한다. 이 스크립트는 완성본 프레임 위에 가이드를
겹친 QC 이미지를 생성한다 — LLM(스킬)이 이미지를 Read로 보고 판정한다.

가이드 좌표 (1080x1920, 인스타 릴스 UI 실측):
  세이프존 = 좌80 / 상250 / 우1000(y858까지)→880(아이콘 레일) / 하1520

Usage:
    python helpers/reels_guide_qc.py <video.mp4> [-t 1 -t 30 ...] [-o out_dir]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

L, T, R1, R2, B, RAIL_Y = 80, 250, 1000, 880, 1520, 858


def overlay_guide(src: Path, out: Path) -> None:
    from PIL import Image, ImageDraw
    img = Image.open(src).convert("RGBA").resize((1080, 1920))
    ov = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    red = (255, 60, 60, 110)
    d.rectangle([0, 0, 1080, T], fill=red)
    d.rectangle([0, B, 1080, 1920], fill=red)
    d.rectangle([0, T, L, B], fill=red)
    d.rectangle([R1, T, 1080, RAIL_Y], fill=red)
    d.rectangle([R2, RAIL_Y, 1080, B], fill=red)
    d.rectangle([L, T, R1, RAIL_Y], outline=(0, 255, 120, 255), width=4)
    d.rectangle([L, RAIL_Y, R2, B], outline=(0, 255, 120, 255), width=4)
    Image.alpha_composite(img, ov).convert("RGB").save(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("-t", "--times", type=float, action="append",
                    help="검사 시점(초). 생략 시 1, 중간, 끝-2")
    ap.add_argument("-o", "--out-dir", type=Path, default=None)
    args = ap.parse_args()

    video = args.video.resolve()
    out_dir = (args.out_dir or video.parent / "guide_qc").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    times = args.times
    if not times:
        dur = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(video)],
            capture_output=True, text=True, check=True).stdout)
        times = [1.0, dur / 2, max(dur - 2, 0)]

    with tempfile.TemporaryDirectory() as tmp:
        for t in times:
            frame = Path(tmp) / f"f{t:.0f}.png"
            r = subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", str(video),
                                "-frames:v", "1", str(frame)],
                               capture_output=True, text=True)
            if r.returncode != 0 or not frame.exists():
                sys.exit(f"frame extract failed @{t}s")
            out = out_dir / f"guide_{t:.0f}s.png"
            overlay_guide(frame, out)
            print(f"saved: {out}")
    print("→ 각 이미지를 Read로 보고 판정: 헤더·얼굴·자막이 초록 박스 안인가?")


if __name__ == "__main__":
    main()
