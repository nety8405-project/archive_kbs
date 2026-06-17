"""
사내 아카이브 서버 HTTP 클라이언트.
로그인 → 목록 조회 → 파일 다운로드를 담당합니다.

아카이브 서버의 실제 API 엔드포인트에 맞게
ENDPOINTS 딕셔너리와 파싱 로직을 수정하세요.
"""

import os
import time
from pathlib import Path
from typing import Optional

import requests
from loguru import logger
from tqdm import tqdm


ENDPOINTS = {
    "login":    "/api/auth/login",
    "list":     "/api/contents/list",
    "detail":   "/api/contents/{item_id}",
    "download": "/api/contents/{item_id}/download",
}


class ArchiveClient:
    def __init__(self):
        self.base_url = os.getenv("ARCHIVE_BASE_URL", "").rstrip("/")
        self.username = os.getenv("ARCHIVE_USERNAME", "")
        self.password = os.getenv("ARCHIVE_PASSWORD", "")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ArchivePipeline/1.0"})
        self._logged_in = False

    # ------------------------------------------------------------------
    # 인증
    # ------------------------------------------------------------------

    def login(self) -> None:
        """사내 계정으로 아카이브 서버에 로그인합니다."""
        url = self.base_url + ENDPOINTS["login"]
        payload = {"username": self.username, "password": self.password}

        resp = self.session.post(url, json=payload, timeout=15)
        resp.raise_for_status()

        data = resp.json()

        # 서버 응답 구조에 따라 아래 토큰 추출 방식을 수정하세요.
        token = data.get("token") or data.get("access_token")
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})

        self._logged_in = True
        logger.info(f"아카이브 서버 로그인 성공: {self.base_url}")

    def _ensure_logged_in(self) -> None:
        if not self._logged_in:
            self.login()

    # ------------------------------------------------------------------
    # 목록 조회
    # ------------------------------------------------------------------

    def fetch_list(
        self,
        page: int = 1,
        page_size: int = 20,
        category: Optional[str] = None,
        date_from: Optional[str] = None,   # "YYYY-MM-DD"
        date_to: Optional[str] = None,
    ) -> list[dict]:
        """아카이브 콘텐츠 목록을 가져옵니다."""
        self._ensure_logged_in()

        url = self.base_url + ENDPOINTS["list"]
        params = {"page": page, "pageSize": page_size}
        if category:
            params["category"] = category
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to

        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()

        data = resp.json()

        # 서버 응답 구조에 따라 아래 키를 수정하세요.
        items = data.get("items") or data.get("contents") or data.get("data") or []
        logger.info(f"목록 조회 완료: {len(items)}개 항목 (page={page})")
        return items

    def fetch_all(
        self,
        category: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        max_pages: int = 50,
    ) -> list[dict]:
        """전체 페이지를 순회하며 모든 항목을 가져옵니다."""
        all_items: list[dict] = []
        for page in range(1, max_pages + 1):
            items = self.fetch_list(page=page, category=category, date_from=date_from, date_to=date_to)
            if not items:
                break
            all_items.extend(items)
            logger.debug(f"페이지 {page} 완료, 누적 {len(all_items)}개")
            time.sleep(0.5)  # 서버 부하 방지
        return all_items

    def fetch_detail(self, item_id: str) -> dict:
        """특정 콘텐츠의 상세 정보를 가져옵니다."""
        self._ensure_logged_in()
        url = self.base_url + ENDPOINTS["detail"].format(item_id=item_id)
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # 파일 다운로드
    # ------------------------------------------------------------------

    def download(self, item_id: str, dest_dir: str = "data/downloads") -> Path:
        """
        아카이브 파일을 다운로드합니다.
        이미 존재하는 파일은 건너뜁니다.
        """
        self._ensure_logged_in()

        dest_path = Path(dest_dir)
        dest_path.mkdir(parents=True, exist_ok=True)

        detail = self.fetch_detail(item_id)

        # 서버 응답 구조에 따라 파일명/URL 키를 수정하세요.
        filename = detail.get("filename") or detail.get("file_name") or f"{item_id}.mp4"
        download_url = detail.get("download_url") or (
            self.base_url + ENDPOINTS["download"].format(item_id=item_id)
        )

        output_file = dest_path / filename
        if output_file.exists():
            logger.info(f"이미 존재하는 파일, 건너뜀: {output_file}")
            return output_file

        logger.info(f"다운로드 시작: {filename}")
        with self.session.get(download_url, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            with open(output_file, "wb") as f, tqdm(
                total=total,
                unit="B",
                unit_scale=True,
                desc=filename,
                ncols=80,
            ) as bar:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    bar.update(len(chunk))

        logger.info(f"다운로드 완료: {output_file}")
        return output_file
