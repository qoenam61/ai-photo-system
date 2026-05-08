"""Mac Photos.app 자동 정리 — PhotoCleanup.app 번들 (PhotoKit Framework).

사용자 명시 (2026-05-06): n8n 자동화 — PhotoKit .app 번들로 권한 영구 부여.

PhotoCleanup.app 위치: ~/Applications/PhotoCleanup.app
  - bundle ID: com.jwhome.photocleanup
  - TCC 권한: 1회 부여 (open -W로 popup 트리거)
  - 호출: open -W -a PhotoCleanup --args delete --input <FILE> --output <FILE>

AppleScript는 media item delete 미지원 → PhotoKit Framework 사용.

흐름:
  1. classify-service /cleanup_candidates → asset_ids (verify PASS, 4중 검증)
  2. immich-postgres → (asset_id, originalFileName, fileCreatedAt)
  3. osxphotos PhotosDB → (filename, date) 매칭 → photo.uuid
  4. PhotoCleanup.app delete batch → PhotoKit 실삭제
  5. cleanup_audit device='mac-photos' 기록
  6. Mac 휴지통 → iCloud 동기 → iPhone 휴지통 (30일 안전망)

trigger: launchd `com.photo.cleanup-mac` (매일 04:15 KST)

Usage:
  PYTHONPATH=. poetry run python scripts/cleanup_photos_mac.py [--dry-run] [--limit N] [--grades ...]
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


PHOTO_CLEANUP_APP = "/Users/jw-home/Applications/PhotoCleanup.app"
# 2026-05-08: 200장 batch는 PhotoKit semaphore.wait() hang 빈도 높음 → 50으로 강등
BATCH_CHUNK = 50


def delete_via_meta_fallback(
    entries: list[tuple[str, str, datetime]],
) -> tuple[int, int, str | None]:
    """2026-05-08 P0-C: osxphotos 매칭 실패 자산을 PhotoCleanup delete-by-meta로 직접 매칭+삭제.

    osxphotos PhotosDB는 iCloud-only 자산을 인덱싱 못하지만, PHAsset.fetchAssets는 OK.
    entries: [(asset_id, filename, fileCreatedAt), ...]
    Returns: (processed, failed, last_error).
    """
    import json as _json
    import tempfile

    if not entries:
        return 0, 0, None

    total_proc = total_fail = 0
    last_err: str | None = None

    for i in range(0, len(entries), BATCH_CHUNK):
        chunk = entries[i:i + BATCH_CHUNK]
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".tsv"
        ) as fin:
            for _, filename, ts in chunk:
                fin.write(f"{filename}\t{ts.isoformat()}\n")
            in_path = fin.name
        out_path = in_path + ".out"

        try:
            subprocess.run(
                ["open", "-W", "-a", PHOTO_CLEANUP_APP,
                 "--args", "delete-by-meta",
                 "--input", in_path, "--output", out_path],
                capture_output=True, text=True, timeout=900,
            )
            try:
                with open(out_path) as f:
                    res = _json.load(f)
                total_proc += res.get("processed", 0)
                total_fail += res.get("failed", 0) + res.get("not_found", 0)
                if res.get("error"):
                    last_err = res["error"]
            except (FileNotFoundError, _json.JSONDecodeError):
                total_fail += len(chunk)
                last_err = "no_response"
        except Exception as e:
            total_fail += len(chunk)
            last_err = f"{type(e).__name__}:{e}"
        finally:
            for p in (in_path, out_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    return total_proc, total_fail, last_err


def delete_via_photokit(uuids: list[str]) -> tuple[int, int, int, str | None]:
    """PhotoCleanup.app 번들 → PhotoKit Framework 실 삭제.

    open -W -a PhotoCleanup --args delete --input <FILE> --output <FILE>
    .app 번들로 호출해야 TCC 권한이 적용됨 (binary 직접 호출 시 권한 거부).

    반환: (processed, failed, not_found, last_error)
    """
    import json
    import tempfile

    valid = [u for u in uuids if UUID_RE.match(u)]
    skipped = len(uuids) - len(valid)
    if not valid:
        return 0, skipped, 0, "no_valid_uuid" if skipped else None

    total_processed = 0
    total_failed = skipped
    total_not_found = 0
    last_err: str | None = None

    for i in range(0, len(valid), BATCH_CHUNK):
        chunk = valid[i:i + BATCH_CHUNK]
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt"
        ) as fin, tempfile.NamedTemporaryFile(
            mode="r", delete=False, suffix=".json"
        ) as fout:
            for u in chunk:
                fin.write(f"{u}/L0/001\n")
            fin.flush()
            in_path = fin.name
            out_path = fout.name

        try:
            r = subprocess.run(
                ["open", "-W", "-a", PHOTO_CLEANUP_APP,
                 "--args", "delete",
                 "--input", in_path, "--output", out_path],
                capture_output=True, text=True, timeout=900,
            )
            try:
                with open(out_path) as f:
                    res = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                res = {}

            if "error" in res and res.get("processed", 0) == 0:
                total_failed += len(chunk)
                last_err = res["error"]
            else:
                total_processed += res.get("processed", 0)
                total_not_found += res.get("not_found", 0)
                total_failed += res.get("failed", 0)
                if res.get("error"):
                    last_err = res["error"]
        except subprocess.TimeoutExpired:
            total_failed += len(chunk)
            last_err = "timeout"
        except Exception as e:
            total_failed += len(chunk)
            last_err = f"{type(e).__name__}:{e}"
        finally:
            for p in (in_path, out_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    return total_processed, total_failed, total_not_found, last_err


def record_audit(
    asset_id: str, immich_id: str, success: bool, reason: str, ts: str,
    reason_category: str | None = None,
) -> None:
    if reason_category is None:
        reason_category = "mac_photokit_ok" if success else "mac_other_error"
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO photo.cleanup_audit
              (asset_id, immich_id, device, success, reason,
               reason_category, reason_detail, device_deleted_at)
            VALUES (%s::uuid, %s, 'mac-photos', %s, %s, %s, %s, %s::timestamptz)
        """, (asset_id, immich_id or None, success, reason,
              reason_category, reason, ts))


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

    print(f"\n🗑  PhotoCleanup.app PhotoKit 실 삭제 ...")
    now = datetime.now().isoformat()

    # 매칭 결과 수집 — osxphotos UUID 매칭 vs meta-fallback 분리
    matched: list[tuple[str, str, str, str]] = []  # (aid, immich_id, filename, mac_uuid)
    fallback_meta: list[tuple[str, str, str, datetime]] = []  # (aid, immich_id, filename, ts)
    no_meta = 0
    for it in items:
        aid = it["asset_id"]
        immich_id = it.get("immich_id", "")
        meta = meta_map.get(aid)
        if not meta:
            no_meta += 1
            continue
        filename, ts = meta
        uuid = find_mac_photo_uuid(idx, filename, ts)
        if uuid:
            matched.append((aid, immich_id, filename, uuid))
        else:
            # osxphotos에 없음 → PhotoCleanup delete-by-meta fallback (iCloud-only 자산 등)
            fallback_meta.append((aid, immich_id, filename, ts))

    # 1차: PhotoKit UUID batch delete
    uuids = [u for _, _, _, u in matched]
    processed, failed, batch_not_found, err = delete_via_photokit(uuids)

    if processed > 0:
        for aid, immich_id, filename, _ in matched[:processed]:
            record_audit(aid, immich_id, True,
                         f"mac_photos_delete:{filename}", now,
                         reason_category="mac_photokit_ok")

    # 2차: meta-fallback (P0-C 2026-05-08) — iCloud-only 자산 매칭
    fb_processed = fb_failed = 0
    fb_err: str | None = None
    if fallback_meta:
        fb_processed, fb_failed, fb_err = delete_via_meta_fallback(
            [(aid, fn, ts) for aid, _, fn, ts in fallback_meta]
        )
        # delete-by-meta는 batch 단위 결과만 반환 → 처리된 수만큼 audit 기록.
        # 어떤 자산이 매칭됐는지 정확 식별 불가하나, 재호출은 멱등(이미 삭제 → not_found)
        for aid, immich_id, filename, _ in fallback_meta[:fb_processed]:
            record_audit(aid, immich_id, True,
                         f"mac_photos_meta:{filename}", now,
                         reason_category="mac_photokit_meta_ok")

    total_targets = len(items)
    osx_rate = (len(matched) / total_targets * 100) if total_targets else 0.0
    fb_rate = (fb_processed / total_targets * 100) if total_targets else 0.0
    overall_rate = ((processed + fb_processed) / total_targets * 100) if total_targets else 0.0
    print(f"\n📊 osxphotos 매칭: {len(matched)} ({osx_rate:.1f}%) → PhotoKit 삭제 {processed}")
    print(f"   meta-fallback: {len(fallback_meta)} → 삭제 {fb_processed} ({fb_rate:.1f}%)")
    print(f"   합계 삭제율: {overall_rate:.1f}% / no_meta: {no_meta}")
    if err:
        print(f"   PhotoKit 오류: {err}")
    if fb_err:
        print(f"   meta-fallback 오류: {fb_err}")

    # 전체 매칭률(osx + meta-fallback) < 10% 시만 경고 — meta-fallback이 작동하면 정상화됨
    if total_targets >= 10 and overall_rate < 10.0:
        print(f"\n⚠️  합계 삭제율 {overall_rate:.1f}% — PhotoCleanup.app 권한 또는 "
              f"Mac Photos 인덱싱 문제 확인 필요.")

    print(f"\n   → Mac 휴지통 → iCloud 동기 → iPhone 휴지통 (30일 안전망)")


if __name__ == "__main__":
    main()
