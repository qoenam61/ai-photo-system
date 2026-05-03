"""FOOD 등급 자산 일괄 카테고리 분류.

photo.classification.grade='FOOD' AND food_category IS NULL → Qwen + Groq 호출.

Usage:
  PYTHONPATH=. poetry run python scripts/categorize_food.py [--limit 20]
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from core.service.food_categorizer import categorize_food

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)


def find_local_path(asset_id: str) -> Path | None:
    """asset_id → /Volumes/Immich-Storage/.../FOOD/<asset_id>.jpg 등 검색."""
    base = Path("/Volumes/Immich-Storage/immich-media/library/FOOD")
    for ext in ("jpg", "jpeg", "heic", "png"):
        p = base / f"{asset_id}.{ext}"
        if p.exists():
            return p
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--all", action="store_true",
                        help="이미 분류된 것 포함 재분류")
    args = parser.parse_args()

    where = "grade = 'FOOD'"
    if not args.all:
        where += " AND food_category IS NULL"

    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT asset_id::text FROM photo.classification
            WHERE {where}
            ORDER BY classified_at DESC
            LIMIT %s
        """, (args.limit,))
        targets = [r[0] for r in cur.fetchall()]

    if not targets:
        print("✅ 분류 대상 FOOD 없음")
        return

    print(f"🍽 FOOD 카테고리 분류: {len(targets)}장 처리")

    counts: dict[str, int] = {}
    with psycopg.connect(DB_DSN, autocommit=True) as conn:
        for aid in targets:
            p = find_local_path(aid)
            if not p:
                print(f"  ⚠️ {aid[:8]} 파일 없음 — skip")
                continue

            meta = categorize_food(p)
            print(f"  {aid[:8]} → {meta.category:6s} ({meta.keyword[:30]})")
            counts[meta.category] = counts.get(meta.category, 0) + 1

            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE photo.classification
                    SET food_category = %s, food_keyword = %s
                    WHERE asset_id = %s
                """, (meta.category, meta.keyword, aid))

    print("\n📊 카테고리별:")
    for c, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {c:6s}: {n}장")


if __name__ == "__main__":
    main()
