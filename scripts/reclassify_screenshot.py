"""auto_screenshot 자산 재분류 — 강화된 휴리스틱.

새 정책 (사용자 명시 2026-05-04):
  - face_count > 0 + laplacian >= 100  → MEMORY+ (사람 + 화질 OK)
  - face_count > 0 + laplacian < 100   → MEMORY-  (사람 + 흐림)
  - face_count = 0 + camera_make 있음  → NORMAL  (카메라 사진, 사람 없음)
  - face_count = 0 + camera_make 없음  → TRASH 유지 (진짜 screenshot)

DB 신호값 부재 시 classify-service /signals/{asset_id} HTTP 호출로 재측정.

Usage:
  PYTHONPATH=. poetry run python scripts/reclassify_screenshot.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter

import httpx
import psycopg
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.pipeline.layer5_album import apply_grade_change  # noqa: E402

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)
CLASSIFY_URL = os.getenv("CLASSIFY_URL", "http://127.0.0.1:8765")
LAPLACIAN_BLUR = 100.0


def fetch_targets() -> list[tuple]:
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT
              asset_id::text,
              face_count,
              laplacian_variance,
              camera_make,
              is_screenshot
            FROM photo.classification
            WHERE grade='TRASH' AND grade_source='auto_screenshot'
            ORDER BY asset_id
        """)
        return cur.fetchall()


def measure_signals(client: httpx.Client, asset_id: str) -> dict | None:
    try:
        r = client.get(f"{CLASSIFY_URL}/signals/{asset_id}", timeout=120)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def decide_new_grade(
    face_count: int | None,
    laplacian: float | None,
    camera_make: str | None,
) -> tuple[str, str]:
    """새 정책으로 등급 결정. (new_grade, new_source)."""
    fc = int(face_count) if face_count is not None else 0
    lap = float(laplacian) if laplacian is not None else 0.0
    cam = (camera_make or "").strip()

    if fc > 0:
        if lap < LAPLACIAN_BLUR:
            return "MEMORY-", "reclass_face_blurry"
        return "MEMORY+", "reclass_face"
    if cam:
        return "NORMAL", "reclass_camera_no_face"
    return "TRASH", "auto_screenshot"  # 유지


def update_db_signals(
    asset_id: str,
    sig: dict,
) -> None:
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE photo.classification
            SET face_count = %s,
                laplacian_variance = %s,
                camera_make = %s,
                is_screenshot = %s,
                width = %s,
                height = %s,
                updated_at = NOW()
            WHERE asset_id = %s::uuid
        """, (
            sig.get("face_count"),
            sig.get("laplacian_variance"),
            sig.get("camera_make") or None,
            sig.get("is_screenshot"),
            sig.get("width") or None,
            sig.get("height") or None,
            asset_id,
        ))


def update_grade(asset_id: str, new_grade: str, new_source: str) -> None:
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE photo.classification
            SET grade = %s, grade_source = %s, updated_at = NOW()
            WHERE asset_id = %s::uuid
        """, (new_grade, new_source, asset_id))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = fetch_targets()
    print(f"📼 auto_screenshot 자산: {len(rows)}장")
    if not rows:
        return

    decisions: Counter[str] = Counter()
    measured = 0
    measure_fail = 0
    plan: list[tuple[str, str, str]] = []   # (asset_id, new_grade, new_source)

    client = httpx.Client()
    try:
        for i, (aid, fc, lap, cam, _ss) in enumerate(rows, 1):
            if i % 50 == 0:
                print(f"  진행 {i}/{len(rows)} (재측정 {measured}, 실패 {measure_fail})")
            # 신호값 부재 시 재측정
            if fc is None or cam is None:
                sig = measure_signals(client, aid)
                if sig is None:
                    measure_fail += 1
                    decisions["measure_fail_keep_trash"] += 1
                    plan.append((aid, "TRASH", "auto_screenshot"))
                    continue
                measured += 1
                if not args.dry_run:
                    update_db_signals(aid, sig)
                fc = sig["face_count"]
                lap = sig["laplacian_variance"]
                cam = sig["camera_make"]

            new_grade, new_source = decide_new_grade(fc, lap, cam)
            decisions[new_source] += 1
            if new_grade != "TRASH":  # 변경 필요한 자산만 plan
                plan.append((aid, new_grade, new_source))
    finally:
        client.close()

    print()
    print(f"📊 분포 (재측정 {measured}장, 실패 {measure_fail}장):")
    for k, v in decisions.most_common():
        print(f"  {k}: {v}")
    print()
    print(f"🔼 등급 변경 대상: {len(plan)}장 (TRASH 유지 외)")

    if args.dry_run:
        print("\n💡 dry-run — DB 변경 X")
        return

    print("\n🔧 등급 변경 + Layer 5 폴더 정합 적용 중...")
    move_ok = move_fail = 0
    for i, (aid, new_grade, new_source) in enumerate(plan, 1):
        if i % 50 == 0:
            print(f"  진행 {i}/{len(plan)} (move ok {move_ok}, fail {move_fail})")
        update_grade(aid, new_grade, new_source)
        success, _ = apply_grade_change(aid, new_grade)
        if success:
            move_ok += 1
        else:
            move_fail += 1

    print(f"\n📊 결과: 등급 변경 {len(plan)}장, HDD move ok={move_ok} fail/skip={move_fail}")


if __name__ == "__main__":
    main()
