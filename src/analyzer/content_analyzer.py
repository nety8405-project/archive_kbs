"""
Content Analyzer 오케스트레이터.
Transcriber → SceneDetector → InterestScorer를 순서대로 실행합니다.
"""

import os
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.analyzer.transcriber import Transcriber
from src.analyzer.scene_detector import SceneDetector
from src.analyzer.interest_scorer import InterestScorer
from src.utils.database import AnalysisResult, get_session


class ContentAnalyzer:
    def __init__(
        self,
        whisper_model: str = "large-v3",
        scene_threshold: float = 27.0,
        min_score: int = 7,
        min_duration: float = 15.0,
        max_duration: float = 60.0,
    ):
        self.transcriber = Transcriber(model_size=whisper_model)
        self.scene_detector = SceneDetector(threshold=scene_threshold)
        self.scorer = InterestScorer()
        self.min_score = min_score
        self.min_duration = min_duration
        self.max_duration = max_duration

    def analyze(self, video_path: str | Path, archive_item_id: str) -> list[dict]:
        """
        영상을 분석하고, 흥미도 기준 이상인 구간을 DB에 저장해 반환합니다.

        Returns:
            흥미도 기준 이상인 구간 목록 (점수 내림차순)
        """
        video_path = Path(video_path)
        logger.info(f"분석 시작: {video_path.name} (ID: {archive_item_id})")

        # 1) 자막 추출
        transcript_segments = self.transcriber.transcribe(video_path)

        # 2) 장면 감지
        scenes = self.scene_detector.detect(video_path)

        # 장면 감지 결과가 없으면 30초 단위로 강제 분할
        if not scenes:
            logger.warning("장면 감지 결과 없음. 30초 단위로 분할합니다.")
            scenes = self._split_by_interval(video_path, interval=30)

        # 3) 흥미도 점수 계산
        scored = self.scorer.score_all(
            segments=scenes,
            transcript_map=transcript_segments,
            min_duration=self.min_duration,
            max_duration=self.max_duration,
        )

        # 4) 기준 점수 이상인 구간만 DB 저장
        high_scored = [s for s in scored if s["score"] >= self.min_score]
        self._save_to_db(archive_item_id, high_scored)

        logger.info(
            f"분석 완료: 전체 {len(scored)}개 구간 중 "
            f"기준({self.min_score}점) 이상 {len(high_scored)}개"
        )
        return high_scored

    def _split_by_interval(self, video_path: Path, interval: int = 30) -> list[dict]:
        """장면 감지 실패 시 일정 간격으로 강제 분할합니다."""
        import subprocess
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            capture_output=True, text=True,
        )
        try:
            total = float(result.stdout.strip())
        except ValueError:
            return []

        scenes = []
        t = 0.0
        while t < total:
            scenes.append({"start": t, "end": min(t + interval, total)})
            t += interval
        return scenes

    def _save_to_db(self, archive_item_id: str, segments: list[dict]) -> None:
        session = get_session()
        try:
            for seg in segments:
                row = AnalysisResult(
                    archive_item_id=archive_item_id,
                    start_time=seg["start"],
                    end_time=seg["end"],
                    transcript=seg.get("transcript", ""),
                    interest_score=seg["score"],
                    reason=seg.get("reason", ""),
                    analyzed_at=datetime.utcnow(),
                )
                session.add(row)
            session.commit()
        finally:
            session.close()
