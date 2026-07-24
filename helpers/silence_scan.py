"""Scan a video for silences + loudness profile, emitting cut-candidate JSON.

장편(10분+) 원본에서 LLM이 EDL을 짜기 전에 기계적으로 컷 후보를 뽑아
컨텍스트를 아끼는 프리패스. ffmpeg silencedetect + loudnorm 통계 사용.

Output: <edit_dir>/silence/<stem>.json
    {
      "duration": 1834.2,
      "silences": [{"start": 12.34, "end": 13.10, "dur": 0.76}, ...],
      "speech_blocks": [{"start": 0.0, "end": 12.34, "dur": 12.34}, ...],
      "stats": {"n_silences": 42, "silence_total": 61.2, "speech_total": 1773.0}
    }

Usage:
    python helpers/silence_scan.py <video> [--noise -35dB] [--min-dur 0.45]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def ffprobe_duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def scan(video: Path, noise: str, min_dur: float) -> dict:
    duration = ffprobe_duration(video)
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video),
         "-af", f"silencedetect=noise={noise}:d={min_dur}",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    log = proc.stderr

    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", log)]

    silences = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else duration
        silences.append({"start": round(s, 3), "end": round(e, 3),
                         "dur": round(e - s, 3)})

    speech_blocks = []
    cursor = 0.0
    for sil in silences:
        if sil["start"] > cursor + 0.05:
            speech_blocks.append({"start": round(cursor, 3),
                                  "end": sil["start"],
                                  "dur": round(sil["start"] - cursor, 3)})
        cursor = sil["end"]
    if duration > cursor + 0.05:
        speech_blocks.append({"start": round(cursor, 3), "end": round(duration, 3),
                              "dur": round(duration - cursor, 3)})

    silence_total = sum(s["dur"] for s in silences)
    return {
        "video": video.name,
        "duration": round(duration, 3),
        "params": {"noise": noise, "min_dur": min_dur},
        "silences": silences,
        "speech_blocks": speech_blocks,
        "stats": {
            "n_silences": len(silences),
            "silence_total": round(silence_total, 1),
            "speech_total": round(duration - silence_total, 1),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Silence/cut-candidate pre-scan")
    ap.add_argument("videos", type=Path, nargs="+")
    ap.add_argument("--edit-dir", type=Path, default=None,
                    help="Output dir (default: <video_parent>/edit)")
    ap.add_argument("--noise", type=str, default="-35dB",
                    help="silencedetect noise threshold (default: -35dB)")
    ap.add_argument("--min-dur", type=float, default=0.45,
                    help="minimum silence duration in seconds (default: 0.45)")
    args = ap.parse_args()

    for v in args.videos:
        v = v.resolve()
        if not v.exists():
            sys.exit(f"video not found: {v}")
        edit_dir = (args.edit_dir or (v.parent / "edit")).resolve()
        out_dir = edit_dir / "silence"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{v.stem}.json"
        if out.exists():
            print(f"cached: {out.name}")
            continue
        result = scan(v, args.noise, args.min_dur)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        st = result["stats"]
        print(f"{v.name}: {st['n_silences']} silences, "
              f"{st['silence_total']}s silent / {result['duration']}s total "
              f"-> {out}")


if __name__ == "__main__":
    main()
