"""음식 카테고리 분류 — LiteLLM 게이트웨이 통합.

설계 §15.G: FOOD 등급 자산을 한식/일식/중식/양식/디저트/기타로 분류.
v3.14: LiteLLM 게이트웨이 통합

플로우:
  1. vision_classify (photo/classify → Qwen VL 7B): 사진 → 음식 키워드
  2. text_generate (photo/text → Qwen 14B, 사진 X): 키워드 → 카테고리 정규화

사진은 절대 외부 전송 X (v3.12 정책 유지).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from core.client.llm_gateway import vision_classify, text_generate
from core.service.classifier import encode_image

load_dotenv()


KEYWORD_PROMPT = """이 사진의 음식을 한국어 키워드로 5단어 이내로 추출해.
예: "김치찌개와 밥", "스시 모듬", "초콜릿 케이크", "마라탕", "스테이크와 와인".
사람·장소 묘사 금지. 음식만.

JSON: {"keyword": "<음식 키워드>"}"""

CATEGORY_SYSTEM = """너는 음식 카테고리 분류기야. 음식 키워드를 받아 다음 6개 中 하나로 분류해:
- 한식: 김치/된장/비빔/한우/삼겹살 등 한국 음식
- 일식: 스시/라멘/돈카츠/우동/사시미 등 일본 음식
- 중식: 짜장/짬뽕/마라탕/딤섬/마파두부 등 중국 음식
- 양식: 파스타/피자/스테이크/햄버거 등 서양 음식
- 디저트: 케이크/아이스크림/빵/도넛/카페 음료 등
- 기타: 위에 명확히 속하지 않는 음식

JSON만: {"category": "<6개 中 하나>"}"""


@dataclass(slots=True)
class FoodMeta:
    keyword: str = ""
    category: str = ""


def extract_food_keyword(path: Path) -> str:
    img_b64 = encode_image(path)
    try:
        r = vision_classify(KEYWORD_PROMPT, "이 음식?", img_b64, max_tokens=64)
        return str(r.raw.get("keyword", "")).strip()[:100]
    except Exception:
        return ""


def categorize_keyword(keyword: str) -> str:
    if not keyword:
        return "기타"
    try:
        resp = text_generate(
            system=CATEGORY_SYSTEM,
            user=keyword,
            temperature=0.1, max_tokens=30,
        )
        cleaned = resp.text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned)
        cat = str(data.get("category", "")).strip()
        if cat in ("한식", "일식", "중식", "양식", "디저트", "기타"):
            return cat
    except Exception:
        pass
    return _fallback_category(keyword)


def _fallback_category(kw: str) -> str:
    kw_l = kw.lower()
    if any(k in kw for k in ["김치", "된장", "비빔", "삼겹", "한식", "한우", "전통"]):
        return "한식"
    if any(k in kw for k in ["스시", "라멘", "돈카츠", "사시미", "우동"]):
        return "일식"
    if any(k in kw for k in ["짜장", "짬뽕", "마라", "딤섬", "탕수육"]):
        return "중식"
    if any(k in kw for k in ["피자", "파스타", "스테이크", "햄버거", "샐러드"]):
        return "양식"
    if any(k in kw for k in ["케이크", "아이스크림", "빵", "도넛", "커피", "디저트"]):
        return "디저트"
    return "기타"


def categorize_food(path: Path) -> FoodMeta:
    """Qwen으로 키워드 추출 → Groq로 카테고리 정규화."""
    kw = extract_food_keyword(path)
    cat = categorize_keyword(kw) if kw else "기타"
    return FoodMeta(keyword=kw, category=cat)
