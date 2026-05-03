"""백업 폴더 전수 SHA256 검증 — Phase 5 안전 게이트.

설계 §5: photo.classification 全 자산을 verify_asset()로 검증.
PASS만 백업 폴더 원본 삭제 후보.

Usage:
  PYTHONPATH=. poetry run python scripts/verify_backup_full.py [--limit N]
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from core.service.backup_verifier import verify_asset

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0=무제한")
    args = parser.parse_args()

    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT asset_id::text, source_path FROM photo.classification
            WHERE source_path LIKE '/Users/jw-home/백업/%' OR source_path LIKE '/mnt/external/%'
            ORDER BY asset_id
        """ + (f" LIMIT {args.limit}" if args.limit > 0 else ""))
        rows = cur.fetchall()

    print(f"🔍 검증 대상: {len(rows)}장")

    pass_count = 0
    fail_count = 0
    fail_reasons: dict[str, int] = {}
    fail_assets: list[tuple[str, str, str]] = []

    for i, (asset_id, source_path) in enumerate(rows, 1):
        if i % 200 == 0:
            print(f"  진행 {i}/{len(rows)} (PASS {pass_count}, FAIL {fail_count})")
        v = verify_asset(asset_id)
        if v.verified:
            pass_count += 1
        else:
            fail_count += 1
            fail_reasons[v.reason] = fail_reasons.get(v.reason, 0) + 1
            if len(fail_assets) < 20:
                fail_assets.append((asset_id, v.reason, source_path))

    print(f"\n📊 결과: PASS {pass_count}/{len(rows)} ({100*pass_count/max(len(rows),1):.1f}%)")
    if fail_count:
        print(f"\n❌ FAIL {fail_count}장 — 사유 분포:")
        for r, c in sorted(fail_reasons.items(), key=lambda x: -x[1]):
            print(f"  {r}: {c}")
        print("\n샘플 (최대 20):")
        for aid, reason, sp in fail_assets:
            print(f"  {aid[:8]} {reason:30s} {sp}")
    else:
        print("\n✅ 전수 검증 PASS — 백업 폴더 원본 삭제 안전")


if __name__ == "__main__":
    main()
