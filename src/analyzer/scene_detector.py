"""
scenedetect를 사용해 영상의 장면 전환 지점을 탐지합니다.
"""

from pathlib import Path

from loguru import logger
from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector, AdaptiveDetector


class SceneDetector:
    def __init__(self, threshold: float = 27.0, adaptive: bool = False):
        """
        threshold: 장면 전환 민감도. 낮을수록 더 많이 감지.
        adaptive:  True면 AdaptiveDetector (동적 임계값), False면 ContentDetector.
        """
        self.threshold = threshold
        self.adaptive = adaptive

    def detect(self, video_path: str | Path) -> list[dict]:
        """
        장면 전환 구간 목록을 반환합니다.

        Returns:
            [
                {"start": 0.0, "end": 12.5},
                {"start": 12.5, "end": 34.0},
                ...
            ]
        """
        video_path = str(video_path)
        logger.info(f"장면 감지 시작: {Path(video_path).name}")

        video = open_video(video_path)
        scene_manager = SceneManager()

        if self.adaptive:
            scene_manager.add_detector(AdaptiveDetector())
        else:
            scene_manager.add_detector(ContentDetector(threshold=self.threshold))

        scene_manager.detect_scenes(video)
        scene_list = scene_manager.get_scene_list()

        scenes = [
            {
                "start": scene[0].get_seconds(),
                "end": scene[1].get_seconds(),
            }
            for scene in scene_list
        ]

        logger.info(f"장면 감지 완료: {len(scenes)}개 장면")
        return scenes
