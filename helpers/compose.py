"""숏폼 템플릿 합성기 — 16:9 컷 영상을 1080x1920 세로 숏폼으로.

블랙 캔버스 위에:
  · 영상: 소스를 4:5 근사로 크롭해 상단에 배치 (완성본 하단 번인자막 회피)
  · 헤더 배너: 라임(설정색) 박스 + 굵은 헤더 폰트, 자동 줄바꿈 + 크기 상한
  · 자막: SRT 번인 (설정 폰트, 검은 박스, 인스타 세이프존 정렬)
  · 푸터(선택): 고정 이미지 스트립 (설정에 있으면)

폰트·색·푸터·크기는 전부 config JSON으로 지정한다 (config/style.example.json 참고).
개인 폰트·이미지는 저장소에 포함하지 않는다 — 사용자가 자기 것을 지정한다.

Usage:
    python helpers/compose.py <cut.mp4> -o <final.mp4> \
        --title "훅 1줄?!|해결 1줄!" --srt <subs.srt> \
        --config config/style.json [--focus 0.5]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULTS = {
    "banner_color": [0, 254, 59],        # 헤더 배너 색 (RGB)
    "header_font": "",                    # 헤더 폰트 파일 경로 (필수)
    "header_max_em": 104,                 # 헤더 폰트 크기 상한(px). 발행분에 맞춰 조정
    "header_tracking": -5,                # 자간(px, 음수=촘촘)
    "header_line_gap": 4,                 # 줄간격(px)
    "header_stroke": 1,                   # 획 보강(px)
    "header_max_lines": 3,
    "subtitle_font": "AppleSDGothicNeo-Bold",   # 자막 폰트명(libass용)
    "subtitle_size": 14,
    "subtitle_style_extra": ("PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                             "BackColour=&H00000000,BorderStyle=3,Outline=2.5,"
                             "Shadow=0,Alignment=2,MarginV=72,MarginL=75,MarginR=75"),
    "footer_image": "",                   # 하단 고정 푸터 이미지(선택, 없으면 생략)
    "source_crop": [715, 864],            # 소스에서 잘라올 [w,h] (하단 번인자막 회피용)
    "video_scale": [1080, 1306],          # 크롭 후 스케일
    "video_y": 264,                       # 캔버스 내 영상 y 위치
    "banner_y": 280,                      # 배너 y 위치
}


def make_title_png(text, out, cfg, max_box_w=900):
    """'줄1|줄2'(| = 강제 줄바꿈) → 단일 컬러 박스 배너.
    header_max_em 상한부터 내려오며 '폭 통과 + max_lines 이내'인 최대 크기 채택.
    타이트 레딩(실제 글자높이 기준) + 자간/스트로크로 촘촘한 두꺼운 블록."""
    from PIL import Image, ImageDraw, ImageFont
    font_path = cfg["header_font"]
    if not font_path or not Path(font_path).exists():
        sys.exit(f"header_font 경로가 유효하지 않습니다: {font_path!r}\n"
                 "config JSON의 header_font에 폰트 파일 경로를 지정하세요.")
    paragraphs = [p.strip() for p in text.split("|") if p.strip()]
    tracking = cfg["header_tracking"]
    line_gap = cfg["header_line_gap"]
    stroke = cfg["header_stroke"]
    max_lines = cfg["header_max_lines"]
    color = tuple(cfg["banner_color"])
    pad_x, pad_y = 30, 14
    ink = (10, 10, 10, 255)
    usable = max_box_w - 2 * pad_x

    def text_w(font, s):
        w = 0
        for ch in s:
            bb = font.getbbox(ch, stroke_width=stroke)
            w += (bb[2] - bb[0]) + tracking
        return w - tracking if s else 0

    def wrap(font, para):
        lines, cur = [], ""
        for word in para.split(" "):
            trial = word if not cur else cur + " " + word
            if text_w(font, trial) <= usable:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    chosen_font, chosen_lines, fallback = None, None, None
    for size in range(cfg["header_max_em"], 52, -2):
        font = ImageFont.truetype(font_path, size)
        lines = []
        for para in paragraphs:
            lines += wrap(font, para)
        widths_ok = all(text_w(font, l) <= usable for l in lines)
        if fallback is None and widths_ok:
            fallback = (font, lines)
        if widths_ok and len(lines) <= max_lines:
            chosen_font, chosen_lines = font, lines
            break
    if chosen_font is None:
        chosen_font, chosen_lines = fallback or (
            ImageFont.truetype(font_path, 80),
            sum([wrap(ImageFont.truetype(font_path, 80), p) for p in paragraphs], []))

    probe = chosen_font.getbbox("한글뷁판문", stroke_width=stroke)
    glyph_h = probe[3] - probe[1]
    gtop = probe[1]
    widths = [text_w(chosen_font, l) for l in chosen_lines]
    n = len(chosen_lines)
    W = max(widths) + pad_x * 2
    H = glyph_h * n + line_gap * (n - 1) + pad_y * 2
    img = Image.new("RGBA", (W + 8, H + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, 4 + W, 4 + H], radius=14, fill=(*color, 255))
    y = 4 + pad_y
    for ln, lw in zip(chosen_lines, widths):
        x = 4 + (W - lw) // 2
        for ch in ln:
            bb = chosen_font.getbbox(ch, stroke_width=stroke)
            d.text((x - bb[0], y - gtop), ch, font=chosen_font, fill=ink,
                   stroke_width=stroke, stroke_fill=ink)
            x += (bb[2] - bb[0]) + tracking
        y += glyph_h + line_gap
    img.save(out)
    return img.width, img.height


def load_config(path):
    cfg = dict(DEFAULTS)
    if path and Path(path).exists():
        cfg.update(json.loads(Path(path).read_text()))
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--title", required=True, help="'훅?!|해결!' 형식(| = 줄바꿈)")
    ap.add_argument("--srt", type=Path, default=None)
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--focus", type=float, default=0.5)
    args = ap.parse_args()

    cfg = load_config(args.config)
    src = args.input.resolve()

    sub_style = (f"FontName={cfg['subtitle_font']},FontSize={cfg['subtitle_size']},"
                 f"Bold=1,{cfg['subtitle_style_extra']}")
    cw, ch = cfg["source_crop"]
    sw, sh = cfg["video_scale"]
    footer = cfg.get("footer_image", "")

    with tempfile.TemporaryDirectory() as tmp:
        title_png = Path(tmp) / "title.png"
        make_title_png(args.title, title_png, cfg)

        inputs = ["-i", str(src), "-i", str(title_png)]
        vf = [
            f"[0:v]crop={cw}:{ch}:(iw-{cw})*{args.focus}:0,"
            f"scale={sw}:{sh}:flags=lanczos[vid]",
            "color=c=black:s=1080x1920[bg]",
            f"[bg][vid]overlay=0:{cfg['video_y']}:shortest=1[c1]",
            f"[c1][1:v]overlay=(W-w)/2:{cfg['banner_y']}[c2]",
        ]
        last = "[c2]"
        if footer and Path(footer).exists():
            inputs += ["-i", str(footer)]
            vf.append(f"[c2][2:v]overlay=0:H-h[c3]")
            last = "[c3]"
        if args.srt:
            srt_esc = str(args.srt.resolve()).replace(":", r"\:").replace("'", r"\'")
            vf.append(f"{last}subtitles='{srt_esc}':force_style='{sub_style}'[out]")
            last = "[out]"

        cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(vf),
               "-map", last, "-map", "0:a?", "-c:v", "libx264", "-preset", "slow",
               "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
               "-movflags", "+faststart", str(args.output)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"ffmpeg failed:\n{r.stderr[-800:]}")
    print(f"composed: {args.output}")


if __name__ == "__main__":
    main()
