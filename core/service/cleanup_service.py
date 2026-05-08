"""Cleanup Service — Layer 5/6 자산 삭제 게이트 + 큐 등록.

도메인 안전 영역. 정식 TC: wiki/03-pdca/active/report/TC-phase5-fastlane.md.

분담:
- enqueue_cleanup() — cleanup_queue INSERT (컨테이너 내부 OK, read-only mount 무관).
- HDD 실삭제는 별도 호스트 스크립트(scripts/cleanup_run.py)에서 수행
  (photo-classify는 /storage:ro 마운트라 컨테이너에서 unlink 불가).

정책 (v3.13 + 사용자 명시 정정 2026-05-05):
- HDD 영구삭제 가능: **TRASH만** (사용자 명시 안전 정책)
- dedup_demoted_* = 등급 강등 표시일 뿐, HDD 영구 보존 (사용자 명시 정정 2026-05-05)
- TRASH grace: 7일 (사용자 명시 확대) — 사용자 자동 승인 시 즉시 처리 가능
- feedback_protect 자산: 영구 제외
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import psycopg

DB_DSN = os.getenv(
    "PHOTO_DB_DSN",
    "host=trading_postgres port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)

DEFAULT_GRACE_HOURS = 168  # 7일 — 사용자 출장/검토 여유 (2026-05-05 확대)
HDD_DELETABLE_GRADES = {"TRASH"}  # MEMORY-/NORMAL/FOOD/EVENT-L/dedup_demoted_* 모두 HDD 보존


@dataclass(slots=True)
class EnqueueResult:
    enqueued: int = 0
    already_queued: int = 0
    skipped: list[dict] = field(default_factory=list)


def enqueue_cleanup(
    asset_ids: list[str],
    grace_hours: int = DEFAULT_GRACE_HOURS,
    dsn: str = DB_DSN,
) -> EnqueueResult:
    """cleanup_queue에 자산 등록.

    - feedback_protect 자산 → skipped
    - classification 미등록 → skipped
    - **TRASH 외 등급(dedup_demoted_* 포함) → skipped** (사용자 명시 정정 2026-05-05)
    - 이미 등록(UNIQUE) → already_queued (no-op)
    """
    res = EnqueueResult()
    if not asset_ids:
        return res

    grace_default = timedelta(hours=grace_hours)
    now = datetime.now(timezone.utc)

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT asset_id::text FROM photo.feedback
            WHERE feedback_type IN ('protect', 'restored')
              AND asset_id = ANY(%s::uuid[])
        """, (asset_ids,))
        protected = {r[0] for r in cur.fetchall()}

        cur.execute("""
            SELECT asset_id::text, grade, grade_source
            FROM photo.classification
            WHERE asset_id = ANY(%s::uuid[])
        """, (asset_ids,))
        meta = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

        for aid in asset_ids:
            if aid in protected:
                res.skipped.append({"asset_id": aid, "reason": "protected"})
                continue
            if aid not in meta:
                res.skipped.append({"asset_id": aid, "reason": "no_classification"})
                continue
            grade, src = meta[aid]
            if grade not in HDD_DELETABLE_GRADES:
                res.skipped.append({
                    "asset_id": aid,
                    "reason": f"not_deletable:grade={grade}/source={src}",
                })
                continue

            # TRASH만 — grace 기본 7일 (사용자 자동 승인 시 외부에서 grace=0 호출)
            grace_until = now + grace_default
            cur.execute("""
                INSERT INTO photo.cleanup_queue (asset_id, grace_until)
                VALUES (%s::uuid, %s)
                ON CONFLICT (asset_id) DO NOTHING
                RETURNING id
            """, (aid, grace_until))
            row = cur.fetchone()
            if row:
                res.enqueued += 1
            else:
                res.already_queued += 1
    return res


@dataclass(slots=True)
class QueueItem:
    queue_id: int
    asset_id: str
    grade: str
    grade_source: str
    file_size_bytes: int
    grace_until: str
    immich_originalpath: str = ""  # populated by caller


def fetch_processable_queue(
    limit: int = 20,
    dsn: str = DB_DSN,
) -> list[QueueItem]:
    """grace 만료 + 미처리 + 미취소 + 보호 미적용 cleanup_queue 항목."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT q.id, q.asset_id::text, c.grade, c.grade_source,
                   COALESCE(c.file_size_bytes, 0), q.grace_until::text
            FROM photo.cleanup_queue q
            JOIN photo.classification c ON c.asset_id = q.asset_id
            LEFT JOIN photo.feedback f
                   ON f.asset_id = q.asset_id
                  AND f.feedback_type IN ('protect', 'restored')
            WHERE q.cancelled = FALSE
              AND q.processed_at IS NULL
              AND q.grace_until <= NOW()
              AND f.id IS NULL
            ORDER BY q.created_at ASC
            LIMIT %s
        """, (limit,))
        return [
            QueueItem(
                queue_id=r[0], asset_id=r[1], grade=r[2], grade_source=r[3],
                file_size_bytes=r[4], grace_until=r[5],
            )
            for r in cur.fetchall()
        ]


def mark_processed(
    queue_id: int,
    asset_id: str,
    immich_id: str,
    success: bool,
    reason: str,
    reclaimed_bytes: int,
    dsn: str = DB_DSN,
    reason_category: str | None = None,
) -> int:
    """cleanup_queue.processed_at + cleanup_audit row 기록.

    reason_category: 카디널리티 ≤ 30 카테고리 (hdd_purge / verify_fail 등).
    None이면 success/reason에서 자동 추론. 2026-05-08 P0-B.
    Returns audit_id.
    """
    if reason_category is None:
        reason_category = "hdd_purge" if success else "hdd_other_error"

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        if success:
            cur.execute("""
                UPDATE photo.cleanup_queue
                SET processed_at = NOW(), deleted_at_device = NOW()
                WHERE id = %s
            """, (queue_id,))
        cur.execute("""
            INSERT INTO photo.cleanup_audit
              (asset_id, immich_id, device, success, reason,
               reason_category, reason_detail,
               reclaimed_bytes, device_deleted_at)
            VALUES (%s::uuid, %s, 'hdd', %s, %s, %s, %s, %s, NOW())
            RETURNING id
        """, (asset_id, immich_id or None, success, reason,
              reason_category, reason, reclaimed_bytes))
        return cur.fetchone()[0]


def cancel_queue_item(queue_id: int, dsn: str = DB_DSN) -> None:
    """cleanup_queue 취소 — 도메인 안전 우회 시 비상 정지."""
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE photo.cleanup_queue SET cancelled = TRUE WHERE id = %s",
            (queue_id,),
        )
