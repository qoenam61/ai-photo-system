"""Mac Photos.app TRASH 자동 정리 — iPhone iCloud 동기 통한 간접 정리.

사용자 명시 (2026-05-05): iPhone 단축어 매칭 한계로 Mac AppleScript 자동화 채택.

흐름:
  1. classify-service /cleanup_candidates → asset_ids (verify PASS 자산)
  2. immich-postgres에서 deviceAssetId (PHAsset.localIdentifier) 조회
  3. AppleScript Photos.app으로 매칭 자산 삭제
  4. Photos.app 휴지통 → iCloud 동기 → iPhone Photos에서도 사라짐 (30일 안전망)
  5. cleanup_audit 기록 (device='mac-photos')

trigger:
  launchd plist `~/Library/LaunchAgents/com.photo.cleanup-mac.plist` 매일 04:00.

안전 게이트:
  - classify-service /cleanup_candidates는 verify 4중 검증 PASS만 반환
  - Photos.app 자체 휴지통 30일 보존 (실수 시 복구 가능)
  - iCloud "최근 삭제된 항목" 30일 동기 안전망
  - feedback_protect 자산은 cleanup_candidates에서 자동 제외

Usage:
  PYTHONPATH=. poetry run python scripts/cleanup_photos_mac.py [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import subprocess
import sys
from datetime import datetime

import httpx
import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)
CLASSIFY_URL = os.getenv("CLASSIFY_URL", "http://127.0.0.1:8765")


def fetch_immich_device_ids(asset_ids: list[str]) -> dict[str, str]:
    """immich-postgres에서 asset_id → deviceAssetId 매핑."""
    if not asset_ids:
        return {}
    in_clause = ",".join(f"'{a}'::uuid" for a in asset_ids)
    proc = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "--csv", "-c",
         f"""SELECT id::text, "deviceAssetId" FROM asset
             WHERE id::text IN (SELECT id::text FROM unnest(ARRAY[{in_clause}]) AS id)
               AND "deviceAssetId" IS NOT NULL"""],
        capture_output=True, text=True, check=True, timeout=30,
    )
    rows = list(csv.reader(io.StringIO(proc.stdout)))[1:]  # skip header
    return {row[0]: row[1] for row in rows if len(row) >= 2 and row[1]}


def delete_photo_applescript(device_asset_id: str) -> tuple[bool, str]:
    """Mac Photos.app에서 PHAsset.localIdentifier 매칭 자산 삭제.

    Returns: (success, message)
      "deleted" — 삭제됨
      "not_found" — Mac Photos에 매칭 X (iCloud 미동기 자산)
      "error: ..." — AppleScript 에러
    """
    osascript_code = f'''
with timeout of 60 seconds
  tell application "Photos"
    try
      set targetPhotos to (every media item whose id is "{device_asset_id}")
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


def record_cleanup_audit(
    asset_id: str,
    immich_id: str,
    success: bool,
    reason: str,
    device_deleted_at: str,
) -> None:
    """photo.cleanup_audit 기록 (device='mac-photos')."""
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO photo.cleanup_audit
              (asset_id, immich_id, device, success, reason, device_deleted_at)
            VALUES (%s::uuid, %s, 'mac-photos', %s, %s, %s::timestamptz)
        """, (asset_id, immich_id or None, success, reason, device_deleted_at))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    # 1. cleanup_candidates 조회 (verify PASS 자산)
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
        print("✅ 처리 가능 자산 없음 (cleanup_candidates 응답 비어있음)")
        return

    print(f"📋 cleanup_candidates: {len(items)}장")

    # 2. Immich에서 deviceAssetId 매핑
    asset_ids = [it["asset_id"] for it in items]
    device_id_map = fetch_immich_device_ids(asset_ids)
    print(f"   deviceAssetId 매칭: {len(device_id_map)}/{len(asset_ids)}")

    # 3. AppleScript 삭제
    if args.dry_run:
        print("\n💡 dry-run — Photos.app 변경 X")
        for it in items:
            aid = it["asset_id"]
            did = device_id_map.get(aid, "<없음>")
            print(f"  {aid[:8]} → {did}")
        return

    print("\n🗑  Mac Photos.app 정리 진행 ...")
    success = not_found = error = no_device_id = 0
    now = datetime.now().isoformat()
    for it in items:
        aid = it["asset_id"]
        immich_id = it.get("immich_id", "")
        device_id = device_id_map.get(aid)
        if not device_id:
            no_device_id += 1
            continue
        ok, msg = delete_photo_applescript(device_id)
        if ok:
            record_cleanup_audit(aid, immich_id, True,
                                 "mac_photos_applescript_delete", now)
            success += 1
            print(f"  ✓ {aid[:8]} {device_id[:8]}... deleted")
        elif msg == "not_found":
            not_found += 1
            print(f"  ⏭  {aid[:8]} not_in_mac_photos (iCloud 미동기)")
        else:
            error += 1
            record_cleanup_audit(aid, immich_id, False, msg, now)
            print(f"  ✗ {aid[:8]} {msg}")

    print(f"\n📊 결과: ok={success} / not_found={not_found} / "
          f"error={error} / no_device_id={no_device_id}")
    print(f"   → iCloud 동기 자동 → iPhone Photos에서도 사라짐 (30일 안전망)")


if __name__ == "__main__":
    main()
