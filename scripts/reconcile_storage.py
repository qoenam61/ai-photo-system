"""Storage ↔ DB 정합성 검증 + orphan 파일 정리.

DB photo.classification.storage_path 와 실제 storage 파일 비교.
DB에 없는 storage 파일 = orphan → 안전하게 quarantine 폴더로 이동 (삭제 X).

Usage:
  PYTHONPATH=. poetry run python scripts/reconcile_storage.py [--apply]
                                                              (기본: dry-run)
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_DSN = (
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"
)
LIBRARY_DIR = Path("/Volumes/Immich-Storage/immich-media/library")
ORPHAN_DIR = Path("/Volumes/Immich-Storage/_orphan")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="실제 이동 (기본: dry-run, 보고만)")
    args = parser.parse_args()

    # DB 등록 storage_path 집합
    conn = psycopg.connect(DB_DSN, autocommit=True)
    with conn.cursor() as cur:
        cur.execute("SELECT storage_path FROM photo.classification WHERE storage_path IS NOT NULL")
        db_paths = {Path(row[0]).resolve() for row in cur.fetchall()}
    conn.close()
    print(f"📊 DB 등록: {len(db_paths)}장")

    # Storage 실제 파일
    if not LIBRARY_DIR.exists():
        print(f"❌ Library 없음: {LIBRARY_DIR}")
        return
    storage_files = {p.resolve() for p in LIBRARY_DIR.rglob("*") if p.is_file() and not p.name.startswith(".")}
    print(f"📦 Storage 실제: {len(storage_files)}장")

    # 분석
    orphans = storage_files - db_paths
    missing = db_paths - storage_files
    print(f"\n🔍 정합성 분석")
    print(f"  ✅ 일치:   {len(db_paths & storage_files)}장")
    print(f"  ⚠️  Orphan (DB 없는 storage): {len(orphans)}장")
    print(f"  ❌ Missing (DB 있는데 파일 X): {len(missing)}장")

    # Orphan 처리
    if orphans:
        if args.apply:
            ts = time.strftime("%Y%m%d_%H%M%S")
            orphan_target = ORPHAN_DIR / ts
            orphan_target.mkdir(parents=True, exist_ok=True)
            for p in orphans:
                rel = p.relative_to(LIBRARY_DIR)
                dest = orphan_target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(dest))
            print(f"\n✅ {len(orphans)}장 → {orphan_target}")
            print(f"   (보존 — 7일 후 사용자 검토 후 영구 삭제 권장)")

            # 빈 디렉토리 정리
            for grade_dir in LIBRARY_DIR.iterdir():
                if grade_dir.is_dir() and not any(grade_dir.iterdir()):
                    grade_dir.rmdir()
        else:
            print(f"\n💡 dry-run: --apply로 {ORPHAN_DIR}로 이동")
            for p in list(orphans)[:5]:
                print(f"   sample: {p.relative_to(LIBRARY_DIR)}")

    # Missing 처리 (DB에 있는데 파일 X — 사용자 검토 필요)
    if missing:
        print(f"\n⚠️ Missing 5건 sample:")
        for p in list(missing)[:5]:
            print(f"   {p}")


if __name__ == "__main__":
    main()
