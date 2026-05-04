"""dedup_demoted 자산 환원 — 그룹 보존 자산 grade로 복구.

사용자 명시 (2026-05-04): 결혼식/이벤트 자산이 dedup으로 TRASH 간 것을 환원.
같은 시각(±10초)+카메라 그룹의 보존 자산 grade로 복구.

Usage:
  PYTHONPATH=. poetry run python scripts/restore_dedup.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

import psycopg
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.pipeline.layer5_album import apply_grade_change  # noqa: E402

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)


def fetch_restoration_plan() -> list[tuple[str, str]]:
    """각 dedup_demoted 자산에 대해 같은 그룹의 보존 자산 grade 추론.

    Returns: [(asset_id, restored_grade)]
    """
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            WITH dedup AS (
              SELECT asset_id, exif_datetime, camera_make, camera_model
              FROM photo.classification
              WHERE grade='TRASH' AND grade_source='dedup_demoted'
            ),
            preserved AS (
              SELECT asset_id, exif_datetime, camera_make, camera_model, grade
              FROM photo.classification
              WHERE grade != 'TRASH' AND exif_datetime IS NOT NULL
            ),
            matched AS (
              SELECT DISTINCT ON (d.asset_id)
                d.asset_id,
                p.grade AS restored_grade,
                ABS(EXTRACT(EPOCH FROM (p.exif_datetime - d.exif_datetime))) AS sec_diff
              FROM dedup d
              JOIN preserved p
                ON ABS(EXTRACT(EPOCH FROM (p.exif_datetime - d.exif_datetime))) <= 10
               AND p.camera_make = d.camera_make
               AND p.camera_model = d.camera_model
              ORDER BY d.asset_id, sec_diff
            )
            SELECT asset_id::text, restored_grade FROM matched
        """)
        return cur.fetchall()


def fetch_unmatched() -> list[str]:
    """그룹 보존 자산 못 찾은 dedup 자산 (안전망)."""
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT asset_id::text FROM photo.classification d
            WHERE d.grade='TRASH' AND d.grade_source='dedup_demoted'
              AND NOT EXISTS (
                SELECT 1 FROM photo.classification p
                WHERE p.grade != 'TRASH'
                  AND ABS(EXTRACT(EPOCH FROM (p.exif_datetime - d.exif_datetime))) <= 10
                  AND p.camera_make = d.camera_make
                  AND p.camera_model = d.camera_model
              )
        """)
        return [r[0] for r in cur.fetchall()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    plan = fetch_restoration_plan()
    unmatched = fetch_unmatched()
    print(f"📊 dedup_demoted 환원 계획: {len(plan)}장 (매칭) + {len(unmatched)}장 (미매칭)")

    by_grade: Counter[str] = Counter()
    for _, g in plan:
        by_grade[g] += 1
    print("\n환원 grade 분포:")
    for g, c in by_grade.most_common():
        print(f"  → {g:8s}: {c}")
    if unmatched:
        print(f"\n⚠️  미매칭 {len(unmatched)}장 → MEMORY+로 보수 환원 (안전)")

    if args.dry_run:
        print("\n💡 dry-run — DB 변경 X")
        return

    # 매칭 환원
    print(f"\n🔧 환원 적용 + Layer 5 폴더 이동 ...")
    by_target: dict[str, list[str]] = {}
    for aid, g in plan:
        by_target.setdefault(g, []).append(aid)

    move_ok = move_fail = 0
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        for grade, aids in by_target.items():
            cur.execute("""
                UPDATE photo.classification
                SET grade = %s, grade_source = 'restored_from_dedup', updated_at = NOW()
                WHERE asset_id = ANY(%s::uuid[])
            """, (grade, aids))
            print(f"  → {grade:8s}: DB {cur.rowcount}장")
            for i, aid in enumerate(aids, 1):
                if i % 200 == 0:
                    print(f"    ... HDD move {i}/{len(aids)}")
                success, _ = apply_grade_change(aid, grade)
                if success:
                    move_ok += 1
                else:
                    move_fail += 1

        if unmatched:
            cur.execute("""
                UPDATE photo.classification
                SET grade = 'MEMORY+', grade_source = 'restored_from_dedup', updated_at = NOW()
                WHERE asset_id = ANY(%s::uuid[])
            """, (unmatched,))
            print(f"  → MEMORY+ (미매칭): DB {cur.rowcount}장")
            for aid in unmatched:
                success, _ = apply_grade_change(aid, "MEMORY+")
                if success:
                    move_ok += 1
                else:
                    move_fail += 1

    print(f"\n📊 결과: HDD move ok={move_ok} fail/skip={move_fail}")


if __name__ == "__main__":
    main()
