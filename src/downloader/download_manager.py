"""
다운로드 매니저.
아카이브 목록을 DB와 비교해 신규 항목만 다운로드하고 상태를 기록합니다.
"""

from datetime import datetime
from pathlib import Path

from loguru import logger

from src.downloader.archive_client import ArchiveClient
from src.utils.database import ArchiveItem, get_session


class DownloadManager:
    def __init__(self, download_dir: str = "data/downloads"):
        self.client = ArchiveClient()
        self.download_dir = download_dir

    def _item_from_raw(self, raw: dict) -> ArchiveItem:
        """API 응답 딕셔너리를 ArchiveItem 모델로 변환합니다."""
        # 서버 응답 필드명에 맞게 키를 수정하세요.
        return ArchiveItem(
            id=str(raw.get("id") or raw.get("content_id") or raw.get("itemId")),
            title=raw.get("title") or raw.get("name") or "제목없음",
            url=raw.get("url") or raw.get("stream_url") or "",
            duration=raw.get("duration") or raw.get("playtime"),
            broadcast_date=raw.get("broadcast_date") or raw.get("aired_at") or raw.get("date"),
        )

    def sync_list(
        self,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> int:
        """아카이브 목록을 DB에 동기화하고, 신규 항목 수를 반환합니다."""
        raw_items = self.client.fetch_all(category=category, date_from=date_from, date_to=date_to)
        session = get_session()
        new_count = 0

        try:
            for raw in raw_items:
                item = self._item_from_raw(raw)
                if not item.id:
                    continue
                exists = session.get(ArchiveItem, item.id)
                if not exists:
                    session.add(item)
                    new_count += 1
            session.commit()
        finally:
            session.close()

        logger.info(f"목록 동기화 완료: 신규 {new_count}개 / 전체 {len(raw_items)}개")
        return new_count

    def download_pending(self, limit: int = 10) -> list[Path]:
        """다운로드되지 않은 항목을 순서대로 다운로드합니다."""
        session = get_session()
        downloaded_paths: list[Path] = []

        try:
            pending = (
                session.query(ArchiveItem)
                .filter(ArchiveItem.downloaded == False)
                .limit(limit)
                .all()
            )
            logger.info(f"미다운로드 항목: {len(pending)}개")

            for item in pending:
                try:
                    path = self.client.download(item.id, dest_dir=self.download_dir)
                    item.downloaded = True
                    item.local_path = str(path)
                    item.downloaded_at = datetime.utcnow()
                    session.commit()
                    downloaded_paths.append(path)
                except Exception as e:
                    logger.error(f"다운로드 실패 [{item.id}] {item.title}: {e}")
                    session.rollback()
        finally:
            session.close()

        return downloaded_paths

    def run(
        self,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        download_limit: int = 10,
    ) -> list[Path]:
        """목록 동기화 → 신규 항목 다운로드 순서로 실행합니다."""
        self.sync_list(category=category, date_from=date_from, date_to=date_to)
        return self.download_pending(limit=download_limit)
