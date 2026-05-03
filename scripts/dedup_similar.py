"""유사컷 강등 — EXIF 시각 ±10초 + 카메라 동일 그룹화.

설계 §4 EVENT/BEST 유사컷 처리 원칙 적용.
강등 규칙:
  EVENT   → EVENT-L
  EVENT-L → MEMORY+
  BEST    → MEMORY+
  MEMORY+ → MEMORY-

quality 점수 = laplacian_variance × file_size_bytes
그룹 내 최고 quality 1개만 유지, 나머지 강등.

Usage:
  PYTHONPATH=. poetry run python scripts/dedup_similar.py [--dry-run]
"""

from __future__ import annotations

import argparse

import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_DSN = (
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"
)

DEMOTE = {
    "EVENT":   "EVENT-L",
    "EVENT-L": "MEMORY+",
    "BEST":    "MEMORY+",
    "MEMORY+": "MEMORY-",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="DB 변경 X, 통계만")
    parser.add_argument("--window-seconds", type=int, default=10, help="시각 군집 ±초")
    args = parser.parse_args()

    conn = psycopg.connect(DB_DSN, autocommit=True)
    with conn.cursor() as cur:
        # 강등 후보: 같은 등급·동일 카메라·동일 분단위 시각
        # window_seconds 단위로 시각 버킷화
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
                AND grade IN ('EVENT', 'EVENT-L', 'BEST', 'MEMORY+')
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

    print(f"📊 강등 후보: {len(candidates)} 자산")

    by_grade: dict[str, int] = {}
    for grade, _, _, _ in candidates:
        by_grade[grade] = by_grade.get(grade, 0) + 1

    print("\n등급별 강등 수:")
    for g in ["EVENT", "EVENT-L", "BEST", "MEMORY+"]:
        if g in by_grade:
            new = DEMOTE[g]
            print(f"  {g:8s} → {new:8s}: {by_grade[g]:4d} 장")

    if args.dry_run:
        print("\n💡 dry-run — DB 변경 X")
        return

    print("\n실제 강등 적용 중...")
    with conn.cursor() as cur:
        for old_grade, new_grade in DEMOTE.items():
            asset_ids = [a for g, a, _, _ in candidates if g == old_grade]
            if not asset_ids:
                continue
            cur.execute(
                """UPDATE photo.classification
                   SET grade = %s,
                       grade_source = 'dedup_demoted',
                       updated_at = NOW()
                   WHERE asset_id = ANY(%s)""",
                (new_grade, asset_ids),
            )
            print(f"  {old_grade:8s} → {new_grade:8s}: {cur.rowcount} 강등")

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
