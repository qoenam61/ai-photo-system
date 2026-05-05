"""얼굴 가시성 룰(2026-05-05) 적용 — 의심 EVENT/BEST/MEMORY+ 재분류.

사용자 명시 (2026-05-05):
  EVENT/BEST/MEMORY+ 등 사람 등장 등급은 얼굴이 명확히 보여야 함.
  부분 신체(다리/뒷모습/잘림)만 보이면 TRASH.

대상 (보수적 우선):
  grade IN (EVENT, BEST, MEMORY+) AND face_count = 0
  AND grade_source = 'llm_qwen'  (LLM이 EVENT/BEST/MEMORY+ 판정했지만 얼굴 인식 0 — 의심)
  AND NOT video, NOT dedup_demoted, NOT restored_from_dedup, NOT folder_bulk_*

  이유:
  - LLM 판정 + face=0 = 새 룰로 잡아낼 핵심 케이스
  - dedup_demoted/restored_from_dedup = 사용자 환원 또는 의도적 강등 → 보호
  - folder_bulk_* = 본식 사진 일괄 import → 신중 (오래된 사진 face 인식 fail 가능)
  - auto_video / auto_quality_ok = 정상 경로

새 분류:
  - 새 PROMPT (얼굴 가시성 강제) 통과 → EVENT/BEST 유지
  - LLM이 TRASH 판정 → TRASH로 강등 (얼굴 안 보이는 사진)
  - LLM이 다른 등급 판정 → 그대로

Usage:
  PYTHONPATH=. poetry run python scripts/reclassify_face_required.py [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

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


def fetch_targets(limit: int) -> list[tuple]:
    """의심 자산: face=0 + LLM 판정 + EVENT/BEST/MEMORY+."""
    sql = """
        SELECT asset_id::text, grade, grade_source
        FROM photo.classification
        WHERE grade IN ('EVENT','BEST','MEMORY+')
          AND face_count = 0
          AND grade_source = 'llm_qwen'
          AND is_video = FALSE
        ORDER BY classified_at DESC
    """
    if limit > 0:
        sql += f" LIMIT {limit}"
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def fetch_immich_paths(asset_ids: list[str]) -> dict[str, str]:
    """asset_id (originalPath stem) → originalPath 매핑."""
    if not asset_ids:
        return {}
    proc = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "--csv", "-c",
         """SELECT "originalPath" FROM asset WHERE "deletedAt" IS NULL"""],
        capture_output=True, text=True, check=True, timeout=120,
    )
    aid_set = set(asset_ids)
    out: dict[str, str] = {}
    rows = list(csv.reader(io.StringIO(proc.stdout)))[1:]
    for row in rows:
        if not row:
            continue
        path = row[0]
        stem = Path(path).stem
        if stem in aid_set:
            out[stem] = path
    return out


def reclassify(client: httpx.Client, asset_id: str, path: str) -> dict | None:
    try:
        r = client.post(
            f"{CLASSIFY_URL}/classify_and_persist",
            json={"path": path, "asset_id": asset_id, "immich_id": ""},
            timeout=120,
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        return {"error": f"{type(e).__name__}:{e}"}
    return {"error": f"http_{r.status_code}"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="0=무제한")
    args = parser.parse_args()

    rows = fetch_targets(args.limit)
    print(f"📼 재분류 후보 (LLM 판정 + face=0 + EVENT/BEST/MEMORY+): {len(rows)}장")
    if not rows:
        return

    by_grade: Counter[str] = Counter()
    for _, g, _ in rows:
        by_grade[g] += 1
    print("  현재 등급 분포:")
    for g, c in by_grade.most_common():
        print(f"    {g}: {c}")

    asset_ids = [aid for aid, _, _ in rows]
    print(f"\n🔍 Immich originalPath 매핑 ...")
    path_map = fetch_immich_paths(asset_ids)
    print(f"   매핑 성공: {len(path_map)}/{len(asset_ids)}")

    if args.dry_run:
        print("\n💡 dry-run — DB/HDD 변경 X")
        return

    print("\n🔧 LLM 재분류 시작 (얼굴 가시성 룰 적용) ...")
    transitions: Counter[tuple[str, str]] = Counter()
    error_count = 0
    moved_ok = moved_fail = 0

    client = httpx.Client()
    try:
        for i, (aid, old_grade, _src) in enumerate(rows, 1):
            if i % 50 == 0:
                print(f"  진행 {i}/{len(rows)} (오류 {error_count})")
            path = path_map.get(aid)
            if not path:
                error_count += 1
                continue

            res = reclassify(client, aid, path)
            if not res or "error" in res:
                error_count += 1
                continue

            new_grade = res.get("grade", old_grade)
            new_src = res.get("source", "")
            transitions[(old_grade, new_grade)] += 1

            if new_grade != old_grade:
                ok, _ = apply_grade_change(aid, new_grade)
                if ok:
                    moved_ok += 1
                else:
                    moved_fail += 1

            # rate-limit guard (Groq throttle 보호)
            if i % 20 == 0:
                time.sleep(1.0)
    finally:
        client.close()

    print(f"\n📊 재분류 결과 (오류 {error_count}장):")
    for (old, new), n in transitions.most_common():
        marker = "→" if old == new else "⬇" if new == "TRASH" else "⬆"
        print(f"  {old:8} {marker} {new:8} : {n}")
    print(f"\n📦 HDD move ok={moved_ok} fail/skip={moved_fail}")


if __name__ == "__main__":
    main()
