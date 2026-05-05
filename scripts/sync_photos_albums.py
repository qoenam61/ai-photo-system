"""Mac Photos.app 8개 등급 앨범 자동 동기.

사용자 명시 (2026-05-05): Mac Photos.app에 등급별 Manual Album 자동 생성 +
사진 추가. iCloud 동기로 iPhone/iPad에 자동 표시.

흐름:
  1. photo.classification 자산 조회 (sync 미완료)
  2. Immich (originalFileName + fileCreatedAt) 매핑
  3. osxphotos PhotosDB → filename + date 매칭 → photo.uuid
  4. tools/photos_cli album-add "{ALBUM}" UUID... batch 호출
  5. DB photo.classification.synced_to_mac_album_at 갱신 (idempotent)

8개 앨범 (CLAUDE.md "iCloud 보존 등급"):
  ⭐ EVENT, ⭐ EVENT-L, ✦ BEST, 🍽 FOOD,
  ◆ MEMORY+, ◇ MEMORY-, ○ NORMAL, 🗑 TRASH

trigger: launchd `com.photo.sync-albums` (매일 03:35, cleanup 후 docker restart 전)

Usage:
  PYTHONPATH=. poetry run python scripts/sync_photos_albums.py [--dry-run] [--limit N] [--all]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import osxphotos
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
DATE_TOL = timedelta(seconds=2)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PHOTOS_CLI = PROJECT_ROOT / "tools" / "photos_cli"

GRADE_ALBUMS = {
    "EVENT":   "⭐ EVENT",
    "EVENT-L": "⭐ EVENT-L",
    "BEST":    "✦ BEST",
    "FOOD":    "🍽 FOOD",
    "MEMORY+": "◆ MEMORY+",
    "MEMORY-": "◇ MEMORY-",
    "NORMAL":  "○ NORMAL",
    "TRASH":   "🗑 TRASH",
}


def fetch_targets(only_unsynced: bool, limit: int) -> list[tuple]:
    """동기 대상: (asset_id, grade).

    cleanup_audit success 자산 제외 (이미 정리됨 — Immich에서 deletedAt 표시).
    """
    where_unsynced = ""
    if only_unsynced:
        where_unsynced = ("AND (synced_to_mac_album_at IS NULL OR "
                          "synced_to_mac_album_at < updated_at)")
    sql = f"""
        SELECT c.asset_id::text, c.grade
        FROM photo.classification c
        WHERE NOT EXISTS (
            SELECT 1 FROM photo.cleanup_audit a
            WHERE a.asset_id = c.asset_id AND a.success
        )
        {where_unsynced}
        ORDER BY c.classified_at DESC
    """
    if limit > 0:
        sql += f" LIMIT {limit}"
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def fetch_immich_index() -> dict[str, tuple[str, datetime]]:
    """Immich 전체 active asset 인덱스: originalPath stem → (filename, ts).

    photo.classification.asset_id == originalPath stem (UUID).
    Immich asset.id는 다른 UUID이므로 stem 매칭 필수.
    """
    proc = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "--csv", "-c",
         """SELECT "originalPath", "originalFileName", "fileCreatedAt"
            FROM asset WHERE "deletedAt" IS NULL"""],
        capture_output=True, text=True, check=True, timeout=120,
    )
    rows = list(csv.reader(io.StringIO(proc.stdout)))[1:]
    out: dict[str, tuple[str, datetime]] = {}
    for row in rows:
        if len(row) < 3:
            continue
        stem = Path(row[0]).stem
        try:
            ts = datetime.fromisoformat(row[2].replace(" ", "T"))
        except ValueError:
            continue
        out[stem] = (row[1], ts)
    return out


def build_filename_index(db: osxphotos.PhotosDB) -> dict[str, list[tuple]]:
    idx: dict[str, list[tuple]] = {}
    for p in db.photos():
        if not p.original_filename or p.date is None:
            continue
        idx.setdefault(p.original_filename, []).append((p.date, p.uuid))
    return idx


def find_mac_uuid(idx: dict, filename: str, ts: datetime) -> str | None:
    cands = idx.get(filename)
    if not cands:
        return None
    for d, uuid in cands:
        if abs((d - ts).total_seconds()) <= DATE_TOL.total_seconds():
            return uuid
    return None


def album_add_batch(album_name: str, uuids: list[str]) -> dict:
    """photos_cli album-add 호출."""
    if not uuids:
        return {"processed": 0}
    try:
        r = subprocess.run(
            [str(PHOTOS_CLI), "album-add", album_name, *uuids],
            capture_output=True, text=True, timeout=120,
        )
        if r.stdout.strip():
            return json.loads(r.stdout.strip())
        return {"processed": 0, "error": r.stderr.strip()[:80]}
    except Exception as e:
        return {"processed": 0, "error": f"{type(e).__name__}:{e}"}


def mark_synced(asset_ids: list[str]) -> None:
    if not asset_ids:
        return
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE photo.classification
            SET synced_to_mac_album_at = NOW()
            WHERE asset_id = ANY(%s::uuid[])
        """, (asset_ids,))


def ensure_synced_column() -> None:
    """photo.classification.synced_to_mac_album_at 컬럼 자동 생성."""
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            ALTER TABLE photo.classification
            ADD COLUMN IF NOT EXISTS synced_to_mac_album_at timestamptz
        """)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="0=무제한")
    parser.add_argument("--all", action="store_true",
                        help="전수 재동기 (synced 무시)")
    args = parser.parse_args()

    ensure_synced_column()

    targets = fetch_targets(only_unsynced=not args.all, limit=args.limit)
    print(f"📋 동기 대상: {len(targets)}장 ({'전수' if args.all else 'unsynced'})")
    if not targets:
        print("✅ 동기 대상 없음")
        return

    asset_ids = [a for a, _ in targets]
    grade_map = {a: g for a, g in targets}

    print("🔍 Immich 인덱스 + Mac Photos 인덱스 ...")
    immich_idx = fetch_immich_index()
    # asset_ids 중 immich에 있는 것만 metadata 매핑
    meta_map = {a: immich_idx[a] for a in asset_ids if a in immich_idx}
    db = osxphotos.PhotosDB()
    idx = build_filename_index(db)
    print(f"   immich active: {len(immich_idx)} / matched: {len(meta_map)}/{len(asset_ids)}")
    print(f"   Mac Photos: {len(db.photos())}")

    # asset_id → (mac_uuid, grade) 매칭
    by_album: dict[str, list[tuple[str, str]]] = defaultdict(list)
    no_match = 0
    no_meta = 0
    for aid in asset_ids:
        meta = meta_map.get(aid)
        if not meta:
            no_meta += 1
            continue
        filename, ts = meta
        mac_uuid = find_mac_uuid(idx, filename, ts)
        if not mac_uuid:
            no_match += 1
            continue
        grade = grade_map[aid]
        album_name = GRADE_ALBUMS.get(grade)
        if album_name:
            by_album[album_name].append((aid, mac_uuid))

    matched = sum(len(v) for v in by_album.values())
    print(f"\n📊 매칭: {matched}장 / 미매칭(Mac에없음): {no_match} / meta없음: {no_meta}")

    if args.dry_run:
        print("\n💡 dry-run — Mac Photos 변경 X")
        for album, items in by_album.items():
            print(f"  {album}: {len(items)}장")
        return

    # 앨범별 batch 처리
    print("\n📁 Mac Photos 앨범 동기 ...")
    total_added = 0
    for album, items in by_album.items():
        if not items:
            continue
        uuids = [u for _, u in items]
        r = album_add_batch(album, uuids)
        added = r.get("processed", 0)
        not_found = r.get("not_found", 0)
        err = r.get("error")
        print(f"  {album}: added={added}/{len(uuids)} not_found={not_found}"
              f"{' err=' + err if err else ''}")
        total_added += added

        # 권한 거부 시 synced 표시 X (다음 시도 가능)
        if err and "권한" in err:
            print("    ⚠️  권한 미부여 — synced 표시 보류")
            continue
        # synced 표시 (실패도 표시 — 다음 시도 안 함)
        synced_aids = [a for a, _ in items]
        mark_synced(synced_aids)

    print(f"\n📊 총 동기: {total_added}장 / iCloud 동기 자동 진행 (수 분~수 시간)")


if __name__ == "__main__":
    main()
