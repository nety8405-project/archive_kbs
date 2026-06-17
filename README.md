# archive_kbs — 사내 아카이브 자동 쇼츠 파이프라인

사내 아카이브 서버에서 영상을 내려받아, AI로 재미있는 구간을 찾아 쇼츠로 만들고 YouTube에 자동 업로드하는 파이프라인입니다.

---

## 구조

```
archive_kbs/
├── main.py                        # 오케스트레이터 (진입점)
├── requirements.txt
├── .env.example                   # 환경변수 템플릿
├── src/
│   ├── downloader/
│   │   ├── archive_client.py      # 사내 아카이브 HTTP 클라이언트
│   │   └── download_manager.py    # 다운로드 + DB 상태 관리
│   ├── analyzer/
│   │   ├── transcriber.py         # Whisper 자막 추출
│   │   ├── scene_detector.py      # 장면 전환 감지
│   │   ├── interest_scorer.py     # GPT-4o 흥미도 점수
│   │   └── content_analyzer.py    # 분석 오케스트레이터
│   ├── generator/
│   │   └── shorts_generator.py    # ffmpeg 쇼츠 생성 (9:16)
│   ├── uploader/
│   │   └── youtube_uploader.py    # YouTube Data API 업로드
│   └── utils/
│       ├── logger.py              # loguru 설정
│       ├── network_guard.py       # 사내망 접속 검증
│       └── database.py            # SQLite 모델 (SQLAlchemy)
└── data/
    ├── downloads/                 # 원본 영상
    ├── shorts/                    # 생성된 쇼츠
    └── pipeline.db                # 상태 DB
```

---

## 시작하기

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

ffmpeg도 필요합니다:
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

### 2. 환경변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열어 아래 항목을 채웁니다:

| 변수 | 설명 |
|---|---|
| `ARCHIVE_BASE_URL` | 사내 아카이브 서버 주소 |
| `ARCHIVE_USERNAME` | 사내 계정 ID |
| `ARCHIVE_PASSWORD` | 사내 계정 비밀번호 |
| `INTERNAL_SUBNET` | 사내 IP 대역 (예: `192.168.1.`) |
| `OPENAI_API_KEY` | OpenAI API 키 |
| `YOUTUBE_CLIENT_ID` | YouTube OAuth2 클라이언트 ID |
| `YOUTUBE_CLIENT_SECRET` | YouTube OAuth2 클라이언트 시크릿 |

### 3. YouTube OAuth2 설정

[Google Cloud Console](https://console.cloud.google.com)에서:
1. 프로젝트 생성
2. YouTube Data API v3 활성화
3. OAuth 2.0 클라이언트 ID 생성 (데스크톱 앱)
4. Client ID / Secret을 `.env`에 기입

첫 실행 시 브라우저가 열려 구글 계정 인증을 요청합니다. 이후에는 토큰이 저장되어 자동 인증됩니다.

### 4. 아카이브 클라이언트 API 연동

`src/downloader/archive_client.py`의 `ENDPOINTS` 딕셔너리와 파싱 로직을 실제 서버 API에 맞게 수정하세요.

---

## 실행

```bash
# 기본 실행 (최신 10개 처리)
python main.py

# 최대 5개, 특정 날짜 이후 콘텐츠
python main.py --limit 5 --date-from 2024-01-01

# 다운로드는 건너뛰고 이미 받은 파일만 처리
python main.py --skip-download

# YouTube 업로드 없이 로컬에만 저장
python main.py --skip-upload

# 매일 오전 6시 자동 실행
python main.py --schedule
```

---

## 파이프라인 흐름

```
[사내 아카이브] → 다운로드
      ↓
[Whisper] → 자막(타임코드) 추출
      ↓
[scenedetect] → 장면 경계 탐지
      ↓
[GPT-4o] → 구간별 흥미도 점수 (1~10)
      ↓
상위 구간 선택 (기본 7점 이상)
      ↓
[ffmpeg] → 9:16 세로형 쇼츠 생성 + 자막 삽입
      ↓
[YouTube API] → 제목/설명 자동 생성 후 업로드
```

---

## 주의사항

- 이 파이프라인은 **사내망에서만 실행**됩니다. 외부 접속 시 자동 차단됩니다.
- Whisper `large-v3` 모델은 GPU 없이도 동작하나, 처리 속도가 느립니다. GPU 환경에서는 훨씬 빠릅니다.
- YouTube 업로드 할당량은 하루 10,000 units입니다. 영상 1개 업로드에 약 1,600 units 소비됩니다.
