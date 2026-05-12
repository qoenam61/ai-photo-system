"""iPhone 업로드 감지 모니터.

Phase 4.5 운영 중 — Immich에 새로 업로드된 자산 중 아직 photo.classification에
없는 자산(분류 대기)을 보고. 이미 분류된 자산은 카운트에서 제외.

iPhone Immich 앱 저장 위치 = /usr/src/app/upload (uploadLibrary).
asset_id == Immich asset UUID == source_path 파일 stem → classification JOIN 가능.

Usage:
  PYTHONPATH=. poetry run python scripts/monitor_iphone_uploads.py [--apply]

옵션:
  --apply: classification에 NORMAL 임시 행 INSERT (auto-classify 대기)
"""

from __future__ import annotations

import argparse
import csv
import io
import subprocess
import uuid
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

OUR_DSN = (
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"
)

EXTERNAL_LIB_PREFIX = "/mnt/external/library/"


def _fetch_classified_ids() -> set[str]:
    """photo.classification에 이미 등록된 asset_id 전체 (UUID 문자열 set)."""
    with psycopg.connect(OUR_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT asset_id::text FROM photo.classification")
        return {r[0] for r in cur.fetchall()}


def fetch_unclassified() -> tuple[list[tuple[str, str, str]], int]:
    """iPhone upload 자산 중 미분류만 반환. (rows, total_iphone_count)

    - total_iphone_count: Immich의 전체 iPhone upload 자산 수 (분류 여부 무관)
    - rows: 그 중 photo.classification에 없는 자산만
    """
    proc = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich",
         "--csv", "-c",
         'SELECT id::text, "originalPath", type FROM asset '
         "WHERE \"deletedAt\" IS NULL "
         f"AND \"originalPath\" NOT LIKE '{EXTERNAL_LIB_PREFIX}%' "
         "AND \"originalPath\" NOT LIKE '%/encoded-video/%' "
         "AND \"originalPath\" NOT LIKE '%/thumbs/%'"],
        capture_output=True, text=True, check=True,
    )
    reader = csv.reader(io.StringIO(proc.stdout))
    all_rows = list(reader)
    if all_rows and all_rows[0] and all_rows[0][0] == "id":
        all_rows = all_rows[1:]
    all_rows = [(r[0], r[1], r[2]) for r in all_rows if r]

    # classification.asset_id = Path(originalPath).stem (Immich asset.id 와 다름)
    classified = _fetch_classified_ids()
    unclassified = [(rid, path, t) for rid, path, t in all_rows
                    if Path(path).stem not in classified]
    return unclassified, len(all_rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="classification에 NORMAL 임시 행 INSERT")
    args = parser.parse_args()

    rows, total = fetch_unclassified()

    print(f"📱 iPhone 업로드 현황: 전체 {total}장 / 미분류 {len(rows)}장")

    if not rows:
        print("✅ 미분류 없음 — 모두 분류 완료")
        return

    by_type: dict[str, int] = {}
    for _, _, t in rows:
        by_type[t] = by_type.get(t, 0) + 1
    for t, c in by_type.items():
        print(f"  {t}: {c}장")

    samples = rows[:5]
    print("\n샘플 (미분류):")
    for immich_id, path, t in samples:
        print(f"  [{t}] {path}")

    if not args.apply:
        print("\n💡 dry-run — 분류 미반영 (--apply 로 NORMAL 임시 등록)")
        return

    conn = psycopg.connect(OUR_DSN, autocommit=True)
    inserted = 0
    with conn.cursor() as cur:
        for immich_id, path, t in rows:
            if t != "IMAGE":
                continue
            asset_uuid = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO photo.classification
                  (asset_id, source_path, grade, grade_source, classified_at)
                VALUES (%s, %s, 'NORMAL', 'iphone_upload_pending', NOW())
                ON CONFLICT (asset_id) DO NOTHING
            """, (asset_uuid, path))
            if cur.rowcount > 0:
                inserted += 1
    print(f"\n✅ {inserted}건 NORMAL로 등록 (auto-classify 재분류 대기)")
    conn.close()


if __name__ == "__main__":
    main()
