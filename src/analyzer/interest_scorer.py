"""
GPT-4o를 사용해 각 장면 구간의 흥미도를 평가합니다.
"""

import json
import os

from loguru import logger
from openai import OpenAI


SCORING_PROMPT = """
당신은 방송 콘텐츠 편집 전문가입니다.
아래는 영상의 특정 구간(시작~끝)에서 추출한 대본입니다.

구간 정보:
- 시작: {start:.1f}초
- 끝: {end:.1f}초
- 길이: {duration:.1f}초
- 대본: "{transcript}"

이 구간이 유튜브 쇼츠로 만들었을 때 얼마나 흥미로울지 평가해 주세요.

평가 기준:
1. 반전이나 예상 밖의 발언이 있는가
2. 웃음 포인트가 있는가
3. 핵심 정보나 인상적인 발언이 있는가
4. 감정적 반응을 유발하는 내용인가
5. 독립적으로 봐도 이해가 되는가 (컨텍스트 없이도)

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "score": <1~10 사이 정수>,
  "reason": "<점수 이유를 한국어로 1~2문장>",
  "suggested_title": "<쇼츠 제목 추천 (30자 이내)>"
}}
"""


class InterestScorer:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def score_segment(
        self,
        start: float,
        end: float,
        transcript: str,
    ) -> dict:
        """
        단일 구간의 흥미도를 평가합니다.

        Returns:
            {"score": 8, "reason": "...", "suggested_title": "..."}
        """
        if not transcript.strip():
            return {"score": 1, "reason": "대본 없음", "suggested_title": ""}

        prompt = SCORING_PROMPT.format(
            start=start,
            end=end,
            duration=end - start,
            transcript=transcript,
        )

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            result = json.loads(response.choices[0].message.content)
            result["score"] = int(result.get("score", 1))
            return result
        except Exception as e:
            logger.error(f"GPT 평가 실패 ({start:.1f}s~{end:.1f}s): {e}")
            return {"score": 1, "reason": f"평가 실패: {e}", "suggested_title": ""}

    def score_all(
        self,
        segments: list[dict],
        transcript_map: list[dict],
        min_duration: float = 10.0,
        max_duration: float = 90.0,
    ) -> list[dict]:
        """
        장면 목록 전체를 평가합니다.

        Args:
            segments: SceneDetector가 반환한 장면 목록
            transcript_map: Transcriber가 반환한 자막 세그먼트 목록
            min_duration: 이 길이 미만인 장면은 제외
            max_duration: 이 길이 초과인 장면은 제외

        Returns:
            score가 포함된 장면 목록 (점수 내림차순 정렬)
        """
        results = []

        for i, scene in enumerate(segments):
            duration = scene["end"] - scene["start"]
            if not (min_duration <= duration <= max_duration):
                logger.debug(f"구간 {i+1} 길이 제외: {duration:.1f}s")
                continue

            # 해당 구간에 겹치는 자막 세그먼트 수집
            transcript = " ".join(
                t["text"]
                for t in transcript_map
                if t["start"] >= scene["start"] and t["end"] <= scene["end"]
            )

            logger.info(f"구간 {i+1}/{len(segments)} 평가 중 ({scene['start']:.1f}s ~ {scene['end']:.1f}s)")
            score_result = self.score_segment(scene["start"], scene["end"], transcript)

            results.append({
                "start": scene["start"],
                "end": scene["end"],
                "duration": duration,
                "transcript": transcript,
                "score": score_result["score"],
                "reason": score_result.get("reason", ""),
                "suggested_title": score_result.get("suggested_title", ""),
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        logger.info(f"전체 {len(results)}개 구간 평가 완료")
        return results
