"""주간 KPI 요약 — Groq Llama-3.3-70B 텍스트 (사진 X).

설계 §15.B: 일요일 09:00 cron → 지난주 통계 → Groq 자연어 요약 → Telegram 발송.

전송 데이터: 메타·통계만 (사진 base64 절대 X — groq_client.text가 차단).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict

import psycopg
from dotenv import load_dotenv

from core.client.llm_gateway import text_generate

load_dotenv()


SYSTEM = """너는 가족 사진 자동화 시스템 운영 관리자야.
주간 통계를 받아서 친근하고 자연스러운 한국어 1~2문단 요약을 작성해.

규칙:
- 숫자는 정확히 인용
- 변화 추이 강조 (전주 대비, 누적)
- 이모지 1~2개 허용 (📸 📊 🎉 등)
- 마크다운 굵은체 (*글자*) 사용 가능 (Telegram MarkdownV2 X — 일반 *)
- 100~300자
- 추천 행동 (Phase 진행, 보호 표시 권장 등) 1줄 포함"""


DB_DSN = os.getenv(
    "PHOTO_DB_DSN",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)


@dataclass
class WeeklyStats:
    week_start: str
    classified_d7: int
    classified_total: int
    by_grade_d7: dict[str, int]
    by_grade_total: dict[str, int]
    pending: int
    cleanup_d7: dict[str, int]  # device → count
    cleanup_failures_d7: dict[str, int]  # reason_category → count (2026-05-08 P1-G)
    reclaimed_mb_d7: float
    protected: int
    phase5_ready: bool
    # 2026-05-08 P1-F: 모델 라우팅 분포 — Groq/Qwen/ensemble/auto_fallback 비율
    routing_d7: dict[str, int]


def collect_stats() -> WeeklyStats:
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT MIN(classified_at)::date::text FROM photo.classification
            WHERE classified_at > NOW() - INTERVAL '7 days'
        """)
        week_start = cur.fetchone()[0] or ""

        cur.execute("""
            SELECT COUNT(*) FROM photo.classification
            WHERE classified_at > NOW() - INTERVAL '7 days'
        """)
        d7 = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM photo.classification")
        total = cur.fetchone()[0]

        cur.execute("""
            SELECT grade, COUNT(*) FROM photo.classification
            WHERE classified_at > NOW() - INTERVAL '7 days'
            GROUP BY grade
        """)
        by_grade_d7 = {g: c for g, c in cur.fetchall()}

        cur.execute("""
            SELECT grade, COUNT(*) FROM photo.classification GROUP BY grade
        """)
        by_grade_total = {g: c for g, c in cur.fetchall()}

        cur.execute("""
            SELECT device,
                   COUNT(*) FILTER (WHERE success) AS ok,
                   COALESCE(SUM(reclaimed_bytes) FILTER (WHERE success), 0) AS bytes
            FROM photo.cleanup_audit
            WHERE reported_at > NOW() - INTERVAL '7 days'
            GROUP BY device
        """)
        cleanup_d7: dict[str, int] = {}
        reclaimed = 0
        for d, ok, b in cur.fetchall():
            cleanup_d7[d] = ok
            reclaimed += int(b or 0)

        cur.execute("""
            SELECT COUNT(DISTINCT asset_id) FROM photo.feedback
            WHERE feedback_type = 'protect'
        """)
        protected = cur.fetchone()[0]

        # 2026-05-08 P1-G: cleanup 실패 카테고리 분포 (reason_category 기반)
        cur.execute("""
            SELECT reason_category, COUNT(*) FROM photo.cleanup_audit
            WHERE reported_at > NOW() - INTERVAL '7 days' AND NOT success
            GROUP BY reason_category ORDER BY 2 DESC
        """)
        cleanup_failures_d7 = {c: n for c, n in cur.fetchall()}

        # 2026-05-08 P1-F: 모델 라우팅 — Groq vs Qwen vs ensemble 분포
        cur.execute("""
            SELECT
              SUM(CASE WHEN grade_source = 'llm_groq' THEN 1 ELSE 0 END) AS groq,
              SUM(CASE WHEN grade_source = 'llm_qwen' THEN 1 ELSE 0 END) AS qwen,
              SUM(CASE WHEN grade_source = 'llm_ensemble' THEN 1 ELSE 0 END) AS ensemble,
              SUM(CASE WHEN grade_source LIKE 'llm_corrected%' THEN 1 ELSE 0 END) AS corrected,
              SUM(CASE WHEN grade_source LIKE 'auto_%' THEN 1 ELSE 0 END) AS auto_fallback
            FROM photo.classification
            WHERE classified_at > NOW() - INTERVAL '7 days'
        """)
        g, q, e, c, a = cur.fetchone()
        routing_d7 = {
            "groq": g or 0, "qwen": q or 0, "ensemble": e or 0,
            "corrected": c or 0, "auto_fallback": a or 0,
        }

    from pathlib import Path
    flag = Path(__file__).parent.parent.parent / "scripts" / "_inventory" / "phase5_ready.flag"

    return WeeklyStats(
        week_start=week_start,
        classified_d7=d7,
        classified_total=total,
        by_grade_d7=by_grade_d7,
        by_grade_total=by_grade_total,
        pending=0,  # 별도 조회는 비싸므로 생략
        cleanup_d7=cleanup_d7,
        cleanup_failures_d7=cleanup_failures_d7,
        reclaimed_mb_d7=round(reclaimed / 1024 / 1024, 1),
        protected=protected,
        phase5_ready=flag.exists(),
        routing_d7=routing_d7,
    )


def summarize(stats: WeeklyStats) -> str:
    """Qwen 14B via LiteLLM 텍스트 요약. 실패 시 폴백 (단순 포맷)."""
    try:
        user = (
            "다음 주간 통계를 한국어로 요약해줘 (사진 데이터 없음, 통계 메타만):\n"
            + json.dumps(asdict(stats), ensure_ascii=False, indent=2)
        )
        resp = text_generate(system=SYSTEM, user=user, temperature=0.5, max_tokens=300)
        text = resp.text.strip()
        if 50 <= len(text) <= 600:
            return text
    except Exception:
        pass
    return _fallback(stats)


def _fallback(s: WeeklyStats) -> str:
    grades_str = ", ".join(f"{g} {c}" for g, c in sorted(s.by_grade_d7.items()))
    cleanup_str = (
        ", ".join(f"{d} {c}" for d, c in s.cleanup_d7.items()) or "없음"
    )
    return (
        f"📸 *주간 KPI ({s.week_start} ~)*\n"
        f"분류: {s.classified_d7}장 (누적 {s.classified_total})\n"
        f"등급: {grades_str}\n"
        f"정리: {cleanup_str} / 회수 {s.reclaimed_mb_d7}MB\n"
        f"보호: {s.protected}건\n"
        f"Phase 5: {'활성' if s.phase5_ready else '대기'}"
    )
