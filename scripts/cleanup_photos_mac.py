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


def delete_photo_applescript(uuid: str) -> tuple[bool, str]:
    """AppleScript Photos.app delete by uuid + /L0/001 접미.

    AppleScript injection 방어: UUID 형식만 통과 (NC-3).
    """
    if not UUID_RE.match(uuid):
        return False, "invalid_uuid"
    photo_id = f"{uuid}/L0/001"
    osascript_code = f'''
with timeout of 60 seconds
  tell application "Photos"
    try
      set targetPhotos to (every media item whose id is "{photo_id}")
      if (count of targetPhotos) > 0 then
        delete targetPhotos
        return "deleted"
      else
        return "not_found"
      end if
    on error e
      return "error: " & e
    end try
  end tell
end timeout
'''
    try:
        r = subprocess.run(
            ["osascript", "-e", osascript_code],
            capture_output=True, text=True, timeout=90,
        )
        if r.returncode != 0:
            return False, f"applescript_fail:{r.stderr.strip()[:80]}"
        msg = r.stdout.strip()
        if msg == "deleted":
            return True, "deleted"
        if msg == "not_found":
            return False, "not_found"
        return False, msg
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, f"exception:{type(e).__name__}"


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
    args = parser.parse_args()

    # 1. cleanup_candidates 조회
    try:
        r = httpx.get(
            f"{CLASSIFY_URL}/cleanup_candidates",
            params={"grades": "TRASH", "min_age_days": 0, "limit": args.limit},
            timeout=120,
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

    print("\n🗑  Mac Photos.app 정리 ...")
    success = not_found = no_meta = error = 0
    now = datetime.now().isoformat()
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
        ok, msg = delete_photo_applescript(uuid)
        if ok:
            record_audit(aid, immich_id, True,
                         f"mac_photos_delete:{filename}", now)
            success += 1
            print(f"  ✓ {aid[:8]} {filename} → deleted")
        else:
            error += 1
            record_audit(aid, immich_id, False, msg, now)
            print(f"  ✗ {aid[:8]} {filename} → {msg}")

    print(f"\n📊 ok={success} / 미매칭(Mac에없음)={not_found} / "
          f"meta없음={no_meta} / error={error}")
    print(f"   → Mac 휴지통 → iCloud → iPhone (30일 안전망)")


if __name__ == "__main__":
    main()
