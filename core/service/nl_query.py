"""자연어 질의 → API 매핑 — Groq Llama-3.3-70B (텍스트 전용).

설계 §15.C: 사용자 자연어 질문 → Groq가 의도 파싱 → 적절한 API 호출 → 답변 생성.

지원 인텐트:
  count_by_grade  : "이번 주 EVENT 몇 장?" → photo.classification 통계
  cleanup_summary : "이번 달 정리한 사진?" → photo.cleanup_audit
  protected_count : "보호된 사진 몇 장?" → photo.feedback
  pending_status  : "분류 대기 중?" → process_pending 큐
  general          : 그 외 → 일반 응답

사진 데이터 절대 전송 X (사용자 정책 v3.12).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import psycopg
from dotenv import load_dotenv

from core.client.llm_gateway import text_generate

load_dotenv()


DB_DSN = os.getenv(
    "PHOTO_DB_DSN",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)

INTENT_SYSTEM = """너는 가족 사진 시스템의 자연어 질의 라우터야.
사용자 한국어 질문을 받아 다음 중 하나의 인텐트로 분류해.

인텐트 목록:
- count_by_grade: 등급별 사진 수 질문 (EVENT/BEST/MEMORY+/등 언급)
- cleanup_summary: 정리/삭제/회수 통계 질문
- protected_count: 보호 표시된 사진 질문
- pending_status: 분류 대기/진행 상황 질문
- general: 그 외

JSON만 출력:
{"intent": "<위 5개 中 하나>", "params": {"grade": "<등급명 또는 null>", "days": <기간일수 또는 null>}}"""

ANSWER_SYSTEM = """너는 가족 사진 시스템 운영 비서야.
사용자 질문 + 데이터를 받아 친근한 한국어 1~3문장으로 답변해.

규칙:
- 숫자 정확히 인용
- 이모지 1개 (📸 📊 🎉 ✅ 🛡 등) 허용
- 마크다운 *굵게* 가능
- 100자 이내"""


@dataclass(slots=True)
class QueryResult:
    intent: str
    answer: str
    data: dict


def parse_intent(question: str) -> dict:
    try:
        resp = text_generate(
            system=INTENT_SYSTEM,
            user=question,
            temperature=0.1, max_tokens=120,
        )
        cleaned = resp.text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except Exception:
        return {"intent": "general", "params": {}}


def fetch_data(intent: str, params: dict) -> dict:
    days = params.get("days") or 7
    grade = params.get("grade")

    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        if intent == "count_by_grade":
            cur.execute("""
                SELECT grade, COUNT(*),
                       COUNT(*) FILTER (WHERE classified_at > NOW() - (%s || ' days')::interval) AS recent
                FROM photo.classification GROUP BY grade
            """, (str(days),))
            rows = {g: {"total": t, "recent": r} for g, t, r in cur.fetchall()}
            if grade and grade.upper() in rows:
                return {"days": days, "grade": grade.upper(), **rows[grade.upper()]}
            return {"days": days, "by_grade": rows}

        if intent == "cleanup_summary":
            cur.execute("""
                SELECT device,
                       COUNT(*) FILTER (WHERE success) AS ok,
                       COUNT(*) FILTER (WHERE NOT success) AS fail,
                       COALESCE(SUM(reclaimed_bytes) FILTER (WHERE success), 0) AS bytes
                FROM photo.cleanup_audit
                WHERE reported_at > NOW() - (%s || ' days')::interval
                GROUP BY device
            """, (str(days),))
            rows = cur.fetchall()
            return {
                "days": days,
                "by_device": [
                    {"device": d, "ok": o, "fail": f, "reclaimed_mb": round(b / 1024 / 1024, 1)}
                    for d, o, f, b in rows
                ],
            }

        if intent == "protected_count":
            cur.execute("""
                SELECT COUNT(DISTINCT asset_id) FROM photo.feedback
                WHERE feedback_type = 'protect'
            """)
            return {"protected": cur.fetchone()[0]}

        if intent == "pending_status":
            cur.execute("SELECT COUNT(*) FROM photo.classification")
            return {"classified_total": cur.fetchone()[0]}

    return {}


def answer_question(question: str) -> QueryResult:
    parsed = parse_intent(question)
    intent = parsed.get("intent", "general")
    params = parsed.get("params", {}) or {}

    data = fetch_data(intent, params)

    try:
        resp = text_generate(
            system=ANSWER_SYSTEM,
            user=f"질문: {question}\n데이터: {json.dumps(data, ensure_ascii=False)}",
            temperature=0.4, max_tokens=200,
        )
        return QueryResult(intent=intent, answer=resp.text.strip(), data=data)
    except Exception:
        return QueryResult(intent=intent, answer=str(data), data=data)
