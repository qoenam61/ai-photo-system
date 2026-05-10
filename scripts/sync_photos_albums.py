"""Mac Photos.app 4개 등급 앨범 자동 동기 (iCloud 백업 대상만).

사용자 명시 (2026-05-05 정정): iCloud 백업 = 고퀄 등급만.
  - BEST: 일반 인물 / 풍경·사물 좋은 컷
  - EVENT: 얼굴 보이는 사람 3+ 또는 행사 (웨딩/돌잔치/생일 등)
  - EVENT-L: Long (영상 ≥3초) + dedup_demoted (결혼식 영상 등 보존 가치)
  - MEMORY+: 사람 + 화질 OK

제외: FOOD, MEMORY-, NORMAL, TRASH (HDD 보존만, iCloud 동기 X)
TRASH 정리는 scripts/cleanup_photos_mac.py가 독립적으로 처리.

흐름:
  1. photo.classification 자산 조회 (sync 미완료, 4등급만)
  2. Immich (originalFileName + fileCreatedAt) 매핑
  3. osxphotos PhotosDB → filename + date 매칭 → photo.uuid
  4. AppleScript Photos.app album add (배치 1회)
  5. DB photo.classification.synced_to_mac_album_at 갱신 (idempotent)

trigger: launchd `com.photo.sync-albums` (매일 03:35)

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

# iCloud 백업 대상 4등급만 동기 (사용자 명시 2026-05-05 정정 + 2026-05-09 안3 분할).
# 보존 = +등급만 (자녀 OR 본식 영상). -등급은 HDD only — iCloud 50GB 한도 유지.
# 제외 등급(EVENT-/EVENT-L-/FOOD/MEMORY-/NORMAL/TRASH)은 HDD 보존 only.
GRADE_ALBUMS = {
    "EVENT+":   "⭐ EVENT",     # 자녀 등장 행사
    "EVENT-L+": "⭐ EVENT-L",   # 본식 영상 + 자녀 행사 (long form)
    "BEST":     "✦ BEST",
    "MEMORY+":  "◆ MEMORY+",
}

# 2026-05-11 ABCD β: base album + sub-album 동시 동기 (사용자 명시).
# (grade, sub_category) → sub-album 이름. None이면 sub-album 미생성.
SUB_ALBUMS: dict[tuple[str, str], str] = {
    ("BEST", "portrait"):          "✦ BEST (Portrait)",
    ("BEST", "landscape"):         "✦ BEST (Landscape)",
    ("BEST", "unknown"):           "✦ BEST (Unverified)",
    ("EVENT+", "family"):          "⭐ EVENT (Family)",
    ("EVENT+", "wedding"):         "⭐ EVENT (Wedding)",
    ("EVENT-L+", "wedding"):       "⭐ EVENT-L (Wedding)",
    ("EVENT-L+", "family"):        "⭐ EVENT-L (Family)",
    ("EVENT-L+", "wedding_video"): "⭐ EVENT-L (Wedding Video)",
    ("MEMORY+", "image"):          "◆ MEMORY+ (Photo)",
    ("MEMORY+", "video"):          "◆ MEMORY+ (Video)",
}


def fetch_targets(only_unsynced: bool, limit: int) -> list[tuple]:
    """동기 대상: (asset_id, grade) — iCloud 백업 4등급만.

    필터:
      - grade IN GRADE_ALBUMS (BEST/EVENT/EVENT-L/MEMORY+)
      - cleanup_audit success 자산 제외 (이미 정리됨)
      - only_unsynced=True 시 미동기 자산만
    """
    grades = list(GRADE_ALBUMS.keys())
    where_unsynced = ""
    if only_unsynced:
        where_unsynced = ("AND (synced_to_mac_album_at IS NULL OR "
                          "synced_to_mac_album_at < updated_at)")
    sql = f"""
        SELECT c.asset_id::text, c.grade, COALESCE(c.sub_category, '')
        FROM photo.classification c
        WHERE c.grade = ANY(%s)
          AND NOT EXISTS (
            SELECT 1 FROM photo.cleanup_audit a
            WHERE a.asset_id = c.asset_id AND a.success
          )
        {where_unsynced}
        ORDER BY c.classified_at DESC
    """
    if limit > 0:
        sql += f" LIMIT {limit}"
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(sql, (grades,))
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


BATCH_CHUNK = 50  # AppleScript 안정성 — Photos.app `add` 작업 AppleEvent timeout 회피


def _album_add_chunk(album_name: str, uuids: list[str]) -> tuple[int, str | None]:
    """AppleScript chunk 1개 호출. (added, error)."""
    if not uuids:
        return 0, None

    photo_ids = [f"{u}/L0/001" for u in uuids]
    id_list = ", ".join(f'"{pid}"' for pid in photo_ids)

    # `media item id "X"` 직접 조회 — O(1) 룩업.
    # `whose id is in {...}` 는 Photos.app이 specifier 유형 변환 거부 (-1700).
    osascript_code = f'''
with timeout of 600 seconds
  tell application "Photos"
    set photosFound to {{}}
    repeat with theID in {{{id_list}}}
      try
        set p to media item id theID
        set end of photosFound to p
      end try
    end repeat

    try
      set targetAlbum to album "{album_name}"
    on error
      set targetAlbum to make new album named "{album_name}"
    end try

    if (count of photosFound) > 0 then
      add photosFound to targetAlbum
    end if

    return (count of photosFound) as text
  end tell
end timeout
'''
    try:
        r = subprocess.run(
            ["osascript", "-e", osascript_code],
            capture_output=True, text=True, timeout=620,
        )
        if r.returncode != 0:
            return 0, f"applescript:{r.stderr.strip()[:120]}"
        return int(r.stdout.strip() or 0), None
    except subprocess.TimeoutExpired:
        return 0, "timeout"
    except Exception as e:
        return 0, f"{type(e).__name__}:{e}"


def album_add_batch(album_name: str, uuids: list[str]) -> dict:
    """앨범 추가 — BATCH_CHUNK 단위 분할. chunk별 성공·실패 추적.

    반환:
      processed   — 성공 chunk의 added 합계
      synced_uuids — 성공 chunk에 포함된 UUIDs (DB synced 마킹 대상)
      failed_count — 실패 chunk의 UUID 수 (재시도 대상)
      error       — 마지막 오류 메시지
    """
    if not uuids:
        return {"processed": 0, "synced_uuids": [], "failed_count": 0}

    total_added = 0
    synced_uuids: list[str] = []
    failed_count = 0
    last_err: str | None = None

    for i in range(0, len(uuids), BATCH_CHUNK):
        chunk = uuids[i:i + BATCH_CHUNK]
        added, err = _album_add_chunk(album_name, chunk)
        if err is None:
            total_added += added
            synced_uuids.extend(chunk)
        else:
            failed_count += len(chunk)
            last_err = err

    out: dict = {
        "processed": total_added,
        "synced_uuids": synced_uuids,
        "failed_count": failed_count,
        "not_found": len(uuids) - total_added - failed_count,
    }
    if last_err:
        out["error"] = last_err
    return out


def rebuild_albums() -> dict:
    """4개 앨범 삭제 + synced_to_mac_album_at 리셋 → 다음 sync에서 새로 생성.

    AppleScript Photos.app의 앨범 멤버십 제거 한계 우회 (delete album + recreate).
    """
    album_names = list(GRADE_ALBUMS.values())
    album_list = ", ".join(f'"{n}"' for n in album_names)
    osascript_code = f'''
with timeout of 600 seconds
  tell application "Photos"
    set deleted to 0
    repeat with theName in {{{album_list}}}
      try
        delete album theName
        set deleted to deleted + 1
      on error
        -- 앨범 없음 — skip
      end try
    end repeat
    return deleted as text
  end tell
end timeout
'''
    deleted = 0
    err: str | None = None
    try:
        r = subprocess.run(
            ["osascript", "-e", osascript_code],
            capture_output=True, text=True, timeout=620,
        )
        if r.returncode == 0:
            deleted = int(r.stdout.strip() or 0)
        else:
            err = f"applescript:{r.stderr.strip()[:120]}"
    except subprocess.TimeoutExpired:
        err = "timeout"
    except Exception as e:
        err = f"{type(e).__name__}:{e}"

    # DB 리셋 — 4 등급 자산 모두 unsynced 상태로
    grades = list(GRADE_ALBUMS.keys())
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE photo.classification
            SET synced_to_mac_album_at = NULL
            WHERE grade = ANY(%s)
        """, (grades,))
        reset_count = cur.rowcount

    return {"albums_deleted": deleted, "db_reset": reset_count, "error": err}


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
    parser.add_argument("--rebuild-albums", action="store_true",
                        help="4개 앨범 삭제 + synced 리셋 후 처음부터 재생성 "
                             "(dedup 후 정합성 회복용)")
    args = parser.parse_args()

    ensure_synced_column()

    if args.rebuild_albums:
        if args.dry_run:
            print("⚠️  --rebuild-albums + --dry-run: 통계만 (앨범 삭제 X)")
        else:
            print("🔄 앨범 재구축 — 4개 앨범 삭제 + synced 리셋 ...")
            r = rebuild_albums()
            print(f"   삭제={r['albums_deleted']} / DB synced 리셋={r['db_reset']}"
                  f"{' / err=' + (r['error'] or '') if r.get('error') else ''}")
            if r.get("error"):
                print("   ⚠️  앨범 삭제 일부 실패 — 계속 진행")

    targets = fetch_targets(only_unsynced=not args.all, limit=args.limit)
    print(f"📋 동기 대상: {len(targets)}장 ({'전수' if args.all else 'unsynced'})")
    if not targets:
        print("✅ 동기 대상 없음")
        return

    asset_ids = [a for a, _, _ in targets]
    grade_map = {a: g for a, g, _ in targets}
    sub_map = {a: s for a, _, s in targets}  # 2026-05-11 ABCD β

    print("🔍 Immich 인덱스 + Mac Photos 인덱스 ...")
    immich_idx = fetch_immich_index()
    # asset_ids 중 immich에 있는 것만 metadata 매핑
    meta_map = {a: immich_idx[a] for a in asset_ids if a in immich_idx}
    db = osxphotos.PhotosDB()
    idx = build_filename_index(db)
    print(f"   immich active: {len(immich_idx)} / matched: {len(meta_map)}/{len(asset_ids)}")
    print(f"   Mac Photos: {len(db.photos())}")

    # asset_id → (mac_uuid, grade) 매칭. base album + sub-album 동시 (β).
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
        sub = sub_map.get(aid, "")
        # base album
        base_album = GRADE_ALBUMS.get(grade)
        if base_album:
            by_album[base_album].append((aid, mac_uuid))
        # sub-album (2026-05-11 ABCD β)
        sub_album = SUB_ALBUMS.get((grade, sub))
        if sub_album:
            by_album[sub_album].append((aid, mac_uuid))

    matched_unique = len({u for items in by_album.values() for _, u in items})
    matched_album_ops = sum(len(v) for v in by_album.values())
    print(f"\n📊 매칭: {matched_unique}장 (앨범 추가 작업 {matched_album_ops}건) / "
          f"미매칭(Mac에없음): {no_match} / meta없음: {no_meta}")

    if args.dry_run:
        print("\n💡 dry-run — Mac Photos 변경 X")
        for album, items in by_album.items():
            print(f"  {album}: {len(items)}장")
        return

    # 앨범별 batch 처리 — chunk 단위 성공/실패 추적
    print("\n📁 Mac Photos 앨범 동기 ...")
    total_added = 0
    total_failed = 0
    for album, items in by_album.items():
        if not items:
            continue
        uuid_to_aid = {u: a for a, u in items}
        uuids = [u for _, u in items]
        r = album_add_batch(album, uuids)
        added = r.get("processed", 0)
        not_found = r.get("not_found", 0)
        failed = r.get("failed_count", 0)
        err = r.get("error")
        synced_uuids = r.get("synced_uuids", [])
        print(f"  {album}: added={added}/{len(uuids)} not_found={not_found}"
              f" failed_chunks={failed}"
              f"{' err=' + err[:80] if err else ''}")
        total_added += added
        total_failed += failed

        # 성공 chunk에 포함된 UUID만 synced 마킹 (실패 chunk는 다음 cron에서 재시도)
        synced_aids = [uuid_to_aid[u] for u in synced_uuids if u in uuid_to_aid]
        if synced_aids:
            mark_synced(synced_aids)

    msg = f"\n📊 총 동기: {total_added}장"
    if total_failed:
        msg += f" / 실패(재시도 대기): {total_failed}장"
    msg += " / iCloud 동기 자동 진행 (수 분~수 시간)"
    print(msg)


if __name__ == "__main__":
    main()
