"""
YouTube Uploader.
OAuth2 인증 후 완성된 쇼츠를 YouTube에 업로드합니다.
"""

import json
import os
from datetime import datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from loguru import logger
from openai import OpenAI


SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

CLIENT_SECRETS = {
    "installed": {
        "client_id": "",        # .env에서 주입됨
        "client_secret": "",    # .env에서 주입됨
        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}


class YouTubeUploader:
    def __init__(self):
        self.token_file = os.getenv("YOUTUBE_TOKEN_FILE", "config/youtube_token.json")
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self._service = None

    # ------------------------------------------------------------------
    # 인증
    # ------------------------------------------------------------------

    def _get_credentials(self) -> Credentials:
        creds = None
        token_path = Path(self.token_file)

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                secrets = CLIENT_SECRETS.copy()
                secrets["installed"]["client_id"] = os.getenv("YOUTUBE_CLIENT_ID", "")
                secrets["installed"]["client_secret"] = os.getenv("YOUTUBE_CLIENT_SECRET", "")

                flow = InstalledAppFlow.from_client_config(secrets, SCOPES)
                creds = flow.run_local_server(port=0)

            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())
            logger.info(f"YouTube 토큰 저장 완료: {token_path}")

        return creds

    def _get_service(self):
        if not self._service:
            creds = self._get_credentials()
            self._service = build("youtube", "v3", credentials=creds)
        return self._service

    # ------------------------------------------------------------------
    # 메타데이터 자동 생성
    # ------------------------------------------------------------------

    def generate_metadata(self, transcript: str, suggested_title: str = "") -> dict:
        """GPT-4o로 업로드용 제목/설명/태그를 생성합니다."""
        prompt = f"""
다음 영상 대본을 바탕으로 유튜브 쇼츠 업로드용 메타데이터를 작성해 주세요.

추천 제목 힌트: {suggested_title}
대본: {transcript[:500]}

반드시 JSON 형식으로 응답하세요:
{{
  "title": "<유튜브 쇼츠 제목 (50자 이내, 이모지 1~2개 포함)>",
  "description": "<설명 (150자 이내)>",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"]
}}
"""
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"메타데이터 생성 실패: {e}")
            return {
                "title": suggested_title or "사내 아카이브 클립",
                "description": "",
                "tags": [],
            }

    # ------------------------------------------------------------------
    # 업로드
    # ------------------------------------------------------------------

    def upload(
        self,
        video_path: str | Path,
        title: str,
        description: str = "",
        tags: list[str] | None = None,
        category_id: str = "24",   # 24 = Entertainment
        privacy: str = "public",   # public / unlisted / private
    ) -> str:
        """
        쇼츠를 YouTube에 업로드합니다.

        Returns:
            업로드된 YouTube 영상 ID
        """
        video_path = Path(video_path)
        tags = tags or []

        logger.info(f"YouTube 업로드 시작: {video_path.name}")

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,
            chunksize=8 * 1024 * 1024,  # 8MB 청크
        )

        service = self._get_service()
        request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.debug(f"업로드 진행: {int(status.progress() * 100)}%")

        video_id = response["id"]
        logger.info(f"업로드 완료: https://youtube.com/shorts/{video_id}")
        return video_id

    def upload_with_auto_metadata(
        self,
        video_path: str | Path,
        segment: dict,
        privacy: str = "public",
    ) -> str:
        """
        분석 결과 세그먼트를 받아 메타데이터를 자동 생성하고 업로드합니다.

        Args:
            segment: ContentAnalyzer가 반환한 구간 dict
                     (transcript, suggested_title 포함)
        Returns:
            YouTube 영상 ID
        """
        metadata = self.generate_metadata(
            transcript=segment.get("transcript", ""),
            suggested_title=segment.get("suggested_title", ""),
        )

        return self.upload(
            video_path=video_path,
            title=metadata["title"],
            description=metadata.get("description", ""),
            tags=metadata.get("tags", []),
            privacy=privacy,
        )
