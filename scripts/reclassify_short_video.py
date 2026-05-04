"""auto_short_video TRASH 자산을 3초 기준으로 재분류.

정책 변경 (사용자 명시 2026-05-04): 5초 → 3초 미만 미만 영상만 TRASH.

  duration < 3.0  → TRASH 유지 (auto_short_video)
  duration >= 3.0 → EVENT-L 환원 (auto_video)
  duration 측정 실패 → 보존 (TRASH 해제, EVENT-L 환원으로 안전 처리)

Usage:
  PYTHONPATH=. poetry run python scripts/reclassify_short_video.py [--dry-run]
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

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)

# Immich originalPath → photo-classify 컨테이너 내부 경로
CONTAINER_MAPPINGS = [
    ("/mnt/external", "/storage/immich-media"),
    ("/usr/src/app/upload", "/storage/immich-uploads"),
]

THRESHOLD = 3.0


def to_container_path(immich_path: str) -> str:
    for src, dst in CONTAINER_MAPPINGS:
        if immich_path.startswith(src):
            return dst + immich_path[len(src):]
    return immich_path


def fetch_target_asset_ids() -> list[str]:
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT asset_id::text FROM photo.classification
            WHERE grade='TRASH' AND grade_source='auto_short_video'
            ORDER BY asset_id
        """)
        return [r[0] for r in cur.fetchall()]


def fetch_immich_video_index() -> dict[str, str]:
    """Immich asset DB에서 type=VIDEO + 활성 자산의 stem → originalPath."""
    proc = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "--csv", "-c",
         """SELECT "originalPath" FROM asset
            WHERE "deletedAt" IS NULL AND type='VIDEO'"""],
        capture_output=True, text=True, check=True,
    )
    rows = [r for r in csv.reader(io.StringIO(proc.stdout)) if r]
    if rows and rows[0][0] == "originalPath":
        rows = rows[1:]
    idx: dict[str, str] = {}
    for row in rows:
        path = row[0]
        stem = Path(path).stem
        idx[stem] = path
    return idx


def get_duration_seconds(container_path: str) -> float:
    try:
        r = subprocess.run(
            ["docker", "exec", "photo-classify",
             "ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1",
             container_path],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except Exception:
        pass
    return -1.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    asset_ids = fetch_target_asset_ids()
    print(f"📼 auto_short_video 자산: {len(asset_ids)}장 (재분류 대상)")
    if not asset_ids:
        return

    print("🔍 Immich VIDEO 인덱스 로드 ...")
    immich_idx = fetch_immich_video_index()
    print(f"   Immich VIDEO active: {len(immich_idx)}장")

    counts: Counter[str] = Counter()
    keep_trash: list[str] = []   # < 3.0초
    promote: list[tuple[str, float]] = []  # >= 3.0초 → EVENT-L 환원
    missing: list[str] = []

    for i, aid in enumerate(asset_ids, 1):
        if i % 50 == 0:
            print(f"  진행 {i}/{len(asset_ids)} (TRASH 유지 {len(keep_trash)}, 환원 {len(promote)})")
        path = immich_idx.get(aid)
        if not path:
            missing.append(aid)
            counts["immich_no_match"] += 1
            continue
        cont = to_container_path(path)
        dur = get_duration_seconds(cont)
        if dur < 0:
            counts["ffprobe_fail"] += 1
            promote.append((aid, dur))   # 측정 실패 → 안전을 위해 환원
            continue
        if dur < THRESHOLD:
            keep_trash.append(aid)
            counts["lt_3s"] += 1
        else:
            promote.append((aid, dur))
            counts["ge_3s"] += 1

    print()
    print(f"📊 분포:")
    for k, v in counts.most_common():
        print(f"  {k}: {v}")
    print()
    print(f"🔻 < 3.0초 (TRASH 유지): {len(keep_trash)}장")
    print(f"🔼 >= 3.0초 또는 측정 실패 (EVENT-L 환원): {len(promote)}장")
    if missing:
        print(f"⚠️  Immich 매칭 실패: {len(missing)}장")
        for m in missing[:5]:
            print(f"     {m[:8]}")

    if args.dry_run:
        print("\n(dry-run — DB 변경 없음)")
        return

    if promote:
        promote_ids = [aid for aid, _ in promote]
        with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE photo.classification
                SET grade='EVENT-L', grade_source='auto_video', updated_at=NOW()
                WHERE asset_id = ANY(%s::uuid[])
            """, (promote_ids,))
        print(f"✅ {len(promote)}장 EVENT-L/auto_video 환원 완료")

    print(f"✅ {len(keep_trash)}장 TRASH 유지 — cleanup_enqueue 후속 처리 가능")


if __name__ == "__main__":
    main()
