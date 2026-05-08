"""Layer 5 HDD 영구삭제 워커 — 호스트 실행 전용.

cleanup_queue grace 만료 항목 → classify-service /verify_backup 호출 →
PASS 시 외장 HDD 파일 unlink + cleanup_audit 기록.

photo-classify 컨테이너는 /storage:ro 마운트라 컨테이너 내부에서 삭제 불가.
이 스크립트는 호스트에서 직접 외장 HDD를 다룸.

Usage:
  PYTHONPATH=. poetry run python scripts/cleanup_run.py [--dry-run] [--limit N]

기본 동작: --dry-run (실제 삭제 X). --no-dry-run 명시 시 실삭제.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import time
from pathlib import Path

import httpx
import psycopg
from dotenv import load_dotenv

# UUID 정규식 — SQL injection 방어 (NC-2)
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)
CLASSIFY_URL = os.getenv("CLASSIFY_URL", "http://127.0.0.1:8765")

# Immich originalPath → 호스트 외장 HDD 실제 경로.
HOST_PATH_MAPPINGS = [
    ("/mnt/external", "/Volumes/Immich-Storage/immich-media"),
    ("/usr/src/app/upload", "/Volumes/Immich-Storage/immich-uploads"),
]


def _resolve_host(immich_path: str) -> Path:
    for src, dst in HOST_PATH_MAPPINGS:
        if immich_path.startswith(src):
            return Path(dst + immich_path[len(src):])
    return Path(immich_path)


def fetch_processable(limit: int) -> list[tuple]:
    """grace 만료 + 미처리 + 미취소 + 미보호 항목."""
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT q.id, q.asset_id::text, c.grade, c.grade_source,
                   COALESCE(c.file_size_bytes, 0)
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
        return cur.fetchall()


def verify_via_service(asset_id: str, client: httpx.Client) -> dict:
    r = client.post(
        f"{CLASSIFY_URL}/verify_backup",
        json={"asset_id": asset_id},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


def mark_immich_deleted(immich_id: str, retries: int = 1) -> bool:
    """Immich asset deletedAt 표시 — 향후 cleanup_candidates에서 자동 제외.

    HDD 파일 unlink 후 호출. SQL injection 방어: UUID 형식 검증 (NC-2).

    실패 시 1회 재시도 (high-load timeout 방어, 운영 발견 2026-05-07).
    누락분은 backfill_immich_deleted_at.py 가 idempotent 정합.
    """
    if not immich_id or not UUID_RE.match(immich_id):
        return False
    for attempt in range(retries + 1):
        try:
            proc = subprocess.run(
                ["docker", "exec", "-i", "immich-postgres",
                 "psql", "-U", "postgres", "-d", "immich", "-c",
                 f"UPDATE asset SET \"deletedAt\" = NOW() WHERE id = '{immich_id}'"],
                capture_output=True, text=True, timeout=15,
            )
            if proc.returncode == 0:
                return True
        except Exception:
            pass
        if attempt < retries:
            time.sleep(0.5)
    return False


_REASON_CATEGORIES_HDD = {
    "layer5_hdd_purge": "hdd_purge",
    "verify_fail": "verify_fail",
    "host_path_missing": "host_path_missing",
    "unlink_failed": "unlink_failed",
}


def _hdd_reason_category(reason: str, imm_marked_ok: bool) -> str:
    """reason prefix → category. 2026-05-08 P0-B."""
    for prefix, category in _REASON_CATEGORIES_HDD.items():
        if reason.startswith(prefix):
            if category == "hdd_purge" and not imm_marked_ok:
                return "hdd_purge_imm_unmarked"
            return category
    return "hdd_other_error"


def mark_audit(
    queue_id: int,
    asset_id: str,
    immich_id: str,
    success: bool,
    reason: str,
    reclaimed_bytes: int,
) -> int:
    """cleanup_audit row 기록 + Immich asset.deletedAt 마킹 (orphan 방지).

    reason_detail에 :imm_marked / :imm_mark_fail suffix를 보존 — 카테고리는
    별도 reason_category 컬럼으로 분리 (2026-05-08 P0-B).
    """
    imm_ok = True
    if success and immich_id:
        imm_ok = mark_immich_deleted(immich_id)
        reason = f"{reason}:{'imm_marked' if imm_ok else 'imm_mark_fail'}"

    reason_category = _hdd_reason_category(reason, imm_ok)

    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
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
        audit_id = cur.fetchone()[0]

    return audit_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--no-dry-run", action="store_true",
                        help="명시해야 실제 HDD 삭제 수행")
    args = parser.parse_args()
    dry_run = not args.no_dry_run

    items = fetch_processable(args.limit)
    if not items:
        print("✅ 처리 대기 항목 없음 (grace 미만료 또는 cleanup_queue 비어 있음)")
        return

    print(f"🗑  Layer 5 HDD cleanup — {len(items)}건 처리 ({'DRY-RUN' if dry_run else '실삭제'})")

    client = httpx.Client()
    success = failed = skipped = 0
    reclaimed = 0
    rows = []
    try:
        for queue_id, asset_id, grade, src, size in items:
            v = verify_via_service(asset_id, client)
            if not v.get("verified"):
                reason = f"verify_fail:{v.get('reason')}"
                if not dry_run:
                    mark_audit(queue_id, asset_id, "", False, reason, 0)
                failed += 1
                rows.append((asset_id, grade, src, "FAIL", reason, 0))
                continue

            target = _resolve_host(v["immich_path"])
            if not target.exists():
                reason = f"host_path_missing:{target}"
                if not dry_run:
                    mark_audit(queue_id, asset_id, v.get("immich_id", ""),
                               False, reason, 0)
                failed += 1
                rows.append((asset_id, grade, src, "FAIL", reason, 0))
                continue

            actual_size = target.stat().st_size

            if dry_run:
                rows.append((asset_id, grade, src, "WOULD-DELETE",
                             str(target), actual_size))
                success += 1
                reclaimed += actual_size
                continue

            try:
                target.unlink()
            except Exception as e:
                reason = f"unlink_failed:{e}"
                mark_audit(queue_id, asset_id, v.get("immich_id", ""),
                           False, reason, 0)
                failed += 1
                rows.append((asset_id, grade, src, "FAIL", reason, 0))
                continue

            audit_id = mark_audit(
                queue_id, asset_id, v.get("immich_id", ""),
                True, "layer5_hdd_purge", actual_size,
            )
            rows.append((asset_id, grade, src, "DELETED",
                         f"audit#{audit_id}", actual_size))
            success += 1
            reclaimed += actual_size
    finally:
        client.close()

    print()
    for aid, grade, src, status, detail, sz in rows:
        size_kb = sz / 1024
        print(f"  {status:13s} {aid[:8]} {grade:7s} {src:18s} "
              f"{size_kb:8.1f}KB  {detail}")

    print(f"\n📊 success {success} / failed {failed} / skipped {skipped}")
    print(f"💾 reclaimed {reclaimed/1024/1024:.1f} MB "
          f"({'DRY-RUN — 실제 삭제 X' if dry_run else '실삭제 완료'})")


if __name__ == "__main__":
    main()
