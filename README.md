# retention-shorts

**롱폼 영상에서 "고객 반응(시청 지속률)이 좋았던 구간"만 자동으로 골라 세로 숏폼으로 만드는 오픈소스 툴킷.**

유튜브 리텐션 데이터로 시청자가 몰린 구간을 찾고 → 그 지점을 콜드오픈으로 재구성 →
9:16 리프레이밍 → 헤더/자막 번인 → 인스타 릴스 세이프존 검수까지. 로컬 전사(faster-whisper)라
전사 비용 0원, ffmpeg만 있으면 됩니다.

> 이 툴킷은 [browser-use/video-use](https://github.com/browser-use/video-use)(MIT)의
> "LLM은 영상을 보지 않고 읽는다" 발상에서 출발했습니다. 여기서는 그 발상을
> **숏폼 양산 + 리텐션 기반 구간 선정 + 세로 템플릿 합성**에 특화했습니다.

---

## 왜 이걸 쓰나

기존 숏폼 자동화 툴은 "아무 구간이나 잘라서" 붙입니다. 이 툴킷은 다릅니다:

1. **데이터로 구간을 고른다** — 유튜브 시청 지속률에서 시청자가 되감아 본(리와인드)
   구간, 주변보다 튄 스파이크를 찾아 "실제로 반응 좋았던 곳"만 뽑습니다.
   (리텐션이 없거나 조회수가 적으면 전사 텍스트 기반 하이라이트로 폴백)
2. **스파이크를 그대로 시작점으로 쓰지 않는다** — 터진 지점(페이오프)을 0~3초
   콜드오픈 훅으로 앞당겨 재구성합니다. 맥락 없는 시작 = 이탈이니까요.
3. **발행 전 세이프존 검수 관문** — 인스타/릴스 UI(우측 아이콘·하단 캡션)에
   헤더·얼굴·자막이 가리지 않는지 자동으로 확인합니다.

## 파이프라인

```
[롱폼]
  │  helpers/fetch_retention.py   유튜브 리텐션 → 스파이크 검출
  │  helpers/transcribe.py        faster-whisper 로컬 전사(단어 타임스탬프)
  ▼
[구간 선정 + 콜드오픈 재구성]  ← 스파이크를 전사에 매핑, 페이오프를 훅으로
  │  (원하는 구간을 ffmpeg로 컷)
  ▼
[9:16 리프레이밍]  helpers/reframe916.py   crop(인물) / blur(화면공유)
  ▼
[템플릿 합성]  helpers/compose.py   헤더 배너 + 자막 번인 + (선택)푸터
  ▼
[세이프존 검수]  helpers/reels_guide_qc.py   릴스 UI 가림 여부 확인
  ▼
[숏폼 완성]
```

## 설치

```bash
# ffmpeg 필수 — 자막 번인(libass)이 되는 빌드여야 함
#   macOS:  brew install ffmpeg   (안 되면 brew install ffmpeg-full)
#   확인:   ffmpeg -filters | grep subtitles
pip install -r requirements.txt
cp config/style.example.json config/style.json   # 폰트·색·푸터 본인 값으로 수정
```

## 사용법

```bash
# 1) 리텐션 수집 (본인 채널 영상만 — Google Cloud OAuth 필요, 아래 참고)
python helpers/fetch_retention.py <YOUTUBE_VIDEO_ID>

# 2) 전사 (단어 단위 타임스탬프)
python helpers/transcribe.py longform.mp4 --language ko

# 3) 스파이크를 전사에 매핑해 콜드오픈 구간 선정 후, 원하는 구간을 컷
ffmpeg -ss <start> -to <end> -i longform.mp4 -c:v libx264 -c:a aac cut.mp4

# 4) 9:16 리프레이밍 (인물은 crop, 화면공유는 blur)
python helpers/reframe916.py cut.mp4 -o cut916.mp4 --mode crop --focus 0.5

# 5) 헤더·자막 합성 (config로 폰트/색/푸터 지정)
python helpers/compose.py cut916.mp4 -o final.mp4 \
    --title "훅 1줄?!|해결 1줄!" --srt subs.srt --config config/style.json

# 6) 발행 전 세이프존 검수
python helpers/reels_guide_qc.py final.mp4
#   생성된 guide_*.png를 눈으로 확인: 헤더·얼굴·자막이 초록 박스 안인가?
```

### 유튜브 리텐션 OAuth (1회 세팅)

1. [Google Cloud Console](https://console.cloud.google.com) → 프로젝트 생성 →
   **YouTube Analytics API** 활성화
2. OAuth 클라이언트 ID(**데스크톱 앱**) 생성 → JSON 다운로드
3. `config/client_secret.json` 으로 저장 (이 파일은 `.gitignore`에 있음 — 절대 커밋 금지)
4. 최초 실행 시 브라우저 동의 → 토큰이 `config/yt_token.json`에 캐시됨
   (리텐션 데이터는 **본인 채널 영상**만 조회 가능합니다)

## 헤더/자막 커스터마이징

- **폰트·색·푸터는 저장소에 없습니다.** `config/style.json`에 본인 폰트 경로와
  색을 지정하세요. 굵고 가독성 좋은 폰트를 헤더에 추천합니다.
- 헤더 카피는 **후킹형 2줄**(도발 질문 `?!` + 해결/FOMO)이 잘 먹힙니다.
  큰 폰트는 줄당 글자수가 제한되니 짧게 압축하세요.
- 푸터(프로필+문구)는 1080폭 PNG를 직접 만들어 `footer_image`에 지정하면 됩니다.

## 구성 요소

| 파일 | 역할 |
|------|------|
| `helpers/fetch_retention.py` | 유튜브 시청 지속률 → 스파이크/리와인드 검출 |
| `helpers/transcribe.py` | faster-whisper 로컬 전사(단어 타임스탬프, 무료) |
| `helpers/silence_scan.py` | 무음 구간 검출(장편 프리스캔·전사 갭 복원) |
| `helpers/reframe916.py` | 16:9 → 9:16 (crop / blur 두 모드) |
| `helpers/compose.py` | 헤더 배너 + 자막 번인 + 푸터 합성 (config 기반) |
| `helpers/reels_guide_qc.py` | 릴스 세이프존 검수 이미지 생성 |
| `helpers/build_seo_pack.py` | (선택) 제목·설명·챕터·FAQ·JSON-LD 스캐폴드 |

## 라이선스

MIT. 상업적 사용 가능. video-use(MIT)의 발상에 빚지고 있습니다.
