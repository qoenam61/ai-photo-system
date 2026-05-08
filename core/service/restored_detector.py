"""복원 감지 서비스 — Layer 5/6 cleanup_audit 자산이 다시 살아난 경우 자동 보호.

도메인 안전 영역. 정식 TC: wiki/03-pdca/active/report/TC-restored-asset-protection.md.

배경 (DD-restored-asset-protection.md, 2026-05-07):
  사용자가 iPhone "최근 삭제됨" 또는 Immich 휴지통에서 자산을 복원하면
  시스템이 이를 감지하지 못하고 다음 cycle에 다시 cleanup_queue에 등록되는 갭 존재.
  본 모듈은 두 경로를 detect 후 photo.feedback (feedback_type='restored') 자동 등록.

경로:
  A. iPhone 휴지통 복원 + 재백업 — sha256 매칭. cleanup_audit asset_id 와 같은 해시
     가진 새 photo.classification row 가 reported_at 이후 등장.
  B. Immich 자체 휴지통 복원 — Immich asset.deletedAt 가 cleanup_audit reported_at
     이후 NULL 로 복귀. 같은 immich_id, 같은 우리 asset_id.

보호 액션:
  - photo.feedback (feedback_type='restored') INSERT
  - photo.cleanup_queue 에 미처리 행 있으면 cancelled=TRUE
  - grade 변경 X (사용자 결정 Q1: 그대로 TRASH + protect만)

호출:
  - scripts/detect_restored_assets.py (maintenance.sh [4.5/9] 30분 cron)
  - 단위 테스트: core/tests/unit/test_restored_detector.py
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

import psycopg

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)


@dataclass(slots=True)
class RestoredPair:
    """경로 A 결과: 영구삭제된 old asset + 재백업된 new asset."""
    old_asset_id: str
    new_asset_id: str
    sha256: str


@dataclass(slots=True)
class MarkResult:
    feedback_inserted: int = 0
    feedback_already: int = 0
    queue_cancelled: int = 0
    errors: list[str] = field(default_factory=list)


def detect_iphone_rebackup(dsn: str = DB_DSN, since_days: int | None = None) -> list[RestoredPair]:
    """경로 A: iPhone 재백업 detect.

    cleanup_audit (hdd success) asset_id 의 sha256 과 동일한 새 photo.classification
    row 가 reported_at 이후 등장한 케이스 (asset_id 다름).

    Args:
      since_days: None이면 전체. 운영 retro-detect 시 30/60/90 등 지정.
    """
    where_clause = ""
    params: list = []
    if since_days is not None:
        where_clause = "AND ca.reported_at >= NOW() - (%s || ' days')::interval"
        params.append(str(since_days))

    sql = f"""
        SELECT
          c_old.asset_id::text AS old_id,
          c_new.asset_id::text AS new_id,
          c_old.sha256
        FROM photo.cleanup_audit ca
        JOIN photo.classification c_old ON c_old.asset_id = ca.asset_id
        JOIN photo.classification c_new
              ON c_new.sha256 = c_old.sha256
             AND c_new.asset_id != c_old.asset_id
             AND c_new.classified_at > ca.reported_at
        WHERE ca.success = TRUE
          AND ca.device = 'hdd'
          {where_clause}
          AND NOT EXISTS (
            SELECT 1 FROM photo.feedback f
            WHERE f.asset_id = c_new.asset_id
              AND f.feedback_type IN ('protect', 'restored')
          )
    """
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return [RestoredPair(old_asset_id=r[0], new_asset_id=r[1], sha256=r[2])
                for r in cur.fetchall()]


def detect_immich_trash_restore(dsn: str = DB_DSN) -> list[str]:
    """경로 B: Immich 휴지통 복원 detect.

    cleanup_audit (hdd success) immich_id 中 Immich asset.deletedAt IS NULL 로
    복귀한 자산. HDD 파일은 이미 unlink 되어 broken_link 상태일 가능성 大.

    Returns: photo asset_id 목록 (보호 등록 대상). 빈 리스트면 detect 없음.
    """
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ca.asset_id::text, ca.immich_id::text
            FROM photo.cleanup_audit ca
            WHERE ca.success = TRUE
              AND ca.device = 'hdd'
              AND ca.immich_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM photo.feedback f
                WHERE f.asset_id = ca.asset_id
                  AND f.feedback_type IN ('protect', 'restored')
              )
        """)
        candidates = cur.fetchall()
    if not candidates:
        return []

    immich_ids = [c[1] for c in candidates]
    asset_by_immich = {c[1]: c[0] for c in candidates}

    # Immich DB 조회 — deletedAt IS NULL 인 자산만 (복원된 자산)
    id_list = ",".join(f"'{i}'" for i in immich_ids)
    proc = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "-t", "-A", "-c",
         f"SELECT id::text FROM asset WHERE \"deletedAt\" IS NULL "
         f"AND id IN ({id_list})"],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        return []

    restored_immich = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    return [asset_by_immich[i] for i in restored_immich if i in asset_by_immich]


def mark_restored(asset_ids: list[str], dsn: str = DB_DSN) -> MarkResult:
    """detect 결과 자산을 photo.feedback (restored) + cleanup_queue cancel.

    - feedback INSERT — 'restored' type. 이미 protect/restored 있으면 skip (idempotent).
    - cleanup_queue UPDATE cancelled=TRUE — 미처리 행만 (processed_at IS NULL).
      이미 처리된 행은 cleanup_audit 와 짝이라 보존 (감사 무결성).
    """
    res = MarkResult()
    if not asset_ids:
        return res

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        for aid in asset_ids:
            try:
                cur.execute("""
                    SELECT 1 FROM photo.feedback
                    WHERE asset_id = %s::uuid
                      AND feedback_type IN ('protect', 'restored')
                    LIMIT 1
                """, (aid,))
                if cur.fetchone():
                    res.feedback_already += 1
                    continue

                cur.execute("""
                    INSERT INTO photo.feedback
                      (asset_id, feedback_type, created_at)
                    VALUES (%s::uuid, 'restored', NOW())
                """, (aid,))
                res.feedback_inserted += 1

                cur.execute("""
                    UPDATE photo.cleanup_queue
                    SET cancelled = TRUE
                    WHERE asset_id = %s::uuid
                      AND cancelled = FALSE
                      AND processed_at IS NULL
                """, (aid,))
                res.queue_cancelled += cur.rowcount
            except Exception as e:
                res.errors.append(f"{aid[:8]}:{type(e).__name__}:{e}")
    return res
