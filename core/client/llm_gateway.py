"""core/client/llm_gateway.py — LiteLLM 통합 게이트웨이 (포토 시스템)

모든 AI 호출은 이 게이트웨이를 거친다.
- LiteLLM Proxy (localhost:4000) → Qwen VL 7B (vision) / Qwen 14B (text)
- 비전 fallback: photo/classify → photo/classify-fb (Groq Llama-4-Scout)
- LiteLLM 불가 시: fallback 결과 반환 (분류 중단 X)

역할 매핑:
  photo/classify    → Qwen VL 7B q4_K_M (로컬 vision)
  photo/classify-fb → Groq llama-4-scout (외부 vision fallback)
  photo/text        → Qwen 14B (로컬 text: 앨범명·KPI·NL 질의)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import httpx

LITELLM_BASE = os.getenv("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_KEY  = os.getenv("LITELLM_MASTER_KEY", "local-litellm-key")


# ── 응답 타입 (기존 QwenResponse / GroqVisionResponse 와 호환) ─────────────────

@dataclass(frozen=True, slots=True)
class VisionResponse:
    grade: str
    confidence: int
    elapsed_ms: int
    raw: dict
    contains_child: bool = False


@dataclass(frozen=True, slots=True)
class TextResponse:
    text: str
    model: str
    elapsed_ms: int


class LLMGatewayError(Exception):
    pass


# ── 공통 호출 헬퍼 ────────────────────────────────────────────────────────────

def _chat(
    role: str,
    messages: list[dict],
    *,
    temperature: float = 0.0,
    max_tokens: int = 256,
    timeout: float = 180.0,
) -> dict:
    start = time.time()
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            f"{LITELLM_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {LITELLM_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": role,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
    resp.raise_for_status()
    body = resp.json()
    body["_elapsed_ms"] = int((time.time() - start) * 1000)
    body["_model"] = body.get("model", role)
    return body


def _parse_json(raw: str) -> dict:
    txt = raw.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        # JSON 블록 추출 시도
        import re
        m = re.search(r"\{[\s\S]*\}", txt)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return {}


# ── Vision 분류 (photo/classify → photo/classify-fb fallback) ──────────────

def vision_classify(
    system: str,
    prompt: str,
    image_b64: str,
    *,
    timeout: float = 180.0,
    max_tokens: int = 128,
) -> VisionResponse:
    """사진 분류 Vision 호출. LiteLLM → Qwen VL 7B, fallback → Groq."""
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                },
            ],
        },
    ]

    # 1차: Qwen VL (로컬)
    try:
        body = _chat("photo/classify", messages, temperature=0.0, max_tokens=max_tokens, timeout=timeout)
        content = body["choices"][0]["message"]["content"]
        payload = _parse_json(content)
        return VisionResponse(
            grade=str(payload.get("grade", "")).strip(),
            confidence=int(payload.get("confidence", 0)),
            elapsed_ms=body["_elapsed_ms"],
            raw=payload,
            contains_child=bool(payload.get("contains_child", False)),
        )
    except Exception:
        pass

    # 2차 fallback: Groq (photo/classify-fb)
    try:
        body = _chat("photo/classify-fb", messages, temperature=0.0, max_tokens=max_tokens, timeout=30.0)
        content = body["choices"][0]["message"]["content"]
        payload = _parse_json(content)
        return VisionResponse(
            grade=str(payload.get("grade", "")).strip(),
            confidence=int(payload.get("confidence", 0)),
            elapsed_ms=body["_elapsed_ms"],
            raw=payload,
            contains_child=bool(payload.get("contains_child", False)),
        )
    except Exception as e:
        raise LLMGatewayError(f"vision_classify 완전 실패: {e}") from e


# ── 텍스트 생성 (photo/text → Qwen 14B) ────────────────────────────────────

def text_generate(
    system: str,
    user: str,
    *,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    timeout: float = 90.0,
) -> TextResponse:
    """텍스트 생성 (앨범명·KPI·NL 질의). 사진 base64 전송 금지."""
    # 보안: base64 이미지 데이터 차단 (Groq 정책 유지)
    if any(marker in user for marker in ("data:image", "iVBOR", "/9j/")):
        raise ValueError("text_generate에 이미지 데이터 전송 금지.")

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    body = _chat("photo/text", messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
    content = body["choices"][0]["message"]["content"]
    return TextResponse(
        text=content.strip(),
        model=body["_model"],
        elapsed_ms=body["_elapsed_ms"],
    )
