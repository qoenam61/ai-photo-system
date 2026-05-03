"""Groq LPU 추론 클라이언트 — Vision + 텍스트.

설계: photo_system_design_v3.md §1 핵심 원칙 (v3.13: VISION_MODEL_CHAIN env로 동적 제어)
       §15 확장 활용 (앨범명·KPI·NL 질의 등 텍스트 작업)
       의사결정 #36~38 (v3.10)

사용처:
  - Vision 분류 (v3.13~): VISION_MODEL_CHAIN=groq,qwen 시 Groq 우선
  - §15.A 앨범 이름 자동 생성 (메타·태그만)
  - §15.B 주간 KPI 자연어 요약
  - §15.C Telegram 자연어 질의 (NL → API 매핑)
  - §15.D 사용자 피드백 분석
  - §15.G 음식 종류 분류

⚠️ PII (이름·주소) 전송 금지.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_VISION_MODEL = os.getenv(
    "GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"
)


class GroqRateLimitError(Exception):
    """Groq 429 또는 무료 한도 소진. retry_after 초 후 재시도 가능."""
    def __init__(self, retry_after: int = 60):
        super().__init__(f"Groq rate limited (retry after {retry_after}s)")
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class GroqResponse:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class GroqVisionResponse:
    grade: str
    confidence: int
    elapsed_ms: int
    raw: dict
    contains_child: bool = False


class GroqClient:
    """Groq 무료 LPU 추론.

    무료 한도: 30 RPM, 14400 RPD, 6000 tokens/req.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self._api_key = api_key or os.environ["GROQ_API_KEY"]
        self._model = model or os.getenv("GROQ_MODEL", DEFAULT_MODEL)

    def text(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        timeout: float = 30.0,
    ) -> GroqResponse:
        """단일 텍스트 완성 호출 (사진 데이터 절대 금지)."""
        import time

        # 보안 검증: base64 이미지 데이터 차단
        if any(marker in user for marker in ("data:image", "iVBOR", "/9j/")):
            raise ValueError(
                "Groq.text()에 이미지 데이터 전송 금지. "
                "Vision은 .vision() 메서드 사용 (사용자 명시 정책 변경 시만)."
            )

        return self._chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    def vision(
        self,
        system: str,
        user_text: str,
        image_b64: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 256,
        timeout: float = 30.0,
    ) -> GroqVisionResponse:
        """이미지 분류용 Vision 호출. v3.13: VISION_MODEL_CHAIN env 기반 활성.

        429/무료한도 → GroqRateLimitError. 호출자(VisionRouter)가 fallback 처리.
        응답 JSON: {"grade": "EVENT|BEST|FOOD|TRASH", "confidence": 1-10, "reason": "..."}
        """
        import json
        import time

        start = time.time()
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model or DEFAULT_VISION_MODEL,
                        "messages": [
                            {"role": "system", "content": system},
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": user_text},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{image_b64}"
                                        },
                                    },
                                ],
                            },
                        ],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "response_format": {"type": "json_object"},
                    },
                )
        except httpx.TimeoutException:
            raise GroqRateLimitError(retry_after=120) from None

        elapsed_ms = int((time.time() - start) * 1000)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("retry-after", "60"))
            raise GroqRateLimitError(retry_after=retry_after)
        resp.raise_for_status()

        body = resp.json()
        text = body["choices"][0]["message"]["content"]
        payload = _parse_json(text)
        return GroqVisionResponse(
            grade=str(payload.get("grade", "")).strip().upper(),
            confidence=int(payload.get("confidence", 0) or 0),
            elapsed_ms=elapsed_ms,
            raw=payload,
            contains_child=bool(payload.get("contains_child", False)),
        )

    def _chat(
        self,
        messages: list,
        *,
        temperature: float,
        max_tokens: int,
        timeout: float,
        model: str | None = None,
    ) -> GroqResponse:
        import time

        start = time.time()
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model or self._model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("retry-after", "60"))
            raise GroqRateLimitError(retry_after=retry_after)
        resp.raise_for_status()
        body = resp.json()
        elapsed_ms = int((time.time() - start) * 1000)

        return GroqResponse(
            text=body["choices"][0]["message"]["content"],
            model=body["model"],
            prompt_tokens=body["usage"]["prompt_tokens"],
            completion_tokens=body["usage"]["completion_tokens"],
            elapsed_ms=elapsed_ms,
        )


def _parse_json(text: str) -> dict:
    import json
    txt = text.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return {}
