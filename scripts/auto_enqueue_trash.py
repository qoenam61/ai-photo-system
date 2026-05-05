"""신규 TRASH 자산 자동 cleanup_queue 등록 (24h grace).

사용자 명시 정책 (2026-05-05):
  분류 결과 grade='TRASH' 자산을 자동으로 cleanup_queue 등록.
  24h grace 후 maintenance.sh cron이 영구삭제.
  사용자는 그 사이 feedback_protect 표시로 보호 가능.

대상:
  grade='TRASH' AND asset_id NOT IN cleanup_queue

호출:
  - maintenance.sh [4.5] 단계 (30분 cron)
  - 또는 수동 PYTHONPATH=. poetry run python scripts/auto_enqueue_trash.py

정책:
  - grace_hours=24 (TRASH 안전 보호 시간)
  - dedup_demoted는 cleanup_service에서 자동 grace=0 적용
  - feedback_protect 자산은 cleanup_service에서 자동 제외
"""

from __future__ import annotations

import os
import sys

import httpx
import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)
CLASSIFY_URL = os.getenv("CLASSIFY_URL", "http://127.0.0.1:8765")


def fetch_unqueued_trash() -> list[str]:
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT c.asset_id::text
            FROM photo.classification c
            LEFT JOIN photo.cleanup_queue q ON q.asset_id = c.asset_id
            WHERE c.grade = 'TRASH'
              AND q.asset_id IS NULL
            ORDER BY c.classified_at ASC
        """)
        return [r[0] for r in cur.fetchall()]


def main() -> None:
    asset_ids = fetch_unqueued_trash()
    if not asset_ids:
        print("✅ 미등록 TRASH 자산 없음")
        return

    print(f"🗑  미등록 TRASH 자산 {len(asset_ids)}장 → cleanup_queue 등록 (grace 24h)")

    try:
        r = httpx.post(
            f"{CLASSIFY_URL}/cleanup_enqueue",
            json={"asset_ids": asset_ids, "grace_hours": 24},
            timeout=60,
        )
        r.raise_for_status()
        d = r.json()
        print(f"  enqueued={d.get('enqueued')} "
              f"already_queued={d.get('already_queued')} "
              f"skipped={len(d.get('skipped', []))}")
        for s in d.get("skipped", [])[:5]:
            print(f"    skip: {s.get('asset_id', '')[:8]} {s.get('reason', '')}")
    except Exception as e:
        print(f"❌ enqueue 실패: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
