"""Build the deterministic skeleton of an SEO/GEO distribution pack.

렌더 완료 후 실행. edl.json의 beat/quote → 유튜브 챕터 타임스탬프,
전사 텍스트 → 풀 트랜스크립트, ffprobe → ISO8601 duration을 뽑아
<edit>/seo/ 아래에 스캐폴드를 만든다. 제목·설명·해시태그 등 창작 필드는
스킬(LLM)이 스캐폴드의 <<TODO>> 마커를 채운다.

Outputs:
    <edit>/seo/seo_pack.md        — 업로드용 팩 (LLM이 TODO 채움)
    <edit>/seo/video_jsonld.json  — schema.org VideoObject (LLM이 TODO 채움)
    <edit>/seo/transcript.txt     — 풀 트랜스크립트 (GEO 인용용)

Usage:
    python helpers/build_seo_pack.py --edit-dir <videos_dir>/edit [--final final.mp4]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def iso8601_duration(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    out = "PT"
    if h:
        out += f"{h}H"
    if m:
        out += f"{m}M"
    out += f"{sec}S"
    return out


def yt_timestamp(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def load_chapters(edl_path: Path) -> list[dict]:
    """EDL ranges → output-timeline chapters (beat 단위로 병합)."""
    edl = json.loads(edl_path.read_text())
    chapters = []
    cursor = 0.0
    prev_beat = None
    for r in edl.get("ranges", []):
        dur = float(r["end"]) - float(r["start"])
        beat = r.get("beat") or "SECTION"
        if beat != prev_beat:
            chapters.append({
                "t": round(cursor, 2),
                "beat": beat,
                "quote": (r.get("quote") or "")[:80],
            })
            prev_beat = beat
        cursor += dur
    return chapters


def main() -> None:
    ap = argparse.ArgumentParser(description="SEO/GEO pack scaffold builder")
    ap.add_argument("--edit-dir", type=Path, required=True)
    ap.add_argument("--final", type=str, default="final.mp4")
    args = ap.parse_args()

    edit = args.edit_dir.resolve()
    seo = edit / "seo"
    seo.mkdir(parents=True, exist_ok=True)

    # duration
    final = edit / args.final
    duration = None
    if final.exists():
        duration = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(final)],
            capture_output=True, text=True, check=True).stdout.strip())

    # transcript
    texts = []
    for tj in sorted((edit / "transcripts").glob("*.json")):
        data = json.loads(tj.read_text())
        if data.get("text"):
            texts.append(data["text"])
    transcript = "\n\n".join(texts)
    (seo / "transcript.txt").write_text(transcript)

    # chapters from EDL
    edl_path = edit / "edl.json"
    chapters = load_chapters(edl_path) if edl_path.exists() else []
    chapter_lines = "\n".join(
        f"{yt_timestamp(c['t'])} <<TODO: '{c['beat']}' 구간 제목 — 근거: {c['quote']}>>"
        for c in chapters
    ) or "0:00 <<TODO: 챕터 — edl.json 없음, 직접 구성>>"

    pack = f"""# SEO/GEO 배포 팩 — <<TODO: 영상 주제>>

> 이 파일의 <<TODO>>를 스킬 규칙(video-edit SKILL.md 'SEO/GEO 단계')에 따라 채운다.

## 1. 제목 후보 (3개 — 검색형/호기심형/GEO질문형)
1. <<TODO: 핵심 키워드 앞배치, 45자 이내>>
2. <<TODO: 호기심 갭>>
3. <<TODO: AI 검색이 그대로 인용할 수 있는 완결 질문형>>

## 2. 설명 (첫 3줄이 승부 — 접힘 전 노출)
<<TODO 1줄: 핵심 키워드 포함 요약. AI 엔진이 그대로 인용할 수 있는 완결 문장>>
<<TODO 2줄: 시청자 얻는 것>>
<<TODO 3줄: CTA>>

### 챕터
{chapter_lines}

### 본문 상세 + FAQ (GEO 핵심 — 질문을 소제목으로)
<<TODO: 영상 내용 기반 Q&A 3~5개. 각 답변은 첫 문장에서 완결>>

## 3. 태그/해시태그
- 태그(YouTube, 쉼표구분): <<TODO: 10~15개, 핵심→파생 순>>
- 해시태그(3개만): <<TODO>>

## 4. 썸네일 텍스트 후보
<<TODO: 3개, 각 8자 이내, 제목과 중복 금지(정보 추가)>>

## 5. 메타 정보 (자동)
- 길이: {yt_timestamp(duration) if duration else "<<final.mp4 없음>>"} ({iso8601_duration(duration) if duration else "-"})
- 전사 워드수 근거: transcript.txt
- 홈페이지/블로그 임베드 시: video_jsonld.json을 <script type="application/ld+json">로 삽입
"""
    (seo / "seo_pack.md").write_text(pack)

    jsonld = {
        "@context": "https://schema.org",
        "@type": "VideoObject",
        "name": "<<TODO: 확정 제목>>",
        "description": "<<TODO: 설명 첫 3줄>>",
        "thumbnailUrl": ["<<TODO: 썸네일 URL>>"],
        "uploadDate": "<<TODO: YYYY-MM-DD>>",
        "duration": iso8601_duration(duration) if duration else "<<TODO>>",
        "contentUrl": "<<TODO: 영상 URL>>",
        "embedUrl": "<<TODO: 임베드 URL>>",
        "transcript": transcript[:1500] + ("..." if len(transcript) > 1500 else ""),
    }
    (seo / "video_jsonld.json").write_text(
        json.dumps(jsonld, ensure_ascii=False, indent=2))

    print(f"scaffolded: {seo / 'seo_pack.md'}")
    print(f"scaffolded: {seo / 'video_jsonld.json'}")
    print(f"transcript: {seo / 'transcript.txt'} ({len(transcript)} chars)")
    if not chapters:
        print("warn: edl.json not found — chapters left as TODO", file=sys.stderr)


if __name__ == "__main__":
    main()
