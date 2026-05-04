"""유사컷 강등 — EXIF 시각 ±10초 + 카메라 동일 그룹화.

설계 §4 + 사용자 명시 정책 (2026-05-04):
  모든 등급(TRASH 제외) 그룹 내 최고 quality 1개만 보존, 나머지 → TRASH 직접.

  대상 등급: EVENT, EVENT-L, BEST, FOOD, MEMORY+, MEMORY-, NORMAL
  → TRASH (grade_source='dedup_demoted')

quality 점수 = laplacian_variance × file_size_bytes (높을수록 보존)

Usage:
  PYTHONPATH=. poetry run python scripts/dedup_similar.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.pipeline.layer5_album import apply_grade_change  # noqa: E402

load_dotenv()

DB_DSN = (
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"
)

DEDUP_FROM = ["EVENT", "EVENT-L", "BEST", "FOOD", "MEMORY+", "MEMORY-", "NORMAL"]
DEMOTE_TARGET = "TRASH"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="DB 변경 X, 통계만")
    parser.add_argument("--window-seconds", type=int, default=10, help="시각 군집 ±초")
    args = parser.parse_args()

    grade_filter = ", ".join(f"'{g}'" for g in DEDUP_FROM)
    conn = psycopg.connect(DB_DSN, autocommit=True)
    with conn.cursor() as cur:
        cur.execute(f"""
            WITH bucketed AS (
              SELECT
                asset_id,
                grade,
                exif_datetime,
                camera_make,
                camera_model,
                file_size_bytes,
                COALESCE(laplacian_variance, 0) AS lap,
                FLOOR(EXTRACT(EPOCH FROM exif_datetime) / {args.window_seconds}) AS time_bucket
              FROM photo.classification
              WHERE exif_datetime IS NOT NULL
                AND grade IN ({grade_filter})
            ),
            ranked AS (
              SELECT *,
                ROW_NUMBER() OVER (
                  PARTITION BY grade, camera_make, camera_model, time_bucket
                  ORDER BY (lap * file_size_bytes) DESC NULLS LAST,
                           file_size_bytes DESC
                ) AS rn,
                COUNT(*) OVER (
                  PARTITION BY grade, camera_make, camera_model, time_bucket
                ) AS group_size
              FROM bucketed
            )
            SELECT grade, asset_id, group_size, rn
            FROM ranked
            WHERE rn > 1 AND group_size > 1
        """)
        candidates = cur.fetchall()

    print(f"📊 dedup 후보 (TRASH 강등 대상): {len(candidates)} 자산")

    by_grade: dict[str, int] = {}
    for grade, _, _, _ in candidates:
        by_grade[grade] = by_grade.get(grade, 0) + 1

    print("\n원래 등급별 분포:")
    for g in DEDUP_FROM:
        if g in by_grade:
            print(f"  {g:8s} → TRASH: {by_grade[g]:5d} 장")

    if args.dry_run:
        print("\n💡 dry-run — DB 변경 X")
        return

    if not candidates:
        return

    asset_ids = [a for _, a, _, _ in candidates]
    print(f"\n실제 TRASH 강등 적용 중 ({len(asset_ids)}장)...")
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE photo.classification
               SET grade = %s,
                   grade_source = 'dedup_demoted',
                   updated_at = NOW()
               WHERE asset_id = ANY(%s)""",
            (DEMOTE_TARGET, asset_ids),
        )
        print(f"  DB 갱신: {cur.rowcount} 강등")

    print("\n🔧 Layer 5 — 외장 HDD 등급 폴더 정합 ...")
    ok = fail = 0
    for i, aid in enumerate(asset_ids, 1):
        if i % 100 == 0:
            print(f"  진행 {i}/{len(asset_ids)} (ok {ok} fail/skip {fail})")
        success, _ = apply_grade_change(aid, DEMOTE_TARGET)
        if success:
            ok += 1
        else:
            fail += 1
    print(f"  HDD move: ok={ok} fail/skip={fail}")

    print("\n📊 최종 등급 분포:")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT grade, COUNT(*) FROM photo.classification
            GROUP BY grade ORDER BY grade
        """)
        for g, c in cur.fetchall():
            print(f"  {g:10s}: {c:5d}")

    conn.close()


if __name__ == "__main__":
    main()
