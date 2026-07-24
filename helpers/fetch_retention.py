"""YouTube Analytics API로 본인 채널 영상의 시청 지속률(리텐션)을 수집하고
스파이크(집중 구간)를 검출한다.

선행 조건 (1회):
  1. Google Cloud Console에서 프로젝트 생성 → YouTube Analytics API 활성화
  2. OAuth 클라이언트 ID(데스크톱 앱) 생성 → client_secret.json 다운로드
  3. 이 폴더의 config/client_secret.json 으로 저장
  최초 실행 시 브라우저 동의창이 뜨고, 토큰은 config/yt_token.json에 캐시된다.

Usage:
    python helpers/fetch_retention.py <VIDEO_ID> [--out retention/<id>.json]

Output JSON:
    { video_id, duration_s(추정불가시 null), points: [{ratio, watch_ratio, rel_perf}],
      spikes: [{ratio, watch_ratio, note}] }  # ratio = 영상 길이 대비 0.0~1.0
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / "config"
SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly"]


def get_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("의존성 없음: uv pip install google-auth google-auth-oauthlib google-api-python-client")

    token_path = CONFIG / "yt_token.json"
    secret_path = CONFIG / "client_secret.json"
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not secret_path.exists():
                sys.exit(f"client_secret.json 없음 → {secret_path}\n"
                         "Google Cloud Console에서 OAuth 데스크톱 클라이언트 생성 후 저장하세요.")
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return build("youtubeAnalytics", "v2", credentials=creds)


def detect_spikes(points: list[dict], window: int = 5, k: float = 1.15) -> list[dict]:
    """이동평균 대비 k배 이상 솟은 로컬 피크 = 집중 스파이크.

    audienceWatchRatio는 뒤로 갈수록 단조 감소가 기본형이라,
    '주변 평균 대비 상대적으로 높은 지점'을 피크로 본다.
    """
    if len(points) < window * 2:
        return []
    vals = [p["watch_ratio"] for p in points]
    spikes = []
    for i in range(window, len(vals) - window):
        neigh = vals[i - window:i] + vals[i + 1:i + 1 + window]
        base = sum(neigh) / len(neigh)
        if base > 0 and vals[i] / base >= k and vals[i] >= max(vals[i - 1], vals[i + 1]):
            spikes.append({
                "ratio": points[i]["ratio"],
                "watch_ratio": vals[i],
                "note": f"주변평균 대비 {vals[i]/base:.2f}x",
            })
    # 재시청(리와인드) 신호: 직전 구간보다 상승한 지점도 후보
    for i in range(1, len(vals)):
        if vals[i] > vals[i - 1] * 1.05:
            spikes.append({"ratio": points[i]["ratio"], "watch_ratio": vals[i],
                           "note": "리와인드 상승(재시청 구간)"})
    # dedup by ratio
    seen, out = set(), []
    for s in sorted(spikes, key=lambda x: x["ratio"]):
        key = round(s["ratio"], 3)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    yt = get_service()
    resp = yt.reports().query(
        ids="channel==MINE",
        startDate="2020-01-01",
        endDate="2030-01-01",
        metrics="audienceWatchRatio,relativeRetentionPerformance",
        dimensions="elapsedVideoTimeRatio",
        filters=f"video=={args.video_id};audienceType==ORGANIC",
    ).execute()

    rows = resp.get("rows", [])
    if not rows:
        sys.exit("리텐션 데이터 없음 — 조회수가 적거나 비공개 영상. 전사 하이라이트 폴백을 사용하세요.")

    points = [{"ratio": r[0], "watch_ratio": r[1], "rel_perf": r[2] if len(r) > 2 else None}
              for r in rows]
    spikes = detect_spikes(points)

    out = args.out or (BASE / "retention" / f"{args.video_id}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"video_id": args.video_id, "points": points,
                               "spikes": spikes}, ensure_ascii=False, indent=2))
    print(f"saved: {out}")
    print(f"  points={len(points)}, spikes={len(spikes)}")
    for s in spikes[:8]:
        print(f"  spike @ {s['ratio']*100:.0f}% — {s['note']}")


if __name__ == "__main__":
    main()
