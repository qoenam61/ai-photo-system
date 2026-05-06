"""기존 자산에 분류 v2 룰 적용 — 사용자 명시 (2026-05-06).

Phase A — Signals backfill:
  face_count / laplacian_variance / camera_make 가 NULL인 자산
  → /signals/{asset_id} HTTP 호출 (OpenCV + EXIF 재측정)
  → DB UPDATE

Phase B — Sanity check 후처리:
  LLM grade 자산에 v2 sanity check 적용:
    · LLM=BEST + face=0 + camera=∅ + lap<30 → TRASH
    · LLM=FOOD + face≥5 → EVENT
    · LLM=TRASH + face>0 + lap≥100 → MEMORY+
  → grade_source 마킹 'llm_corrected_*' + Layer 5 HDD 이동

Usage:
  PYTHONPATH=. poetry run python scripts/backfill_classification_v2.py [--dry-run] [--phase A|B|all] [--limit N]
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


# ─────────────────────────────────────────────
# Phase A: Signals backfill
# ─────────────────────────────────────────────


def fetch_phase_a_targets(limit: int) -> list[str]:
    """face_count NULL 또는 laplacian_variance NULL 인 이미지 자산."""
    sql = """
        SELECT asset_id::text
        FROM photo.classification
        WHERE (is_video = FALSE OR is_video IS NULL)
          AND (face_count IS NULL OR laplacian_variance IS NULL)
          AND grade != 'TRASH'  -- TRASH는 backfill 의미 적음
        ORDER BY classified_at DESC
    """
    if limit > 0:
        sql += f" LIMIT {limit}"
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return [r[0] for r in cur.fetchall()]


def measure_signals(client: httpx.Client, asset_id: str) -> dict | None:
    try:
        r = client.get(f"{CLASSIFY_URL}/signals/{asset_id}", timeout=60)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def update_signals(asset_id: str, sig: dict) -> None:
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE photo.classification
            SET face_count = %s,
                laplacian_variance = %s,
                camera_make = %s,
                is_screenshot = %s,
                width = %s, height = %s,
                updated_at = NOW()
            WHERE asset_id = %s::uuid
        """, (
            sig.get("face_count"), sig.get("laplacian_variance"),
            sig.get("camera_make") or None, sig.get("is_screenshot"),
            sig.get("width") or None, sig.get("height") or None,
            asset_id,
        ))


def run_phase_a(dry_run: bool, limit: int) -> None:
    targets = fetch_phase_a_targets(limit)
    print(f"📊 Phase A — Signal backfill 대상: {len(targets)}장")
    if not targets:
        return

    if dry_run:
        print("💡 dry-run — 측정 안 함")
        return

    ok = fail = 0
    client = httpx.Client()
    try:
        for i, aid in enumerate(targets, 1):
            if i % 100 == 0:
                print(f"  진행 {i}/{len(targets)} (ok={ok} fail={fail})")
            sig = measure_signals(client, aid)
            if sig is None:
                fail += 1
                continue
            update_signals(aid, sig)
            ok += 1
            if i % 50 == 0:
                time.sleep(0.5)  # rate limit guard
    finally:
        client.close()
    print(f"\n✅ Phase A 완료: 측정 {ok}장 / 실패 {fail}장")


# ─────────────────────────────────────────────
# Phase B: Sanity check 후처리
# ─────────────────────────────────────────────


def _sanity_check(grade: str, fc: int | None, lap: float | None,
                  cam: str | None) -> tuple[str, str] | None:
    """v2 sanity check 룰 (classifier.py와 동일).

    반환: (new_grade, suffix) or None (변경 없음).
    """
    fc = fc or 0
    lap = lap or 0.0
    cam = (cam or "").strip()

    # BEST → 신호 모두 의심 (얼굴 X + 카메라 X + 매우 흐림)
    if grade == "BEST" and fc == 0 and not cam and 0 < lap < 30:
        return ("TRASH", "_llm_best_unverified")

    # FOOD → 사람 다수 (인물 우선)
    if grade == "FOOD" and fc >= 5:
        return ("EVENT", "_llm_food_with_crowd")

    # TRASH → 사람 명확 + 선명 (LLM 오판 의심)
    if grade == "TRASH" and fc > 0 and lap >= 100:
        return ("MEMORY+", "_llm_trash_face_sharp")

    return None


def fetch_phase_b_targets(limit: int) -> list[tuple]:
    """LLM grade + sanity check 가능한 자산. (asset_id, grade, fc, lap, cam)."""
    sql = """
        SELECT asset_id::text, grade,
               face_count, laplacian_variance, camera_make
        FROM photo.classification
        WHERE grade IN ('BEST','EVENT','FOOD','TRASH')
          AND grade_source LIKE 'llm_%%'
          AND (is_video = FALSE OR is_video IS NULL)
        ORDER BY classified_at DESC
    """
    if limit > 0:
        sql += f" LIMIT {limit}"
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def update_grade(asset_id: str, new_grade: str, suffix: str) -> None:
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE photo.classification
            SET grade = %s,
                grade_source = %s,
                updated_at = NOW()
            WHERE asset_id = %s::uuid
        """, (new_grade, f"llm_corrected{suffix}", asset_id))


def run_phase_b(dry_run: bool, limit: int) -> None:
    rows = fetch_phase_b_targets(limit)
    print(f"📊 Phase B — Sanity check 대상: {len(rows)}장 (LLM grade)")

    transitions: Counter[tuple[str, str]] = Counter()
    plan: list[tuple[str, str, str]] = []  # (aid, new_grade, suffix)

    for aid, grade, fc, lap, cam in rows:
        result = _sanity_check(grade, fc, float(lap) if lap else None, cam)
        if result is None:
            continue
        new_grade, suffix = result
        transitions[(grade, new_grade)] += 1
        plan.append((aid, new_grade, suffix))

    print(f"\n등급 전이 (sanity check 변경 후보):")
    for (old, new), n in sorted(transitions.items(), key=lambda x: -x[1]):
        print(f"  {old:8} → {new:8}: {n}")

    if not plan:
        print("\n변경 대상 없음")
        return

    print(f"\n📊 변경 대상: {len(plan)}장")

    if dry_run:
        print("💡 dry-run — DB/HDD 변경 X")
        return

    print("\n🔧 적용 중 ...")
    move_ok = move_fail = 0
    for i, (aid, new_grade, suffix) in enumerate(plan, 1):
        if i % 50 == 0:
            print(f"  진행 {i}/{len(plan)} (HDD ok={move_ok} fail={move_fail})")
        update_grade(aid, new_grade, suffix)
        success, _ = apply_grade_change(aid, new_grade)
        if success:
            move_ok += 1
        else:
            move_fail += 1

    print(f"\n✅ Phase B 완료: 등급 변경 {len(plan)}장 / HDD ok={move_ok} fail={move_fail}")


# ─────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--phase", choices=["A", "B", "all"], default="all")
    parser.add_argument("--limit", type=int, default=0, help="0=무제한")
    args = parser.parse_args()

    if args.phase in ("A", "all"):
        print("=" * 60)
        print("Phase A — Signal backfill")
        print("=" * 60)
        run_phase_a(args.dry_run, args.limit)

    if args.phase in ("B", "all"):
        print()
        print("=" * 60)
        print("Phase B — Sanity check 후처리")
        print("=" * 60)
        run_phase_b(args.dry_run, args.limit)


if __name__ == "__main__":
    main()
