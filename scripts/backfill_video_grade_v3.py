"""영상 등급 세분화 백필 — 2026-05-08 P1-D.

기존 정책: 영상 ≥3초 일률 EVENT-L (auto_video).
신규 정책 (classifier.py VIDEO_SHORT/LONG_THRESHOLD):
  duration < 3초     → TRASH    (auto_short_video)
  3 ≤ duration < 10초 → MEMORY+ (auto_short_clip — 짧은 일상 영상)
  duration ≥ 10초    → EVENT-L  (auto_video — 긴 행사 영상)

사용자 환원 자산(restored_from_dedup, dedup_demoted_*)은 제외 — 등급 강등 정책 충돌.

Usage:
  PYTHONPATH=. poetry run python scripts/backfill_video_grade_v3.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with psycopg.connect(DB_DSN, autocommit=False) as conn, conn.cursor() as cur:
        # 1. 사전 분포
        cur.execute("""
            SELECT
              SUM(CASE WHEN duration_seconds < 3 THEN 1 ELSE 0 END) AS very_short,
              SUM(CASE WHEN duration_seconds >= 3 AND duration_seconds < 10 THEN 1 ELSE 0 END) AS short_clip,
              SUM(CASE WHEN duration_seconds >= 10 THEN 1 ELSE 0 END) AS long_video
            FROM photo.classification
            WHERE grade = 'EVENT-L' AND grade_source = 'auto_video'
        """)
        very_short, short_clip, long_video = cur.fetchone()
        print(f"📊 EVENT-L auto_video: <3s={very_short or 0}  3-10s={short_clip or 0}  >=10s={long_video or 0}")

        # 2. <3s → TRASH
        cur.execute("""
            UPDATE photo.classification
            SET grade = 'TRASH', grade_source = 'auto_short_video',
                updated_at = NOW()
            WHERE grade = 'EVENT-L'
              AND grade_source = 'auto_video'
              AND duration_seconds < 3
            RETURNING asset_id
        """)
        very_short_updated = cur.rowcount
        print(f"  → TRASH (<3s): {very_short_updated}장")

        # 3. 3 ≤ dur < 10s → MEMORY+
        cur.execute("""
            UPDATE photo.classification
            SET grade = 'MEMORY+', grade_source = 'auto_short_clip',
                updated_at = NOW()
            WHERE grade = 'EVENT-L'
              AND grade_source = 'auto_video'
              AND duration_seconds >= 3
              AND duration_seconds < 10
            RETURNING asset_id
        """)
        short_clip_updated = cur.rowcount
        print(f"  → MEMORY+ (3-10s): {short_clip_updated}장")

        if args.dry_run:
            conn.rollback()
            print("\n💡 dry-run — DB 변경 X")
            return

        conn.commit()
        print("\n✅ 백필 완료 (commit)")

        # 4. 사후 분포 확인
        cur.execute("""
            SELECT grade, grade_source, COUNT(*) FROM photo.classification
            WHERE grade_source IN ('auto_video', 'auto_short_video', 'auto_short_clip')
            GROUP BY 1, 2 ORDER BY 1, 2
        """)
        print("\n📊 사후 분포:")
        for grade, src, cnt in cur.fetchall():
            print(f"  {grade:8s} {src:25s} {cnt}장")


if __name__ == "__main__":
    main()
