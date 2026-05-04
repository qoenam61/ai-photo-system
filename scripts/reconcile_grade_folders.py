"""DB grade ↔ HDD library/{GRADE}/ 정합 — 어긋난 자산 일괄 이동.

호스트 실행. iPhone 업로드 자산(`/usr/src/app/upload/...`)은 등급 폴더
사용 안 함 — 자동 skip. backup_legacy 자산만 대상.

Usage:
  PYTHONPATH=. poetry run python scripts/reconcile_grade_folders.py [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import subprocess
import sys

import psycopg
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.pipeline.layer5_album import apply_grade_change  # noqa: E402

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)


def fetch_immich_index() -> dict[str, str]:
    """asset_id stem → originalPath (library/ 내부 자산만)."""
    r = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "--csv", "-c",
         """SELECT "originalPath" FROM asset
            WHERE "deletedAt" IS NULL
              AND "originalPath" LIKE '/mnt/external/library/%'"""],
        capture_output=True, text=True, check=True,
    )
    rows = [r for r in csv.reader(io.StringIO(r.stdout)) if r]
    if rows and rows[0][0] == "originalPath":
        rows = rows[1:]
    idx: dict[str, str] = {}
    for row in rows:
        path = row[0]
        # /mnt/external/library/{GRADE}/{stem}.{ext}
        from pathlib import Path
        idx[Path(path).stem] = path
    return idx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("🔍 Immich library 인덱스 로드...")
    immich_idx = fetch_immich_index()
    print(f"   library/ 자산: {len(immich_idx)}장")

    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT asset_id::text, grade
            FROM photo.classification
            ORDER BY asset_id
        """)
        rows = cur.fetchall()

    needs_move: list[tuple[str, str, str]] = []  # (asset_id, current, target)
    for asset_id, db_grade in rows:
        path = immich_idx.get(asset_id)
        if not path:
            continue
        from pathlib import Path
        current = Path(path).parent.name
        if current != db_grade:
            needs_move.append((asset_id, current, db_grade))

    print(f"\n📊 어긋난 자산: {len(needs_move)}장")
    by_target: dict[str, int] = {}
    for _, cur_g, tgt_g in needs_move:
        key = f"{cur_g}→{tgt_g}"
        by_target[key] = by_target.get(key, 0) + 1
    for k, v in sorted(by_target.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")

    if args.dry_run:
        print("\n💡 dry-run — 변경 X")
        return

    if not needs_move:
        print("\n✅ 이미 정합 — 변경 없음")
        return

    print("\n🔧 폴더 이동 적용 중...")
    counts = {"ok": 0, "noop": 0, "skip": 0, "fail": 0}
    fails: list[tuple[str, str]] = []
    for i, (asset_id, _, target_grade) in enumerate(needs_move, 1):
        if i % 50 == 0:
            print(f"  진행 {i}/{len(needs_move)} (ok {counts['ok']}, fail {counts['fail']})")
        success, msg = apply_grade_change(asset_id, target_grade)
        category = msg.split(":")[0]
        counts[category] = counts.get(category, 0) + 1
        if not success and category == "fail":
            fails.append((asset_id, msg))

    print(f"\n📊 결과: ok={counts['ok']} noop={counts['noop']} "
          f"skip={counts['skip']} fail={counts['fail']}")
    if fails:
        print("\n❌ FAIL 사례 (최대 10):")
        for aid, msg in fails[:10]:
            print(f"  {aid[:8]} {msg}")


if __name__ == "__main__":
    main()
