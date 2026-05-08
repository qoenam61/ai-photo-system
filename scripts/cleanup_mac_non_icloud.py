"""Mac Photos 4등급 외 자산 일괄 정리 — verify 우회.

cleanup_photos_mac.py의 한계 우회:
  /cleanup_candidates는 verify_asset 4중 검증 (DB+Immich+파일+SHA256) 통과 자산만 반환.
  HDD에서 이미 영구삭제된 TRASH 자산은 file_missing → 검증 실패 → Mac에서 영구 미정리.

본 스크립트는 DB photo.classification만으로 Mac 매칭:
  - grade NOT IN (BEST,EVENT,EVENT-L,MEMORY+) — 4등급 외
  - cleanup_audit mac-photos success 없음 (이미 처리 X)
  - photo.feedback protect 없음
  - osxphotos PhotosDB로 (filename, date) 매칭
  - PhotoCleanup.app PhotoKit 실 삭제
  - cleanup_audit 기록

iPhone 30일 안전망 + HDD 영구 보존 (TRASH 외) 정책 유지.

Usage:
  PYTHONPATH=. poetry run python scripts/cleanup_mac_non_icloud.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
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

PHOTO_CLEANUP_APP = "/Users/jw-home/Applications/PhotoCleanup.app"
DATE_TOL = timedelta(seconds=2)
NON_ICLOUD_GRADES = ("FOOD", "MEMORY-", "NORMAL", "TRASH")
# 2026-05-08: PhotoCleanup.app delete-by-meta가 200장 batch에서 hang 빈도 높음.
# 50장으로 줄여 PhotoKit semaphore.wait() 무응답 회피.
BATCH_CHUNK = 50


def delete_via_meta_fallback(
    entries: list[tuple[str, str, datetime]],
) -> tuple[int, int, str | None]:
    """2026-05-08 P0-C: osxphotos 매칭 실패 자산을 PhotoCleanup delete-by-meta 직접 매칭+삭제."""
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
                capture_output=True, text=True, timeout=1800,
            )
            try:
                with open(out_path) as f:
                    res = json.load(f)
                total_proc += res.get("processed", 0)
                total_fail += res.get("failed", 0) + res.get("not_found", 0)
                if res.get("error"):
                    last_err = res["error"]
            except (FileNotFoundError, json.JSONDecodeError):
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


def fetch_targets(limit: int) -> list[tuple[str, str]]:
    """4등급 외 자산 中 Mac 미처리. (asset_id, grade)."""
    sql = """
        SELECT c.asset_id::text, c.grade
        FROM photo.classification c
        WHERE c.grade = ANY(%s)
          AND NOT EXISTS (
            SELECT 1 FROM photo.cleanup_audit a
            WHERE a.asset_id = c.asset_id
              AND a.success AND a.device = 'mac-photos'
          )
          AND NOT EXISTS (
            SELECT 1 FROM photo.feedback f
            WHERE f.asset_id = c.asset_id
              AND f.feedback_type IN ('protect', 'restored')
          )
        ORDER BY c.classified_at DESC
    """
    if limit > 0:
        sql += f" LIMIT {limit}"
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(sql, (list(NON_ICLOUD_GRADES),))
        return cur.fetchall()


def fetch_immich_metadata(asset_ids: list[str]) -> dict[str, tuple[str, datetime]]:
    """asset_id → (originalFileName, fileCreatedAt)."""
    if not asset_ids:
        return {}
    proc = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "--csv", "-c",
         """SELECT "originalPath", "originalFileName", "fileCreatedAt"
            FROM asset"""],
        capture_output=True, text=True, check=True, timeout=120,
    )
    rows = list(csv.reader(io.StringIO(proc.stdout)))[1:]
    aid_set = set(asset_ids)
    out: dict[str, tuple[str, datetime]] = {}
    for row in rows:
        if len(row) < 3:
            continue
        stem = Path(row[0]).stem
        if stem not in aid_set:
            continue
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


def delete_via_photokit(uuids: list[str]) -> tuple[int, int, str | None]:
    """PhotoCleanup.app batch delete. (processed, failed, error)."""
    if not uuids:
        return 0, 0, None
    total_proc = total_fail = 0
    last_err: str | None = None

    for i in range(0, len(uuids), BATCH_CHUNK):
        chunk = uuids[i:i + BATCH_CHUNK]
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt"
        ) as fin:
            for u in chunk:
                fin.write(f"{u}/L0/001\n")
            in_path = fin.name
        out_path = in_path + ".out"

        try:
            subprocess.run(
                ["open", "-W", "-a", PHOTO_CLEANUP_APP,
                 "--args", "delete",
                 "--input", in_path, "--output", out_path],
                capture_output=True, text=True, timeout=1800,
            )
            try:
                with open(out_path) as f:
                    res = json.load(f)
                total_proc += res.get("processed", 0)
                total_fail += res.get("failed", 0)
                if res.get("error"):
                    last_err = res["error"]
            except (FileNotFoundError, json.JSONDecodeError):
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


def record_audit(
    asset_id: str, success: bool, reason: str,
    reason_category: str | None = None,
) -> None:
    if reason_category is None:
        reason_category = "mac_non_icloud_ok" if success else "mac_other_error"
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO photo.cleanup_audit
              (asset_id, immich_id, device, success, reason,
               reason_category, reason_detail, device_deleted_at)
            VALUES (%s::uuid, NULL, 'mac-photos', %s, %s, %s, %s, NOW())
        """, (asset_id, success, reason[:200], reason_category, reason))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="0=무제한")
    args = parser.parse_args()

    targets = fetch_targets(args.limit)
    print(f"📋 4등급 외 미처리: {len(targets)}장")
    if not targets:
        print("✅ 처리 대상 없음")
        return

    by_grade: dict[str, int] = {}
    for _, g in targets:
        by_grade[g] = by_grade.get(g, 0) + 1
    print("등급 분포:")
    for g, c in sorted(by_grade.items(), key=lambda x: -x[1]):
        print(f"  {g}: {c}")

    asset_ids = [a for a, _ in targets]
    grade_map = {a: g for a, g in targets}

    print(f"\n🔍 Immich + Mac Photos 인덱스 ...")
    meta_map = fetch_immich_metadata(asset_ids)
    print(f"   Immich metadata: {len(meta_map)}/{len(asset_ids)}")

    db = osxphotos.PhotosDB()
    idx = build_filename_index(db)
    print(f"   Mac Photos: {len(db.photos())}장 / unique filenames: {len(idx)}")

    matched: list[tuple[str, str, str, str]] = []  # (aid, grade, filename, mac_uuid)
    fallback_meta: list[tuple[str, str, str, datetime]] = []  # (aid, grade, filename, ts)
    no_meta = 0
    for aid in asset_ids:
        meta = meta_map.get(aid)
        if not meta:
            no_meta += 1
            continue
        filename, ts = meta
        uuid = find_mac_uuid(idx, filename, ts)
        if uuid:
            matched.append((aid, grade_map[aid], filename, uuid))
        else:
            # osxphotos 미인덱싱 자산 (iCloud-only 등) → meta-fallback (P0-C)
            fallback_meta.append((aid, grade_map[aid], filename, ts))

    print(f"\n📊 osxphotos 매칭: {len(matched)} / meta-fallback: {len(fallback_meta)} / no_meta: {no_meta}")

    if args.dry_run:
        by_g: dict[str, int] = {}
        for _, g, _, _ in matched:
            by_g[g] = by_g.get(g, 0) + 1
        print("매칭된 자산 등급 분포:")
        for g, c in sorted(by_g.items(), key=lambda x: -x[1]):
            print(f"  {g}: {c}")
        print("\n💡 dry-run — Mac Photos 변경 X")
        return

    if not matched and not fallback_meta:
        return

    print(f"\n🗑  PhotoCleanup.app PhotoKit 실 삭제 ...")
    # 1차: UUID 매칭 batch
    processed = failed = 0
    err: str | None = None
    if matched:
        uuids = [u for _, _, _, u in matched]
        processed, failed, err = delete_via_photokit(uuids)
        print(f"   UUID 경로: processed={processed} failed={failed}"
              f"{' err='+err if err else ''}")
        if processed > 0:
            for aid, grade, filename, _ in matched[:processed]:
                record_audit(aid, True, f"mac_non_icloud:{grade}:{filename}",
                             reason_category="mac_non_icloud_ok")

    # 2차: meta-fallback (P0-C 2026-05-08)
    fb_processed = fb_failed = 0
    fb_err: str | None = None
    if fallback_meta:
        fb_processed, fb_failed, fb_err = delete_via_meta_fallback(
            [(aid, fn, ts) for aid, _, fn, ts in fallback_meta]
        )
        print(f"   meta-fallback: processed={fb_processed} failed={fb_failed}"
              f"{' err='+fb_err if fb_err else ''}")
        if fb_processed > 0:
            for aid, grade, filename, _ in fallback_meta[:fb_processed]:
                record_audit(aid, True, f"mac_non_icloud_meta:{grade}:{filename}",
                             reason_category="mac_non_icloud_meta_ok")

    print(f"\n✅ 완료: Mac Photos 휴지통 → iCloud → iPhone (30일 안전망)")


if __name__ == "__main__":
    main()
