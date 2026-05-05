"""모든 자산 → immich-views/{GRADE}/{asset_id}.{ext} symlink 일괄 생성.

사용자 명시 (2026-05-04): 외장 HDD에서 등급별로 모든 자산(legacy+iPhone)
가시화. immich-views 통합 view 폴더.

내용:
  - DB photo.classification 전수 조회
  - 각 자산의 immich originalPath 매칭 → 호스트 경로 변환
  - immich-views/{GRADE}/{asset_id}.{ext} symlink 생성

기존 view 폴더와 공존:
  immich-views/월별/      ← 기존 storage_service 월별 view
  immich-views/{GRADE}/   ← 새 등급별 view (BEST/EVENT/.../TRASH)

Usage:
  PYTHONPATH=. poetry run python scripts/build_grade_views.py [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import psycopg
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.pipeline.layer5_album import refresh_view_link, VIEWS_HOST  # noqa: E402

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)


def fetch_immich_index() -> dict[str, str]:
    """Immich asset index: stem → originalPath."""
    r = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "--csv", "-c",
         """SELECT "originalPath" FROM asset WHERE "deletedAt" IS NULL"""],
        capture_output=True, text=True, check=True,
    )
    rows = [r for r in csv.reader(io.StringIO(r.stdout)) if r]
    if rows and rows[0][0] == "originalPath":
        rows = rows[1:]
    return {Path(row[0]).stem: row[0] for row in rows}


def cleanup_broken_links() -> int:
    """모든 immich-views/{GRADE}/ 폴더에서 broken symlink 제거.

    cleanup_run.py가 외장 HDD 자산 unlink 후 남는 잔재 정리.
    Returns: 정리된 broken symlink 개수.
    """
    cleaned = 0
    for grade_dir in VIEWS_HOST.iterdir():
        if not grade_dir.is_dir() or grade_dir.name == "월별":
            continue
        for link in grade_dir.iterdir():
            if link.is_symlink() and not link.exists():
                try:
                    link.unlink()
                    cleaned += 1
                except Exception:
                    pass
    return cleaned


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run:
        broken_cleaned = cleanup_broken_links()
        if broken_cleaned:
            print(f"🧹 broken symlink 정리: {broken_cleaned}개")

    print("🔍 Immich asset 인덱스 로드 ...")
    immich_idx = fetch_immich_index()
    print(f"   active asset: {len(immich_idx)}장")

    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT asset_id::text, grade
            FROM photo.classification
            ORDER BY grade, asset_id
        """)
        rows = cur.fetchall()
    print(f"   classification: {len(rows)}장")

    by_grade: Counter[str] = Counter()
    for _, g in rows:
        by_grade[g] += 1
    print("\n📊 등급별 view 생성 대상:")
    for g, c in sorted(by_grade.items()):
        print(f"  {g:8s}: {c}")

    if args.dry_run:
        print(f"\n💡 dry-run — view 폴더: {VIEWS_HOST}/{{GRADE}}/")
        print("   기존 immich-views/월별/은 그대로 유지")
        return

    print(f"\n🔧 immich-views/{{GRADE}}/ symlink 생성 ...")
    ok = miss = fail = 0
    for i, (aid, grade) in enumerate(rows, 1):
        if i % 500 == 0:
            print(f"  진행 {i}/{len(rows)} (ok {ok}, miss {miss}, fail {fail})")
        immich_path = immich_idx.get(aid)
        if not immich_path:
            miss += 1
            continue
        if refresh_view_link(aid, immich_path, grade):
            ok += 1
        else:
            fail += 1

    print(f"\n📊 결과: ok={ok} miss={miss} fail={fail}")
    print()
    print("=== immich-views/{GRADE}/ 폴더 ===")
    for g in sorted(by_grade.keys()):
        d = VIEWS_HOST / g
        if d.exists():
            cnt = len(list(d.iterdir()))
            print(f"  {g:8s}: {cnt} symlinks")


if __name__ == "__main__":
    main()
