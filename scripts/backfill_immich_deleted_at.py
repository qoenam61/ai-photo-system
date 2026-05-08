"""cleanup_audit hdd success ↔ Immich asset.deletedAt 정합 백필.

배경 (운영 발견 2026-05-07):
  cleanup_run.py:84 mark_immich_deleted subprocess 호출이 2026-05-04부터
  high-load 시 timeout 으로 누락. cleanup_audit success=TRUE 인데 Immich
  asset.deletedAt IS NULL 상태가 379건 누적 → DD-restored-asset-protection
  의 경로 B detect false positive 유발.

본 스크립트:
  cleanup_audit (success=TRUE, device='hdd') asset 中 Immich deletedAt=NULL
  자산을 일괄 chunk 단위 UPDATE. cleanup_audit reported_at 시각으로 deletedAt
  설정 (실제 cleanup 시각 보존, 감사 정합).

Idempotent — 이미 deletedAt 있는 자산은 영향 X (WHERE deletedAt IS NULL 조건).

Usage:
  PYTHONPATH=. poetry run python scripts/backfill_immich_deleted_at.py [--dry-run]

도메인 안전 영역. LLM 호출 X. 트레이딩 시간 무관.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
CHUNK = 200


def fetch_pending() -> list[tuple[str, str]]:
    """deletedAt 마킹 누락 자산 (immich_id, reported_at_iso)."""
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT immich_id::text,
                   COALESCE(device_deleted_at, reported_at)::text
            FROM photo.cleanup_audit
            WHERE success = TRUE
              AND device = 'hdd'
              AND immich_id IS NOT NULL
            ORDER BY reported_at DESC
        """)
        return cur.fetchall()


def filter_actual_gaps(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Immich에서 deletedAt=NULL 인 자산만 남김 (idempotent)."""
    if not rows:
        return []
    immich_ids = [r[0] for r in rows if UUID_RE.match(r[0])]
    if not immich_ids:
        return []

    gap_rows: list[tuple[str, str]] = []
    by_id = {r[0]: r[1] for r in rows}
    for i in range(0, len(immich_ids), CHUNK):
        chunk = immich_ids[i:i + CHUNK]
        id_list = ",".join(f"'{x}'" for x in chunk)
        proc = subprocess.run(
            ["docker", "exec", "-i", "immich-postgres",
             "psql", "-U", "postgres", "-d", "immich", "-t", "-A", "-c",
             f"SELECT id::text FROM asset "
             f"WHERE \"deletedAt\" IS NULL AND id IN ({id_list})"],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            print(f"⚠️ Immich SELECT 실패 (chunk {i//CHUNK+1}): {proc.stderr[:200]}",
                  file=sys.stderr)
            continue
        for line in proc.stdout.splitlines():
            iid = line.strip()
            if iid in by_id:
                gap_rows.append((iid, by_id[iid]))
    return gap_rows


def backfill_chunk(rows: list[tuple[str, str]]) -> tuple[int, int]:
    """immich asset.deletedAt 일괄 마킹 (UPDATE ... FROM VALUES).

    각 자산을 cleanup_audit reported_at 시각으로 마킹 (실제 cleanup 시각 보존).
    Returns: (updated_count, fail_count)
    """
    if not rows:
        return 0, 0

    total_updated = 0
    fails = 0
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i:i + CHUNK]
        # VALUES (id, ts), ... 로 batch UPDATE
        values_sql = ",".join(
            f"('{iid}'::uuid, '{ts}'::timestamptz)"
            for iid, ts in chunk if UUID_RE.match(iid)
        )
        if not values_sql:
            continue
        sql = f"""
            UPDATE asset SET "deletedAt" = v.ts
            FROM (VALUES {values_sql}) AS v(id, ts)
            WHERE asset.id = v.id AND asset."deletedAt" IS NULL
        """
        proc = subprocess.run(
            ["docker", "exec", "-i", "immich-postgres",
             "psql", "-U", "postgres", "-d", "immich", "-c", sql],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            fails += len(chunk)
            print(f"⚠️ chunk {i//CHUNK+1} UPDATE 실패: {proc.stderr[:200]}",
                  file=sys.stderr)
            continue
        # "UPDATE N" 파싱
        m = re.search(r"UPDATE (\d+)", proc.stdout)
        if m:
            total_updated += int(m.group(1))
        print(f"  chunk {i//CHUNK+1}: UPDATE {m.group(1) if m else '?'}/{len(chunk)}")

    return total_updated, fails


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="실제 UPDATE X. 갭 측정만.")
    args = parser.parse_args()

    audit_rows = fetch_pending()
    print(f"📋 cleanup_audit hdd success: {len(audit_rows)}건")
    if not audit_rows:
        print("✅ cleanup_audit 비어 있음")
        return 0

    gaps = filter_actual_gaps(audit_rows)
    print(f"🔍 정합 갭 (Immich deletedAt=NULL): {len(gaps)}건")
    if not gaps:
        print("✅ 정합 OK — 백필 불필요")
        return 0

    if args.dry_run:
        print("\n💡 DRY-RUN — 실제 UPDATE X")
        for iid, ts in gaps[:5]:
            print(f"  {iid[:8]} → deletedAt={ts}")
        if len(gaps) > 5:
            print(f"  ... +{len(gaps) - 5}건")
        return 0

    print(f"\n🔧 백필 진행 (chunk={CHUNK}) ...")
    updated, fails = backfill_chunk(gaps)
    print(f"\n📊 결과: UPDATE {updated} / 실패 {fails} / 대상 {len(gaps)}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
