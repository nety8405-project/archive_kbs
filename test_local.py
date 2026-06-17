"""
로컬 영상 파일로 파이프라인을 테스트하는 스크립트.
아카이브 다운로드 / YouTube 업로드 없이
  분석 → 쇼츠 생성 만 실행합니다.

실행 예시:
  python test_local.py                                   # 기본 테스트 영상 사용
  python test_local.py --video path/to/your_video.mp4   # 임의 영상 지정
  python test_local.py --no-gpt                         # GPT 없이 장면만 잘라서 저장
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── 로거 먼저 설정 ──────────────────────────────────────────────────────
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}", level="INFO", colorize=True)
logger.add("logs/test_local.log", rotation="5 MB", level="DEBUG", encoding="utf-8")

Path("logs").mkdir(exist_ok=True)
Path("data/shorts").mkdir(parents=True, exist_ok=True)


def run_test(video_path: str, use_gpt: bool = True, top_n: int = 3) -> None:

    video = Path(video_path)
    if not video.exists():
        logger.error(f"파일이 없습니다: {video}")
        sys.exit(1)

    logger.info(f"테스트 시작: {video.name}")
    logger.info(f"  GPT 흥미도 분석: {'ON' if use_gpt else 'OFF (장면만 자르기)'}")
    logger.info(f"  생성할 쇼츠 최대 개수: {top_n}")

    # ── STEP 1: 장면 감지 ───────────────────────────────────────────────
    logger.info("[1/3] 장면 감지 중...")
    from src.analyzer.scene_detector import SceneDetector

    detector = SceneDetector(threshold=20.0)
    scenes = detector.detect(video)

    if not scenes:
        logger.warning("장면 감지 결과 없음 → 30초 단위로 강제 분할")
        import subprocess
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            capture_output=True, text=True,
        )
        total = float(r.stdout.strip())
        scenes = [{"start": t, "end": min(t + 30, total)} for t in range(0, int(total), 30)]

    logger.info(f"  → {len(scenes)}개 장면 감지")
    for i, s in enumerate(scenes):
        logger.info(f"     장면 {i+1}: {s['start']:.1f}s ~ {s['end']:.1f}s ({s['end']-s['start']:.1f}초)")

    # ── STEP 2: 흥미도 점수 (GPT) 또는 더미 점수 ───────────────────────
    logger.info("[2/3] 흥미도 분석 중...")

    valid_scenes = [s for s in scenes if 10 <= (s["end"] - s["start"]) <= 90]

    if not valid_scenes:
        valid_scenes = scenes  # 길이 조건 완화

    if use_gpt and os.getenv("OPENAI_API_KEY"):
        from src.analyzer.interest_scorer import InterestScorer
        scorer = InterestScorer()
        scored = []
        for i, scene in enumerate(valid_scenes):
            logger.info(f"  GPT 평가 중... ({i+1}/{len(valid_scenes)})")
            result = scorer.score_segment(
                start=scene["start"],
                end=scene["end"],
                transcript=f"테스트 장면 {i+1} 구간",
            )
            scored.append({**scene, **result, "transcript": f"테스트 장면 {i+1}"})
        scored.sort(key=lambda x: x["score"], reverse=True)
    else:
        if use_gpt and not os.getenv("OPENAI_API_KEY"):
            logger.warning("OPENAI_API_KEY 없음 → 더미 점수로 대체")
        import random
        scored = [
            {
                **scene,
                "score": random.randint(5, 10),
                "reason": "더미 점수 (GPT 미사용)",
                "suggested_title": f"하이라이트 클립 {i+1}",
                "transcript": f"테스트 장면 {i+1}",
            }
            for i, scene in enumerate(valid_scenes)
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)

    logger.info("  흥미도 점수 결과:")
    for i, s in enumerate(scored):
        logger.info(f"     {i+1}위: {s['start']:.1f}s~{s['end']:.1f}s  점수={s['score']}  {s.get('reason','')[:40]}")

    # ── STEP 3: 쇼츠 생성 ───────────────────────────────────────────────
    logger.info(f"[3/3] 상위 {min(top_n, len(scored))}개 쇼츠 생성 중...")
    from src.generator.shorts_generator import ShortsGenerator

    generator = ShortsGenerator(output_dir="data/shorts")
    output_paths = []

    for rank, seg in enumerate(scored[:top_n], start=1):
        try:
            out = generator.generate(
                source_path=video,
                start=seg["start"],
                end=seg["end"],
                transcript=seg.get("transcript", ""),
                output_filename=f"{video.stem}_shorts_{rank}위_{int(seg['score'])}점.mp4",
            )
            output_paths.append(out)
            logger.info(f"  ✓ 쇼츠 {rank}위 저장: {out}")
        except Exception as e:
            logger.error(f"  ✗ 쇼츠 {rank}위 생성 실패: {e}")

    # ── 결과 요약 ────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 50)
    logger.info("테스트 완료")
    logger.info(f"  생성된 쇼츠: {len(output_paths)}개")
    for p in output_paths:
        size = p.stat().st_size // 1024
        logger.info(f"  → {p}  ({size}KB)")

    result = {
        "input": str(video),
        "scenes_detected": len(scenes),
        "shorts_created": len(output_paths),
        "outputs": [str(p) for p in output_paths],
        "top_segments": [
            {
                "rank": i + 1,
                "start": s["start"],
                "end": s["end"],
                "score": s["score"],
                "reason": s.get("reason", ""),
            }
            for i, s in enumerate(scored[:top_n])
        ],
    }

    result_path = Path("data/test_result.json")
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    logger.info(f"  결과 JSON: {result_path}")
    logger.info("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="로컬 영상 파이프라인 테스트")
    parser.add_argument(
        "--video",
        default="data/downloads/test_long.mp4",
        help="테스트할 영상 파일 경로 (기본: data/downloads/test_long.mp4)",
    )
    parser.add_argument(
        "--no-gpt",
        action="store_true",
        help="GPT 흥미도 분석 없이 장면만 잘라 쇼츠 생성",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=3,
        help="생성할 쇼츠 개수 (기본: 3)",
    )
    args = parser.parse_args()

    run_test(
        video_path=args.video,
        use_gpt=not args.no_gpt,
        top_n=args.top_n,
    )


if __name__ == "__main__":
    main()
