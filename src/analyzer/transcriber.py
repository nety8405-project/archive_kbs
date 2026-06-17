"""
Whisper를 사용해 영상에서 자막(타임코드 포함)을 추출합니다.
"""

import os
from pathlib import Path
from typing import Optional

import whisper
from loguru import logger


class Transcriber:
    def __init__(self, model_size: str = "large-v3"):
        """
        model_size: tiny / base / small / medium / large-v3
        GPU가 없으면 small 또는 medium 권장.
        """
        logger.info(f"Whisper 모델 로딩 중: {model_size}")
        self.model = whisper.load_model(model_size)
        logger.info("Whisper 모델 로딩 완료")

    def transcribe(self, video_path: str | Path, language: str = "ko") -> list[dict]:
        """
        영상을 받아 타임코드가 포함된 자막 세그먼트 목록을 반환합니다.

        Returns:
            [
                {"start": 0.0, "end": 3.2, "text": "안녕하세요"},
                ...
            ]
        """
        video_path = str(video_path)
        logger.info(f"자막 추출 시작: {Path(video_path).name}")

        result = self.model.transcribe(
            video_path,
            language=language,
            task="transcribe",
            verbose=False,
            word_timestamps=True,
        )

        segments = [
            {
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"].strip(),
            }
            for seg in result["segments"]
        ]

        logger.info(f"자막 추출 완료: {len(segments)}개 세그먼트")
        return segments

    def segments_to_text(self, segments: list[dict]) -> str:
        """세그먼트 목록을 하나의 전문(全文) 텍스트로 합칩니다."""
        return " ".join(s["text"] for s in segments)
