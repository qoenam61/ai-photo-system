"""Ollama Qwen2.5-VL 클라이언트 — 로컬 Vision 추론.

설계 §2 핵심 LLM (사진 외부 전송 X 원칙은 Qwen/로컬에서 보장).

설정:
  OLLAMA_URL  http://localhost:11434/api/generate (기본)
  OLLAMA_MODEL qwen2.5vl:7b-q4_K_M (기본)

Docker 컨테이너에서 호스트 Ollama 호출 시:
  OLLAMA_URL=http://host.docker.internal:11434/api/generate
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import httpx


DEFAULT_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5vl:7b-q4_K_M")


@dataclass(frozen=True, slots=True)
class QwenResponse:
    grade: str
    confidence: int
    elapsed_ms: int
    raw: dict
    contains_child: bool = False


class QwenClient:
    def __init__(self, url: str | None = None, model: str | None = None) -> None:
        self._url = url or DEFAULT_URL
        self._model = model or DEFAULT_MODEL

    def vision(
        self,
        system: str,
        prompt: str,
        image_b64: str,
        *,
        num_ctx: int = 2048,
        num_predict: int = 128,
        temperature: float = 0.0,
        keep_alive: str = "30m",
        timeout: float = 180.0,
    ) -> QwenResponse:
        start = time.time()
        with httpx.Client(timeout=timeout) as client:
            r = client.post(self._url, json={
                "model": self._model,
                "system": system,
                "prompt": prompt,
                "images": [image_b64],
                "stream": False,
                "format": "json",
                "options": {
                    "num_ctx": num_ctx,
                    "temperature": temperature,
                    "num_predict": num_predict,
                },
                "keep_alive": keep_alive,
            })
        elapsed = int((time.time() - start) * 1000)
        r.raise_for_status()
        body = r.json()
        payload = _safe_json(body.get("response", "{}"))
        return QwenResponse(
            grade=str(payload.get("grade", "")).strip(),
            confidence=int(payload.get("confidence", 0)),
            elapsed_ms=elapsed,
            raw=payload,
            contains_child=bool(payload.get("contains_child", False)),
        )


def _safe_json(text: str) -> dict:
    txt = text.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return {}
