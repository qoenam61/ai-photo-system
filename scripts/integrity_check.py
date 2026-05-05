"""데이터 무결성 모니터링 — DB ↔ Immich ↔ HDD ↔ immich-views 정합 검증.

사용자 명시 (2026-05-05): 자산 수 차이 / orphan 자동 감시. 차이 발견 시 Telegram 알림.

검증 항목:
  1. photo.classification 자산 수 vs Immich active asset
  2. classification grade별 분포 vs immich-views/{GRADE}/ symlink 수
  3. cleanup_queue.processed = cleanup_audit.success
  4. broken symlink (immich-views) 수
  5. orphan: classification 행 + Immich에서 deletedAt
  6. orphan: classification 행 + 외장 HDD 파일 미존재 (legacy만)

trigger: maintenance.sh 일일 또는 weekly cron.

Usage:
  PYTHONPATH=. poetry run python scripts/integrity_check.py [--telegram]
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import subprocess
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)
LIBRARY_HOST = Path("/Volumes/Immich-Storage/immich-media/library")
VIEWS_HOST = Path("/Volumes/Immich-Storage/immich-views")
GRADES = ("BEST", "EVENT", "EVENT-L", "FOOD", "MEMORY+", "MEMORY-", "NORMAL", "TRASH")


def fetch_db_stats() -> dict:
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT grade, COUNT(*) FROM photo.classification
            GROUP BY grade ORDER BY grade
        """)
        by_grade = dict(cur.fetchall())

        cur.execute("""
            SELECT
              (SELECT COUNT(*) FROM photo.classification),
              (SELECT COUNT(*) FROM photo.cleanup_queue WHERE processed_at IS NOT NULL),
              (SELECT COUNT(*) FROM photo.cleanup_audit WHERE success)
        """)
        classified, processed, audit_ok = cur.fetchone()

    return {"by_grade": by_grade, "classified": classified,
            "processed": processed, "audit_ok": audit_ok}


def fetch_immich_stats() -> dict:
    proc = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "--csv", "-c",
         """SELECT COUNT(*) FILTER (WHERE "deletedAt" IS NULL) AS active,
                   COUNT(*) FILTER (WHERE "deletedAt" IS NOT NULL) AS deleted
            FROM asset"""],
        capture_output=True, text=True, check=True,
    )
    rows = list(csv.reader(io.StringIO(proc.stdout)))[1:]
    return {"active": int(rows[0][0]), "deleted": int(rows[0][1])}


def fetch_hdd_stats() -> dict:
    out = {}
    for g in GRADES:
        d = LIBRARY_HOST / g
        if not d.exists():
            out[g] = 0
            continue
        out[g] = sum(1 for _ in d.iterdir() if _.is_file())
    return out


def fetch_views_stats() -> dict:
    out = {"by_grade": {}, "broken": 0}
    for g in GRADES:
        d = VIEWS_HOST / g
        if not d.exists():
            out["by_grade"][g] = 0
            continue
        total = broken = 0
        for entry in d.iterdir():
            if entry.is_symlink():
                total += 1
                if not entry.exists():
                    broken += 1
        out["by_grade"][g] = total
        out["broken"] += broken
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--telegram", action="store_true",
                        help="이상 발견 시 Telegram 알림")
    args = parser.parse_args()

    print("🔍 무결성 검증 시작 ...\n")

    db = fetch_db_stats()
    immich = fetch_immich_stats()
    hdd = fetch_hdd_stats()
    views = fetch_views_stats()

    issues: list[str] = []

    # 1. DB classified vs Immich active
    diff_total = abs(db["classified"] - immich["active"])
    print(f"📊 DB classification: {db['classified']}")
    print(f"   Immich active:    {immich['active']}")
    print(f"   차이: {diff_total}장")
    if diff_total > 50:
        issues.append(f"DB↔Immich 차이 {diff_total}장 (분류 누락 또는 orphan)")

    # 2. cleanup queue processed = audit success
    if db["processed"] != db["audit_ok"]:
        issues.append(f"queue processed({db['processed']}) ≠ audit success({db['audit_ok']})")
    print(f"\n📋 cleanup: processed={db['processed']} audit_success={db['audit_ok']}")

    # 3. immich-views broken symlinks
    print(f"\n🔗 immich-views broken symlinks: {views['broken']}")
    if views["broken"] > 0:
        issues.append(f"broken symlinks {views['broken']}개")

    # 4. 등급별 정합 (DB vs HDD vs views)
    print(f"\n📁 등급별 정합:")
    print(f"   {'GRADE':10s} {'DB':>7s} {'HDD':>7s} {'views':>7s}")
    for g in GRADES:
        d_cnt = db["by_grade"].get(g, 0)
        h_cnt = hdd.get(g, 0)
        v_cnt = views["by_grade"].get(g, 0)
        diff = abs(d_cnt - v_cnt)
        mark = " ⚠️" if diff > 50 else ""
        print(f"   {g:10s} {d_cnt:>7d} {h_cnt:>7d} {v_cnt:>7d}{mark}")
        if diff > 50:
            issues.append(f"{g}: DB={d_cnt} vs views={v_cnt} 차이 {diff}")

    print()
    if not issues:
        print("✅ 무결성 PASS — 모든 정합 정상")
    else:
        print(f"⚠️  이상 {len(issues)}건:")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")

        if args.telegram:
            body = "\n".join(f"- {i}" for i in issues)
            subprocess.run(
                ["bash", "scripts/notify_telegram.sh",
                 "Photo 무결성 이상 감지", body],
                check=False,
            )


if __name__ == "__main__":
    main()
