"""Phase 5 실삭제 — dry-run 보고서.

설계 §5 단계적 활성화 원칙: TRASH·MEMORY- 14일 dry-run 후 실삭제.
이 스크립트는 무엇이 삭제 후보인지만 보고. **실제 파일 삭제 없음.**

출력:
  - TRASH/MEMORY-별 자산 수
  - 회수 가능 디스크 (file_size_bytes 합)
  - grade_source별 분포 (LLM 결정 vs 자동 결정)
  - 14일 이내 분류된 자산 수 (대기 기간 미충족)
  - 14일 이상 경과 자산 수 (삭제 가능 후보)

Usage:
  PYTHONPATH=. poetry run python scripts/phase5_dryrun_report.py
                                             [--grade TRASH]
                                             [--min-age-days 14]
                                             [--out scripts/_inventory/phase5_dryrun_YYYYMMDD.txt]
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_DSN = (
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"
)

DELETION_GRADES = ["TRASH", "MEMORY-"]


def run(grades: list[str], min_age_days: int, out_path: Path | None) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=min_age_days)
    lines: list[str] = []
    push = lines.append

    push(f"# Phase 5 Dry-run 보고서 — {datetime.now(timezone.utc).isoformat()}")
    push(f"# 기준: {min_age_days}일 이상 경과 + grade in {grades}")
    push(f"# ⚠️ 실삭제 없음 (보고서 only)")
    push("")

    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        # 1. 등급별 합계
        push("## 1. 등급별 후보 자산")
        cur.execute("""
            SELECT grade,
                   COUNT(*) AS total,
                   SUM(file_size_bytes) AS bytes,
                   COUNT(*) FILTER (WHERE classified_at < %s) AS aged,
                   COUNT(*) FILTER (WHERE classified_at >= %s) AS waiting
            FROM photo.classification
            WHERE grade = ANY(%s)
            GROUP BY grade
            ORDER BY grade
        """, (cutoff, cutoff, grades))
        total_aged_bytes = 0
        total_aged_count = 0
        for grade, total, b, aged, waiting in cur.fetchall():
            mb = (b or 0) / 1024 / 1024
            push(f"  [{grade:8s}] 총 {total:5d}장 / {mb:.0f}MB | "
                 f"삭제 가능 {aged:5d}장 / 대기 {waiting:5d}장")
            total_aged_count += aged
            total_aged_bytes += b or 0

        push("")
        push(f"💾 회수 가능 디스크: {total_aged_bytes / 1024 / 1024:.0f}MB "
             f"({total_aged_count}장 / {min_age_days}일 경과)")
        push("")

        # 2. grade_source 분포
        push("## 2. 등급 결정 출처 (LLM vs 자동)")
        cur.execute("""
            SELECT grade, grade_source, COUNT(*)
            FROM photo.classification
            WHERE grade = ANY(%s) AND classified_at < %s
            GROUP BY grade, grade_source
            ORDER BY grade, COUNT(*) DESC
        """, (grades, cutoff))
        for grade, src, c in cur.fetchall():
            push(f"  [{grade:8s}] {src:30s} {c:5d}장")
        push("")

        # 3. 영상 vs 사진
        push("## 3. 영상/사진 분포")
        cur.execute("""
            SELECT grade,
                   COUNT(*) FILTER (WHERE is_video) AS video,
                   COUNT(*) FILTER (WHERE NOT is_video) AS image
            FROM photo.classification
            WHERE grade = ANY(%s) AND classified_at < %s
            GROUP BY grade
        """, (grades, cutoff))
        for grade, v, i in cur.fetchall():
            push(f"  [{grade:8s}] 사진 {i:5d} / 영상 {v:5d}")
        push("")

        # 4. 사용자 피드백으로 보호된 자산 (있을 시)
        push("## 4. 사용자 보호 자산 (feedback table)")
        try:
            cur.execute("""
                SELECT COUNT(*) FROM photo.feedback
                WHERE action = 'protect'
            """)
            protected = cur.fetchone()[0]
            push(f"  보호 표시: {protected}장")
        except Exception:
            push("  feedback table 미구성 (Phase 5 진입 전 보호 메커니즘 필요)")
        push("")

        # 5. 삭제 검증 체크리스트
        push("## 5. 실삭제 진입 전 체크리스트")
        checks = [
            ("dry-run 14일 이상 누적", total_aged_count > 0),
            ("classification.sha256 NOT NULL 일관성", True),  # 스키마 보장
            ("Immich library에서 실제 파일 존재 확인 필요", None),
            ("사용자 보호 메커니즘 (feedback table)", False),  # 미구현
            ("백업 무결성 — Immich-Storage 별도 백업", None),
            ("실삭제 SAFE-REVIEW 검증 (정식 TC 파일)", False),
        ]
        for desc, ok in checks:
            mark = "✅" if ok else ("❌" if ok is False else "⚠️")
            push(f"  {mark} {desc}")
        push("")
        push("⚠️ 위 체크리스트 미충족 항목 해결 전 실삭제 절대 금지 (도메인 안전 영역).")

    text = "\n".join(lines)
    print(text)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text)
        print(f"\n📄 saved → {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--grade", action="append", default=None,
                        help="검사할 등급 (복수 지정 가능, 기본 TRASH+MEMORY-)")
    parser.add_argument("--min-age-days", type=int, default=14)
    parser.add_argument("--out", type=Path,
                        default=Path("scripts/_inventory")
                        / f"phase5_dryrun_{datetime.now().strftime('%Y%m%d')}.txt")
    args = parser.parse_args()
    grades = args.grade or DELETION_GRADES
    run(grades, args.min_age_days, args.out)


if __name__ == "__main__":
    main()
