"""앨범명 자동 생성 — Qwen 14B via LiteLLM (텍스트 전용).

설계 §15.A: 메타데이터(연도, 행사 종류, 위치, 인물 수) → 자연스러운 한국어 앨범명.
**사진 데이터 절대 전송 금지** — 메타·태그·통계만.
v3.14: LiteLLM 게이트웨이 통합 (photo/text → Qwen 14B)

Usage:
  from core.service.album_namer import suggest_album_name
  name = suggest_album_name(year=2022, event_kind='결혼식', count=2028)
"""

from __future__ import annotations

import json

from dotenv import load_dotenv

from core.client.llm_gateway import text_generate

load_dotenv()


SYSTEM_PROMPT = """너는 가족 사진 앨범 이름을 짓는 한국어 작명가야.

규칙:
1. 한국어로 자연스럽고 따뜻한 이름 (5~25자)
2. 연도, 계절, 행사, 장소, 추억 키워드 활용
3. 이모지 사용 금지
4. 따옴표·괄호·특수문자 금지
5. JSON만 출력: {"name": "<앨범명>"}"""


def suggest_album_name(
    *,
    year: int | None = None,
    season: str | None = None,
    event_kind: str | None = None,
    location: str | None = None,
    count: int | None = None,
    keywords: list[str] | None = None,
    folder_hint: str | None = None,
) -> str:
    """메타로부터 앨범명 추천.

    실패 시 폴백 (LLM 호출 실패) — 메타 기반 단순 조합.
    """
    payload = {
        "year": year, "season": season, "event_kind": event_kind,
        "location": location, "count": count,
        "keywords": keywords or [],
        "folder_hint": folder_hint,
    }
    user_text = (
        "다음 메타로 앨범명을 지어줘 (텍스트만, 사진 없음):\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )

    try:
        resp = text_generate(
            system=SYSTEM_PROMPT, user=user_text,
            temperature=0.4, max_tokens=80,
        )
        cleaned = resp.text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned)
        name = str(data.get("name", "")).strip()
        if 3 <= len(name) <= 30:
            return name
    except Exception:
        pass
    return _fallback(payload)


def _fallback(meta: dict) -> str:
    parts: list[str] = []
    if meta.get("year"):
        parts.append(f"{meta['year']}")
    if meta.get("season"):
        parts.append(meta["season"])
    if meta.get("event_kind"):
        parts.append(meta["event_kind"])
    elif meta.get("location"):
        parts.append(meta["location"])
    parts.append("추억")
    return " ".join(parts) if parts else "추억"
