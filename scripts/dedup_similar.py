"""유사컷 강등 — 5초 window burst dedup + 하위등급 보관 (사용자 명시 2026-05-05).

사용자 명시 정책 변경 (2026-05-05):
  - window 1초 → **5초** (5초 이내 burst는 동일 장면)
  - demote target: TRASH → **하위등급 강등 보관** (삭제 X, 등급만 한 단계 아래)
  - 그룹화: 5초 bucket + 같은 카메라 (등급 무시)
    → BEST_a + EVENT_b가 같은 시점·카메라면 같은 장면으로 처리
  - 베스트컷 = laplacian × file_size 1위 → 원래 등급 유지
  - 나머지 = DEMOTE 매핑 따라 한 단계 아래로 강등

DEMOTE 매핑:
  BEST    → MEMORY+   (iCloud 보존 유지, 한 단계 아래)
  EVENT   → EVENT-L   (행사 long/secondary, iCloud)
  EVENT-L → MEMORY+
  MEMORY+ → MEMORY-   (HDD 보존)
  FOOD    → MEMORY-
  MEMORY- → NORMAL
  NORMAL  → NORMAL    (변화 X — 이미 최하위 비-trash)

이미 dedup_demoted_* 처리된 자산은 재처리 X.

Usage:
  PYTHONPATH=. poetry run python scripts/dedup_similar.py [--dry-run] [--window-seconds N]
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

import psycopg
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.pipeline.layer5_album import apply_grade_change  # noqa: E402

load_dotenv()

DB_DSN = (
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"
)

# 2026-05-08 P1-E 보강: 사용자 환원 1,599장의 93%가 EVENT/EVENT-L burst.
# 행사 사진 5초 burst는 사용자가 여러 컷 보존을 원하므로 dedup_5s 제외.
# (BEST는 베스트컷이 살아남으므로 안전 — 같은 장면 burst 한정)
DEDUP_FROM = ["BEST", "MEMORY+", "FOOD", "MEMORY-", "NORMAL"]
EVENT_PRESERVED_GRADES = ("EVENT", "EVENT-L")

DEMOTE = {
    "BEST":    "MEMORY+",
    "EVENT":   "EVENT-L",
    "EVENT-L": "MEMORY+",
    "MEMORY+": "MEMORY-",
    "FOOD":    "MEMORY-",
    "MEMORY-": "NORMAL",
    "NORMAL":  "NORMAL",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="DB 변경 X, 통계만")
    parser.add_argument("--window-seconds", type=int, default=5,
                        help="burst 그룹화 단위(초). 사용자 명시 기본 5초")
    args = parser.parse_args()

    grade_filter = ", ".join(f"'{g}'" for g in DEDUP_FROM)
    conn = psycopg.connect(DB_DSN, autocommit=True)
    with conn.cursor() as cur:
        # 그룹화: 5초 bucket + 같은 카메라 (등급 무시 — 같은 장면 가정)
        # 이미 dedup_demoted_* 처리된 자산은 제외 (재처리 방지)
        cur.execute(f"""
            WITH bucketed AS (
              SELECT
                asset_id,
                grade,
                grade_source,
                exif_datetime,
                COALESCE(camera_make, '') AS make,
                COALESCE(camera_model, '') AS model,
                file_size_bytes,
                COALESCE(laplacian_variance, 0) AS lap,
                FLOOR(EXTRACT(EPOCH FROM exif_datetime) / {args.window_seconds}) AS time_bucket
              FROM photo.classification c
              WHERE c.exif_datetime IS NOT NULL
                AND c.grade IN ({grade_filter})
                AND COALESCE(c.grade_source, '') NOT LIKE 'dedup_demoted%%'
                AND COALESCE(c.grade_source, '') != 'restored_from_dedup'
                AND NOT EXISTS (
                  SELECT 1 FROM photo.feedback f
                  WHERE f.asset_id = c.asset_id
                    AND f.feedback_type IN ('protect', 'restored')
                )
            ),
            ranked AS (
              SELECT *,
                ROW_NUMBER() OVER (
                  PARTITION BY make, model, time_bucket
                  ORDER BY (lap * file_size_bytes) DESC NULLS LAST,
                           file_size_bytes DESC
                ) AS rn,
                COUNT(*) OVER (
                  PARTITION BY make, model, time_bucket
                ) AS group_size
              FROM bucketed
            )
            -- group_size >= 3: 진짜 burst만 처리 (단순 2장 쌍 보호 — 2026-05-08 P1-E)
            SELECT grade, asset_id::text, group_size, rn
            FROM ranked
            WHERE rn > 1 AND group_size >= 3
        """)
        candidates = cur.fetchall()

    print(f"📊 5초 burst dedup 후보 (rank≥2, 강등 대상): {len(candidates)} 자산")

    transitions: Counter[tuple[str, str]] = Counter()
    no_demote = 0
    for grade, _, _, _ in candidates:
        target = DEMOTE.get(grade)
        if target is None or target == grade:
            no_demote += 1
            continue
        transitions[(grade, target)] += 1

    print("\n등급 전이 (베스트컷 1장 외):")
    for (old, new), n in sorted(transitions.items(), key=lambda x: -x[1]):
        print(f"  {old:8} → {new:8} : {n}")
    if no_demote:
        print(f"  변화 없음 (이미 최하위 또는 매핑 X): {no_demote}")

    if args.dry_run:
        print("\n💡 dry-run — DB 변경 X")
        return

    if not candidates:
        return

    print("\n🔧 강등 적용 + Layer 5 HDD 폴더 정합 ...")
    move_ok = move_fail = 0
    db_updated = 0
    for i, (grade, aid, _, _) in enumerate(candidates, 1):
        if i % 100 == 0:
            print(f"  진행 {i}/{len(candidates)} (DB {db_updated}, HDD ok={move_ok} fail={move_fail})")
        target = DEMOTE.get(grade, grade)
        if target == grade:
            continue
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE photo.classification
                   SET grade = %s,
                       grade_source = 'dedup_demoted_5s',
                       updated_at = NOW()
                   WHERE asset_id = %s::uuid
                     AND grade = %s""",
                (target, aid, grade),
            )
            if cur.rowcount > 0:
                db_updated += 1
        success, _ = apply_grade_change(aid, target)
        if success:
            move_ok += 1
        else:
            move_fail += 1

    print(f"\n📊 결과: DB 강등 {db_updated} / HDD move ok={move_ok} fail/skip={move_fail}")

    print("\n📊 최종 등급 분포:")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT grade, COUNT(*) FROM photo.classification
            GROUP BY grade ORDER BY grade
        """)
        for g, c in cur.fetchall():
            print(f"  {g:10s}: {c:5d}")

    conn.close()


if __name__ == "__main__":
    main()
