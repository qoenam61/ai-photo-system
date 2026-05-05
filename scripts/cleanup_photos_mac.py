"""Mac Photos.app TRASH 자동 정리 — filename + creation date 조합 매칭.

사용자 명시 (2026-05-05):
  iPhone PHAsset.localIdentifier ≠ macOS Photos.app id 한계 발견.
  filename + creation date 조합 매칭으로 우회 (정확도 99.99%, 검증 완료).

흐름:
  1. classify-service /cleanup_candidates → asset_ids (verify PASS)
  2. immich-postgres에서 (asset_id, originalFileName, fileCreatedAt) 조회
  3. osxphotos PhotosDB에서 (filename, date) 매칭 → photo.uuid 추출
  4. AppleScript Photos.app: delete by `<UUID>/L0/001`
  5. cleanup_audit device='mac-photos' 기록
  6. Mac Photos 휴지통 → iCloud 동기 자동 → iPhone Photos 휴지통 (30일 안전망)

trigger: launchd `com.photo.cleanup-mac` (매일 04:15 KST)

Usage:
  PYTHONPATH=. poetry run python scripts/cleanup_photos_mac.py [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

import httpx
import osxphotos
import psycopg
from dotenv import load_dotenv

load_dotenv()

# UUID 정규식 — SQL/AppleScript injection 방어 (NC-2/3)
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)
CLASSIFY_URL = os.getenv("CLASSIFY_URL", "http://127.0.0.1:8765")

# datetime 매칭 허용 오차 (sub-second 차이)
DATE_TOLERANCE = timedelta(seconds=2)


def fetch_immich_metadata(asset_ids: list[str]) -> dict[str, tuple[str, datetime]]:
    """asset_id → (originalFileName, fileCreatedAt) 매핑.

    photo.classification.asset_id == originalPath stem (UUID).
    Immich asset.id (DB primary key)와 다르므로 stem 매칭 사용.
    """
    asset_ids = [a for a in asset_ids if UUID_RE.match(a)]
    if not asset_ids:
        return {}

    # Immich 전체 active asset 인덱스 (originalPath stem → metadata)
    proc = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "--csv", "-c",
         """SELECT "originalPath", "originalFileName", "fileCreatedAt"
            FROM asset WHERE "deletedAt" IS NULL"""],
        capture_output=True, text=True, check=True, timeout=120,
    )
    rows = list(csv.reader(io.StringIO(proc.stdout)))[1:]

    from pathlib import Path as _Path
    full_idx: dict[str, tuple[str, datetime]] = {}
    for row in rows:
        if len(row) < 3:
            continue
        stem = _Path(row[0]).stem
        try:
            ts = datetime.fromisoformat(row[2].replace(" ", "T"))
        except ValueError:
            continue
        full_idx[stem] = (row[1], ts)

    # asset_ids 매칭만 추출
    return {a: full_idx[a] for a in asset_ids if a in full_idx}


def build_filename_index(
    db: osxphotos.PhotosDB,
) -> dict[str, list[tuple[datetime, str]]]:
    """filename → [(date, uuid), ...] 인덱스. 한 번 빌드, O(1) 조회."""
    idx: dict[str, list[tuple[datetime, str]]] = {}
    for p in db.photos():
        if not p.original_filename or p.date is None:
            continue
        idx.setdefault(p.original_filename, []).append((p.date, p.uuid))
    return idx


def find_mac_photo_uuid(
    idx: dict[str, list[tuple[datetime, str]]],
    filename: str,
    fileCreatedAt: datetime,
) -> str | None:
    """filename + date 조합으로 photo.uuid 매칭."""
    candidates = idx.get(filename)
    if not candidates:
        return None
    target = fileCreatedAt
    for d, uuid in candidates:
        if abs((d - target).total_seconds()) <= DATE_TOLERANCE.total_seconds():
            return uuid
    return None


TODELETE_ALBUM = "🗑 ToDelete"
BATCH_CHUNK = 50  # AppleScript 안정 한계


def add_to_todelete_album_batch(uuids: list[str]) -> tuple[int, int, str | None]:
    """🗑 ToDelete 앨범에 batch 추가 (AppleScript delete 한계 우회).

    Photos.app AppleScript는 media item delete 미지원 (`album/folder` 유형만).
    대안: 🗑 ToDelete 앨범에 모음 → 사용자가 Mac Photos UI에서 Cmd+A+Delete로 일괄 처리.

    반환: (added, failed, last_error)
    """
    valid = [u for u in uuids if UUID_RE.match(u)]
    if not valid:
        return 0, len(uuids) - len(valid), "no_valid_uuid"

    total_added = 0
    total_failed = 0
    last_err: str | None = None

    for i in range(0, len(valid), BATCH_CHUNK):
        chunk = valid[i:i + BATCH_CHUNK]
        photo_ids = [f"{u}/L0/001" for u in chunk]
        id_list = ", ".join(f'"{pid}"' for pid in photo_ids)

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
      set targetAlbum to album "{TODELETE_ALBUM}"
    on error
      set targetAlbum to make new album named "{TODELETE_ALBUM}"
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
                total_failed += len(chunk)
                last_err = f"applescript:{r.stderr.strip()[:120]}"
                continue
            added = int(r.stdout.strip() or 0)
            total_added += added
        except subprocess.TimeoutExpired:
            total_failed += len(chunk)
            last_err = "timeout"
        except Exception as e:
            total_failed += len(chunk)
            last_err = f"{type(e).__name__}:{e}"

    return total_added, total_failed, last_err


def record_audit(
    asset_id: str, immich_id: str, success: bool, reason: str, ts: str,
) -> None:
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO photo.cleanup_audit
              (asset_id, immich_id, device, success, reason, device_deleted_at)
            VALUES (%s::uuid, %s, 'mac-photos', %s, %s, %s::timestamptz)
        """, (asset_id, immich_id or None, success, reason, ts))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--grades", type=str, default="TRASH",
                        help="삭제 대상 등급 (콤마 구분). 예: FOOD,MEMORY-,NORMAL,TRASH")
    parser.add_argument("--no-progressive", action="store_true",
                        help="phase5_ready.flag 단계 limit 우회 (사용자 명시 승인 시)")
    parser.add_argument("--min-age-days", type=int, default=0)
    args = parser.parse_args()

    # 1. cleanup_candidates 조회
    try:
        params = {
            "grades": args.grades,
            "min_age_days": args.min_age_days,
            "limit": args.limit,
        }
        if args.no_progressive:
            params["progressive"] = "false"
        r = httpx.get(
            f"{CLASSIFY_URL}/cleanup_candidates",
            params=params,
            timeout=300,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
    except Exception as e:
        print(f"❌ cleanup_candidates 조회 실패: {e}")
        sys.exit(1)

    if not items:
        print("✅ 처리 가능 자산 없음")
        return

    print(f"📋 cleanup_candidates: {len(items)}장")

    # 2. Immich metadata
    asset_ids = [it["asset_id"] for it in items]
    meta_map = fetch_immich_metadata(asset_ids)
    print(f"   Immich metadata: {len(meta_map)}/{len(asset_ids)}")

    # 3. osxphotos 인덱스 (한 번 빌드)
    print("🔍 Mac Photos.app DB 로드 ...")
    db = osxphotos.PhotosDB()
    idx = build_filename_index(db)
    print(f"   Mac Photos: {len(db.photos())}장 / unique filenames: {len(idx)}")

    # 4. 매칭 + 삭제
    if args.dry_run:
        print("\n💡 dry-run — 매칭 시뮬레이션")
        matched = unmatched = no_meta = 0
        for it in items:
            aid = it["asset_id"]
            meta = meta_map.get(aid)
            if not meta:
                no_meta += 1
                continue
            filename, ts = meta
            uuid = find_mac_photo_uuid(idx, filename, ts)
            if uuid:
                matched += 1
                print(f"  ✓ {aid[:8]} {filename} → mac_uuid={uuid[:8]}")
            else:
                unmatched += 1
                print(f"  ⏭  {aid[:8]} {filename} not_in_mac")
        print(f"\n📊 매칭 {matched} / 미매칭 {unmatched} / no_meta {no_meta}")
        return

    print(f"\n🗑  Mac Photos.app — '{TODELETE_ALBUM}' 앨범에 추가 ...")
    print(f"     (AppleScript는 media item 직접 삭제 미지원 — 사용자 수동 정리 필요)")
    now = datetime.now().isoformat()

    # 매칭 결과 수집
    matched: list[tuple[str, str, str, str]] = []  # (aid, immich_id, filename, mac_uuid)
    not_found = no_meta = 0
    for it in items:
        aid = it["asset_id"]
        immich_id = it.get("immich_id", "")
        meta = meta_map.get(aid)
        if not meta:
            no_meta += 1
            continue
        filename, ts = meta
        uuid = find_mac_photo_uuid(idx, filename, ts)
        if not uuid:
            not_found += 1
            continue
        matched.append((aid, immich_id, filename, uuid))

    # batch 추가
    uuids = [u for _, _, _, u in matched]
    added, failed, err = add_to_todelete_album_batch(uuids)

    # cleanup_audit 기록 — added 자산은 success, failed는 audit 없음 (재시도 가능)
    success = 0
    if added > 0:
        # batch는 어떤 UUID가 성공했는지 별도 알 수 없음 → 모두 success 처리
        # (Photos.app은 중복 추가 자동 dedupe — 재시도해도 안전)
        synced_uuids = uuids[:added] if added < len(uuids) else uuids
        synced_set = set(synced_uuids)
        for aid, immich_id, filename, mac_uuid in matched:
            if mac_uuid in synced_set:
                record_audit(aid, immich_id, True,
                             f"mac_photos_todelete:{filename}", now)
                success += 1

    print(f"\n📊 매칭: {len(matched)}장 / 추가: {added} / 실패: {failed}"
          f" / 미매칭: {not_found} / no_meta: {no_meta}")
    if err:
        print(f"   마지막 오류: {err}")
    print(f"\n💡 다음 단계: Mac Photos에서 '{TODELETE_ALBUM}' 앨범 열기"
          f"\n   → Cmd+A (전체 선택) → Cmd+Delete (휴지통 이동)"
          f"\n   → iCloud 자동 동기 → iPhone 휴지통 (30일 안전망)")


if __name__ == "__main__":
    main()
