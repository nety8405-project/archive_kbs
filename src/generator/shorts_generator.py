"""
Shorts Generator.
분석된 구간을 ffmpeg로 잘라 9:16 세로형 쇼츠 영상으로 만듭니다.
"""

import os
import subprocess
from pathlib import Path

import ffmpeg
from loguru import logger


class ShortsGenerator:
    def __init__(
        self,
        output_dir: str = "data/shorts",
        target_width: int = 1080,
        target_height: int = 1920,
        font_path: str | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.target_width = target_width
        self.target_height = target_height
        # 자막 폰트 경로 (없으면 시스템 기본 폰트 사용)
        self.font_path = font_path or self._find_system_font()

    def _find_system_font(self) -> str:
        candidates = [
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "C:/Windows/Fonts/malgun.ttf",
        ]
        for path in candidates:
            if Path(path).exists():
                return path
        return ""

    def generate(
        self,
        source_path: str | Path,
        start: float,
        end: float,
        transcript: str = "",
        output_filename: str | None = None,
    ) -> Path:
        """
        소스 영상에서 start~end 구간을 잘라 세로형 쇼츠로 저장합니다.

        Args:
            source_path: 원본 영상 경로
            start: 시작 시각 (초)
            end: 끝 시각 (초)
            transcript: 하드코딩할 자막 텍스트
            output_filename: 저장 파일명 (None이면 자동 생성)

        Returns:
            저장된 쇼츠 파일 경로
        """
        source_path = Path(source_path)
        duration = end - start

        if not output_filename:
            stem = source_path.stem
            output_filename = f"{stem}_{int(start)}s_{int(end)}s.mp4"

        output_path = self.output_dir / output_filename
        if output_path.exists():
            logger.info(f"이미 존재하는 쇼츠, 건너뜀: {output_path}")
            return output_path

        logger.info(f"쇼츠 생성 중: {output_filename} ({start:.1f}s ~ {end:.1f}s)")

        # ffmpeg 필터 체인 구성
        # 1) 원본에서 구간 추출
        # 2) 세로형(9:16) 맞게 crop + scale
        # 3) 자막 오버레이

        vf_filters = self._build_video_filter(transcript)

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(source_path),
            "-t", str(duration),
            "-vf", vf_filters,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"ffmpeg 오류:\n{result.stderr}")
            raise RuntimeError(f"쇼츠 생성 실패: {output_filename}")

        logger.info(f"쇼츠 생성 완료: {output_path}")
        return output_path

    def _build_video_filter(self, transcript: str) -> str:
        """
        세로형 변환 + 자막 오버레이 필터를 반환합니다.
        원본이 16:9라고 가정하고, 위아래 여백을 검정으로 채웁니다.
        """
        w = self.target_width
        h = self.target_height

        # 원본 16:9를 9:16 안에 letterbox 방식으로 맞추기
        # scale 후 pad로 빈 공간 채우기
        scale_filter = (
            f"scale={w}:-2:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
        )

        if not transcript.strip():
            return scale_filter

        # 자막 하드코딩
        safe_text = transcript.replace("'", "\\'").replace(":", "\\:").replace("\\", "\\\\")
        font_setting = f":fontfile='{self.font_path}'" if self.font_path else ""
        subtitle_filter = (
            f"drawtext=text='{safe_text}'"
            f"{font_setting}"
            f":fontsize=40"
            f":fontcolor=white"
            f":borderw=2"
            f":bordercolor=black"
            f":x=(w-text_w)/2"
            f":y=h-100"
        )

        return f"{scale_filter},{subtitle_filter}"

    def generate_batch(
        self,
        source_path: str | Path,
        segments: list[dict],
        top_n: int = 3,
    ) -> list[Path]:
        """
        분석 결과 목록에서 상위 N개를 쇼츠로 만듭니다.

        Args:
            segments: ContentAnalyzer가 반환한 구간 목록 (score 내림차순 전제)
            top_n: 만들 쇼츠 개수
        """
        outputs = []
        for seg in segments[:top_n]:
            try:
                path = self.generate(
                    source_path=source_path,
                    start=seg["start"],
                    end=seg["end"],
                    transcript=seg.get("transcript", ""),
                )
                outputs.append(path)
            except Exception as e:
                logger.error(f"쇼츠 생성 실패: {e}")
        return outputs
