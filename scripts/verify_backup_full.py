"""백업 폴더 전수 SHA256 검증 — Phase 5 안전 게이트 (호스트 실행).

설계 §5: photo.classification 全 자산을 classify-service /verify_backup으로 검증.
PASS만 백업 폴더 원본 삭제 후보.

호스트 실행 — backup_verifier.py가 컨테이너 내부 DSN(trading_postgres)을 쓰므로
직접 호출 불가. classify-service HTTP를 경유해 검증.

이미 cleanup 처리된 자산(processed_at IS NOT NULL)은 검증 대상에서 제외.

Usage:
  PYTHONPATH=. poetry run python scripts/verify_backup_full.py [--limit N] [--source TYPE]

  --source: all | iphone | legacy | external (기본 all)
"""

from __future__ import annotations

import argparse
import os
import time
from collections import Counter

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


def fetch_targets(source: str, limit: int) -> list[tuple[str, str, str]]:
    pattern = {
        "all":      ("/Users/jw-home/%", "/mnt/external/%", "/usr/src/app/upload/%"),
        "legacy":   ("/Users/jw-home/%",),
        "external": ("/mnt/external/%",),
        "iphone":   ("/usr/src/app/upload/%",),
    }[source]

    where = " OR ".join([f"source_path LIKE %s"] * len(pattern))
    sql = f"""
        SELECT c.asset_id::text, c.source_path,
               LOWER(SUBSTRING(c.source_path FROM '\\.[^.]+$')) AS ext
        FROM photo.classification c
        LEFT JOIN photo.cleanup_queue q ON q.asset_id = c.asset_id
        WHERE ({where})
          AND (q.processed_at IS NULL OR q.id IS NULL)
        ORDER BY c.asset_id
    """
    params = list(pattern)
    if limit > 0:
        sql += " LIMIT %s"
        params.append(limit)

    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".hevc"}


def _verify_one(client: httpx.Client, asset_id: str, is_video: bool) -> dict:
    """1회 + 1회 재시도 (총 2회). 영상은 600s timeout, 사진 180s."""
    timeout = 600.0 if is_video else 180.0
    last_err = ""
    for attempt in range(2):
        try:
            r = client.post(
                f"{CLASSIFY_URL}/verify_backup",
                json={"asset_id": asset_id},
                timeout=timeout,
            )
            return r.json()
        except Exception as e:
            last_err = f"http_error:{type(e).__name__}"
            if attempt == 0:
                continue
    return {"verified": False, "reason": last_err}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0=무제한")
    parser.add_argument(
        "--source", default="all",
        choices=["all", "legacy", "external", "iphone"],
    )
    args = parser.parse_args()

    rows = fetch_targets(args.source, args.limit)
    total = len(rows)
    print(f"🔍 검증 대상: {total}장 (source={args.source})")
    if total == 0:
        return

    pass_count = 0
    fail_count = 0
    fail_reasons: Counter[str] = Counter()
    fail_assets: list[tuple[str, str, str]] = []
    start = time.time()

    client = httpx.Client()
    try:
        for i, (asset_id, source_path, ext) in enumerate(rows, 1):
            if i % 200 == 0:
                elapsed = time.time() - start
                rate = i / elapsed if elapsed else 0
                eta = (total - i) / rate if rate else 0
                print(f"  진행 {i}/{total} (PASS {pass_count}, FAIL {fail_count}) "
                      f"{rate:.1f}/s ETA {eta/60:.1f}min")
            v = _verify_one(client, asset_id, is_video=(ext in VIDEO_EXTS))
            if v.get("verified"):
                pass_count += 1
            else:
                fail_count += 1
                reason = v.get("reason", "unknown").split(":")[0]
                fail_reasons[reason] += 1
                if len(fail_assets) < 20:
                    fail_assets.append((asset_id, v.get("reason", ""), source_path))
    finally:
        client.close()

    pct = 100 * pass_count / max(total, 1)
    print(f"\n📊 결과: PASS {pass_count}/{total} ({pct:.2f}%) FAIL {fail_count}")
    if fail_count:
        print(f"\n❌ FAIL 사유 분포:")
        for r, c in fail_reasons.most_common():
            print(f"  {r}: {c}")
        print("\n샘플 (최대 20):")
        for aid, reason, sp in fail_assets:
            print(f"  {aid[:8]} {reason[:40]:40s} {sp}")
    else:
        print("\n✅ 전수 검증 PASS — 안전")


if __name__ == "__main__":
    main()
