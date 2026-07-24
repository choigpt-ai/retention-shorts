"""Transcribe a video locally with faster-whisper, emitting ElevenLabs
Scribe-compatible JSON so downstream tools
consume it unchanged.

Scribe 스키마 호환: words 배열에 type=word 항목 + 단어 사이 갭은 type=spacing
항목으로 삽입. speaker_id는 로컬 전사에서는 None (diarization 없음).

Cached: if <edit_dir>/transcripts/<stem>.json exists, skip.

Usage:
    python helpers/local_transcribe.py <video> [<video2> ...]
    python helpers/local_transcribe.py <video> --edit-dir /custom/edit
    python helpers/local_transcribe.py <video> --language ko --model large-v3-turbo
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

MODELS = ["large-v3-turbo", "large-v3", "medium", "small", "base"]

# silence_scan.py의 silencedetect 파서를 재사용 (같은 helpers/ 디렉토리)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from silence_scan import scan as silence_scan_run  # noqa: E402


def clamp_words_to_silences(words: list[dict], silences: list[tuple[float, float]]) -> None:
    """무음 구간을 침범한 단어 경계를 잘라내 실제 갭이 드러나게 한다. in-place."""
    for w in words:
        if w["type"] != "word":
            continue
        for s, e in silences:
            # 단어 끝이 무음 안으로 늘어난 경우 → 무음 시작으로 당김
            if w["start"] < s < w["end"] <= e + 0.05:
                w["end"] = round(max(w["start"] + 0.05, s), 3)
            # 단어 시작이 무음 안으로 당겨진 경우 → 무음 끝으로 밀어냄
            if s - 0.05 <= w["start"] < e < w["end"]:
                w["start"] = round(min(w["end"] - 0.05, e), 3)


def transcribe_one(
    model,
    video: Path,
    edit_dir: Path,
    language: str | None,
    verbose: bool = True,
) -> Path:
    transcripts_dir = edit_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    out_path = transcripts_dir / f"{video.stem}.json"

    if out_path.exists():
        if verbose:
            print(f"cached: {out_path.name}")
        return out_path

    t0 = time.time()
    segments, info = model.transcribe(
        str(video),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        # verbatim에 가깝게: 필러가 남을 확률을 높인다 (Scribe만큼은 아님)
        condition_on_previous_text=False,
    )

    raw_words: list[dict] = []
    full_text_parts: list[str] = []

    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if not text:
                continue
            raw_words.append({
                "text": text,
                "start": round(float(w.start), 3),
                "end": round(float(w.end), 3),
                "type": "word",
                "speaker_id": None,
            })
            full_text_parts.append(text)

    # whisper는 단어 경계를 무음 구간까지 늘려 갭 정보를 지운다 →
    # 실측 무음(silencedetect)으로 경계를 클램프해 갭을 복원한다.
    # (한계: BGM이 깔린 소스는 무음이 마스킹돼 효과 없음)
    n_silences = 0
    try:
        scan_result = silence_scan_run(video, noise="-35dB", min_dur=0.35)
        silences = [(s["start"], s["end"]) for s in scan_result["silences"]]
        n_silences = len(silences)
        clamp_words_to_silences(raw_words, silences)
    except Exception as exc:  # 무음 스캔 실패가 전사를 막으면 안 된다
        print(f"  warn: silence scan failed ({exc}); gaps rely on whisper timestamps only")

    words: list[dict] = []
    prev_end: float | None = None
    for w in raw_words:
        if prev_end is not None and w["start"] > prev_end + 0.001:
            words.append({
                "text": " ",
                "start": prev_end,
                "end": w["start"],
                "type": "spacing",
                "speaker_id": None,
            })
        words.append(w)
        prev_end = w["end"]

    payload = {
        "language_code": info.language,
        "language_probability": round(float(info.language_probability), 4),
        "text": " ".join(full_text_parts),
        "words": words,
        "_meta": {
            "engine": "faster-whisper",
            "model": getattr(model, "_va_model_name", "unknown"),
            "duration": round(float(info.duration), 3),
            "silences_clamped": n_silences,
            "note": "Scribe-compatible local transcript. No diarization, no audio events.",
        },
    }

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    dt = time.time() - t0

    if verbose:
        kb = out_path.stat().st_size / 1024
        n_words = sum(1 for w in words if w["type"] == "word")
        print(f"  saved: {out_path.name} ({kb:.1f} KB, {n_words} words) in {dt:.1f}s")

    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Local faster-whisper transcription, Scribe-compatible output")
    ap.add_argument("videos", type=Path, nargs="+", help="Video file(s)")
    ap.add_argument("--edit-dir", type=Path, default=None,
                    help="Edit output dir (default: <video_parent>/edit)")
    ap.add_argument("--language", type=str, default=None,
                    help="ISO code e.g. 'ko'. Omit to auto-detect.")
    ap.add_argument("--model", type=str, default="large-v3-turbo", choices=MODELS,
                    help="faster-whisper model (default: large-v3-turbo)")
    args = ap.parse_args()

    videos = [v.resolve() for v in args.videos]
    for v in videos:
        if not v.exists():
            sys.exit(f"video not found: {v}")

    # 캐시 전부 히트면 모델 로드 자체를 건너뛴다
    def out_for(v: Path) -> Path:
        edit = (args.edit_dir or (v.parent / "edit")).resolve()
        return edit / "transcripts" / f"{v.stem}.json"

    if all(out_for(v).exists() for v in videos):
        for v in videos:
            print(f"cached: {out_for(v).name}")
        return

    from faster_whisper import WhisperModel
    print(f"loading model {args.model} (cpu/int8)...", flush=True)
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    model._va_model_name = args.model

    for v in videos:
        edit_dir = (args.edit_dir or (v.parent / "edit")).resolve()
        print(f"transcribing {v.name}", flush=True)
        transcribe_one(model, v, edit_dir, args.language)


if __name__ == "__main__":
    main()
