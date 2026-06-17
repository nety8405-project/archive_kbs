"""
Archive Shorts Pipeline - 메인 오케스트레이터

실행 예시:
  python main.py                          # 기본 실행 (최신 10개 처리)
  python main.py --limit 5               # 최대 5개 처리
  python main.py --date-from 2024-01-01  # 특정 날짜 이후 콘텐츠
  python main.py --skip-download         # 다운로드 건너뜀 (이미 받은 파일만 처리)
  python main.py --skip-upload           # 업로드 건너뜀 (로컬 저장만)
  python main.py --schedule              # 매일 오전 6시 자동 실행
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import schedule
import time as _time
from dotenv import load_dotenv
from loguru import logger

from src.utils.logger import setup_logger
from src.utils.network_guard import require_internal_network
from src.utils.database import get_session, ArchiveItem, AnalysisResult, ShortsItem
from src.downloader.download_manager import DownloadManager
from src.analyzer.content_analyzer import ContentAnalyzer
from src.generator.shorts_generator import ShortsGenerator
from src.uploader.youtube_uploader import YouTubeUploader


load_dotenv()
setup_logger()


def run_pipeline(
    limit: int = 10,
    date_from: str | None = None,
    date_to: str | None = None,
    category: str | None = None,
    top_n_shorts: int = 3,
    skip_download: bool = False,
    skip_upload: bool = False,
    youtube_privacy: str = "public",
) -> None:
    logger.info("=" * 60)
    logger.info("파이프라인 시작")
    logger.info(f"  limit={limit}, date_from={date_from}, skip_download={skip_download}, skip_upload={skip_upload}")
    logger.info("=" * 60)

    # 사내망 체크
    require_internal_network()

    # ------------------------------------------------------------------ #
    # STEP 1: 다운로드                                                     #
    # ------------------------------------------------------------------ #
    downloaded_paths: list[Path] = []

    if not skip_download:
        logger.info("[STEP 1] 아카이브 다운로드")
        manager = DownloadManager(download_dir=os.getenv("DOWNLOAD_DIR", "data/downloads"))
        downloaded_paths = manager.run(
            category=category,
            date_from=date_from,
            date_to=date_to,
            download_limit=limit,
        )
        logger.info(f"  → {len(downloaded_paths)}개 다운로드 완료")
    else:
        logger.info("[STEP 1] 다운로드 건너뜀. DB에서 기존 파일 로드.")
        session = get_session()
        try:
            rows = (
                session.query(ArchiveItem)
                .filter(ArchiveItem.downloaded == True)
                .limit(limit)
                .all()
            )
            downloaded_paths = [Path(r.local_path) for r in rows if r.local_path]
        finally:
            session.close()

    if not downloaded_paths:
        logger.warning("처리할 파일이 없습니다. 파이프라인 종료.")
        return

    # ------------------------------------------------------------------ #
    # STEP 2: 분석                                                         #
    # ------------------------------------------------------------------ #
    logger.info("[STEP 2] 콘텐츠 분석")
    analyzer = ContentAnalyzer(
        whisper_model=os.getenv("WHISPER_MODEL", "large-v3"),
        min_score=int(os.getenv("MIN_INTEREST_SCORE", "7")),
        min_duration=float(os.getenv("SHORTS_MIN_DURATION", "15")),
        max_duration=float(os.getenv("SHORTS_MAX_DURATION", "60")),
    )

    # archive_item_id를 로컬 경로로부터 역조회
    session = get_session()
    path_to_id: dict[str, str] = {}
    try:
        for row in session.query(ArchiveItem).filter(ArchiveItem.downloaded == True).all():
            if row.local_path:
                path_to_id[row.local_path] = row.id
    finally:
        session.close()

    all_segments: list[tuple[Path, dict]] = []   # (원본경로, 구간dict)
    for video_path in downloaded_paths:
        archive_id = path_to_id.get(str(video_path), video_path.stem)
        try:
            segments = analyzer.analyze(video_path, archive_item_id=archive_id)
            for seg in segments:
                all_segments.append((video_path, seg))
        except Exception as e:
            logger.error(f"분석 실패 [{video_path.name}]: {e}")

    logger.info(f"  → 총 {len(all_segments)}개 흥미 구간 발견")

    if not all_segments:
        logger.warning("쇼츠로 만들 구간이 없습니다. 파이프라인 종료.")
        return

    # 점수 내림차순 정렬 후 상위 N개 선택
    all_segments.sort(key=lambda x: x[1]["score"], reverse=True)
    top_segments = all_segments[:top_n_shorts]

    # ------------------------------------------------------------------ #
    # STEP 3: 쇼츠 생성                                                   #
    # ------------------------------------------------------------------ #
    logger.info(f"[STEP 3] 쇼츠 생성 (상위 {len(top_segments)}개)")
    generator = ShortsGenerator(output_dir=os.getenv("SHORTS_DIR", "data/shorts"))
    session = get_session()

    shorts_queue: list[tuple[Path, dict]] = []   # (쇼츠경로, 구간dict)
    try:
        for video_path, seg in top_segments:
            try:
                shorts_path = generator.generate(
                    source_path=video_path,
                    start=seg["start"],
                    end=seg["end"],
                    transcript=seg.get("transcript", ""),
                )

                # DB에서 분석결과 ID 조회
                archive_id = path_to_id.get(str(video_path), video_path.stem)
                analysis_row = (
                    session.query(AnalysisResult)
                    .filter(
                        AnalysisResult.archive_item_id == archive_id,
                        AnalysisResult.start_time == seg["start"],
                    )
                    .first()
                )
                analysis_id = analysis_row.id if analysis_row else 0

                shorts_row = ShortsItem(
                    analysis_result_id=analysis_id,
                    archive_item_id=archive_id,
                    local_path=str(shorts_path),
                    title=seg.get("suggested_title", ""),
                    created_at=datetime.utcnow(),
                )
                session.add(shorts_row)
                session.commit()
                shorts_queue.append((shorts_path, seg))
            except Exception as e:
                logger.error(f"쇼츠 생성 실패: {e}")
    finally:
        session.close()

    logger.info(f"  → {len(shorts_queue)}개 쇼츠 생성 완료")

    # ------------------------------------------------------------------ #
    # STEP 4: YouTube 업로드                                              #
    # ------------------------------------------------------------------ #
    if skip_upload:
        logger.info("[STEP 4] 업로드 건너뜀. 쇼츠는 data/shorts/ 에 저장됨.")
        return

    logger.info("[STEP 4] YouTube 업로드")
    uploader = YouTubeUploader()
    session = get_session()

    try:
        for shorts_path, seg in shorts_queue:
            try:
                video_id = uploader.upload_with_auto_metadata(
                    video_path=shorts_path,
                    segment=seg,
                    privacy=youtube_privacy,
                )
                # DB 업로드 상태 갱신
                row = (
                    session.query(ShortsItem)
                    .filter(ShortsItem.local_path == str(shorts_path))
                    .first()
                )
                if row:
                    row.uploaded = True
                    row.youtube_video_id = video_id
                    row.uploaded_at = datetime.utcnow()
                    session.commit()
            except Exception as e:
                logger.error(f"업로드 실패 [{shorts_path.name}]: {e}")
    finally:
        session.close()

    logger.info("=" * 60)
    logger.info("파이프라인 완료")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Archive Shorts 자동화 파이프라인")
    parser.add_argument("--limit", type=int, default=10, help="처리할 최대 영상 수")
    parser.add_argument("--top-n", type=int, default=3, help="영상당 쇼츠 최대 개수")
    parser.add_argument("--date-from", type=str, default=None, help="기준 시작일 (YYYY-MM-DD)")
    parser.add_argument("--date-to", type=str, default=None, help="기준 종료일 (YYYY-MM-DD)")
    parser.add_argument("--category", type=str, default=None, help="아카이브 카테고리 필터")
    parser.add_argument("--privacy", type=str, default="public", choices=["public", "unlisted", "private"])
    parser.add_argument("--skip-download", action="store_true", help="다운로드 단계 건너뜀")
    parser.add_argument("--skip-upload", action="store_true", help="YouTube 업로드 건너뜀")
    parser.add_argument("--schedule", action="store_true", help="매일 오전 6시 자동 실행 모드")
    args = parser.parse_args()

    kwargs = {
        "limit": args.limit,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "category": args.category,
        "top_n_shorts": args.top_n,
        "skip_download": args.skip_download,
        "skip_upload": args.skip_upload,
        "youtube_privacy": args.privacy,
    }

    if args.schedule:
        logger.info("스케줄 모드 시작: 매일 오전 06:00 실행")
        schedule.every().day.at("06:00").do(run_pipeline, **kwargs)
        while True:
            schedule.run_pending()
            _time.sleep(60)
    else:
        run_pipeline(**kwargs)


if __name__ == "__main__":
    main()
