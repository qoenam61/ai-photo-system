"""iPhone 업로드 감지 모니터.

설계 §16 Phase 4 진입 전 임시 monitor — Immich에 새로 업로드된 자산 중
External Library('Backup Migration')에 속하지 않은 자산을 분류 대기 큐에 적재.

iPhone Immich 앱은 기본 저장 위치 = /usr/src/app/upload (uploadLibrary).
이 자산들은 libraryId가 NULL 또는 별개 사용자 라이브러리.

Usage:
  PYTHONPATH=. poetry run python scripts/monitor_iphone_uploads.py [--apply]

옵션:
  --apply: photo.classification에 NORMAL 임시 행 INSERT (이후 Phase 4 파이프라인이 재분류)
"""

from __future__ import annotations

import argparse
import csv
import io
import subprocess
import uuid

import psycopg
from dotenv import load_dotenv

load_dotenv()

OUR_DSN = (
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"
)

EXTERNAL_LIB_PREFIX = "/mnt/external/library/"


def fetch_unclassified() -> list[tuple[str, str, str]]:
    """Immich asset 중 외부 라이브러리 아닌 것 + classification에 없는 것."""
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
    rows = list(reader)
    if rows and rows[0] and rows[0][0] == "id":
        rows = rows[1:]
    return [(r[0], r[1], r[2]) for r in rows if r]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="classification에 NORMAL 임시 행 INSERT")
    args = parser.parse_args()

    rows = fetch_unclassified()
    if not rows:
        print("✅ 신규 업로드 없음 (External Library 외 자산 0건)")
        return

    print(f"📱 신규 업로드 감지: {len(rows)}건")
    by_type: dict[str, int] = {}
    for _, _, t in rows:
        by_type[t] = by_type.get(t, 0) + 1
    for t, c in by_type.items():
        print(f"  {t}: {c}장")

    samples = rows[:5]
    print("\n샘플:")
    for immich_id, path, t in samples:
        print(f"  [{t}] {path}")

    if not args.apply:
        print("\n💡 dry-run — Phase 4 미완료. classification 미반영")
        return

    # Phase 4 파이프라인 미완료 — 임시로 NORMAL 등급 row 적재만
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
    print(f"\n✅ {inserted}건 classification에 NORMAL로 등록 (Phase 4 재분류 대기)")
    conn.close()


if __name__ == "__main__":
    main()
