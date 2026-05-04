"""EVENT-L 자산 AI 재평가 + promote.

사용자 명시 (2026-05-04): 결혼식 본식 burst 사진 중 좋은 컷을 AI가 BEST/EVENT로
자동 promote. 프로젝트 본질.

대상:
  grade='EVENT-L' AND is_video=FALSE AND (qwen_grade IS NULL OR qwen_grade='')

흐름:
  1. classify-service /classify HTTP 호출 (Vision LLM 재평가)
  2. LLM 결과 (BEST/EVENT/FOOD/TRASH) + signals 종합
  3. DB UPDATE + storage 이동 (layer5_album hook)

정책 (사용자 명시 보호선):
  - LLM = BEST → BEST promote ✅
  - LLM = EVENT → EVENT promote (EVENT-L에서 한 단계 ↑)
  - LLM = FOOD → FOOD 변경
  - LLM = TRASH → EVENT-L 유지 (사용자 명시: 결혼식 사진 보호, TRASH 절대 X)
  - LLM 평가 실패 → EVENT-L 유지

Usage:
  PYTHONPATH=. poetry run python scripts/promote_event_l.py [--limit N] [--dry-run]
                                                            [--source legacy|all]
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

# 결혼식 사진 보호선: LLM이 TRASH 판정해도 EVENT-L 유지
SAFE_FALLBACK = "EVENT-L"


def fetch_targets(source_filter: str, limit: int) -> list[tuple[str, str]]:
    """LLM 미평가 EVENT-L 이미지 자산. (asset_id, immich_path)."""
    src_clauses = {
        "legacy": "AND source_path LIKE '/Users/jw-home/%'",
        "iphone": "AND source_path LIKE '/usr/src/app/upload/%'",
        "all": "",
    }
    src = src_clauses.get(source_filter, "")

    sql = f"""
        SELECT c.asset_id::text, c.source_path
        FROM photo.classification c
        WHERE c.grade='EVENT-L'
          AND c.is_video = FALSE
          AND (c.qwen_grade IS NULL OR c.qwen_grade='')
          {src}
        ORDER BY c.asset_id
    """
    if limit > 0:
        sql += f" LIMIT {limit}"
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def classify_via_service(client: httpx.Client, asset_id: str,
                         immich_path: str) -> dict | None:
    """classify-service /classify 호출."""
    # immich_path를 Immich originalPath로 변환 (그대로 전달, classify가 _resolve)
    # 단, source_path가 호스트 경로(/Users/jw-home/...)면 Immich path 모르면 매핑 필요.
    # 가장 간단: /signals/{asset_id}로 immich_path 받기 → /classify에 그 path
    # 다만 /classify는 path 인자가 필요. 우회: backup_verifier 사용
    # 또는 classify_and_persist를 활용 — but 새 row 만들지 않음.

    # 가장 단순: /signals 호출해 immich_path 얻고, 그 path로 /classify
    try:
        s = client.get(f"{CLASSIFY_URL}/signals/{asset_id}", timeout=120)
        if s.status_code != 200:
            return None
        path_info = s.json()
        # /signals 응답에는 immich_path 명시 안 됨. backup_verifier 호출 우회.
        v = client.post(f"{CLASSIFY_URL}/verify_backup",
                        json={"asset_id": asset_id}, timeout=600)
        if v.status_code != 200:
            return None
        immich_path = v.json().get("immich_path")
        if not immich_path:
            return None

        r = client.post(
            f"{CLASSIFY_URL}/classify",
            json={"immich_id": "n/a", "path": immich_path,
                  "asset_id": asset_id},
            timeout=180,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        return None
    return None


def update_db(asset_id: str, decision: dict, new_grade: str) -> None:
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE photo.classification
            SET grade = %s,
                grade_source = %s,
                qwen_grade = %s,
                qwen_conf = %s,
                qwen_ms = %s,
                groq_grade = %s,
                groq_conf = %s,
                groq_ms = %s,
                contains_child = %s,
                updated_at = NOW()
            WHERE asset_id = %s::uuid
        """, (
            new_grade,
            decision.get("source", "llm_unknown"),
            decision.get("qwen_grade") or "",
            decision.get("qwen_conf") or 0,
            decision.get("qwen_ms") or 0,
            decision.get("groq_grade") or "",
            decision.get("groq_conf") or 0,
            decision.get("groq_ms") or 0,
            decision.get("contains_child", False),
            asset_id,
        ))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0=무제한")
    parser.add_argument("--source", default="legacy",
                        choices=["legacy", "iphone", "all"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    targets = fetch_targets(args.source, args.limit)
    print(f"📼 promote 대상: {len(targets)}장 (source={args.source})")
    if not targets:
        return

    decisions: Counter[str] = Counter()
    promotions: list[tuple[str, str, str]] = []   # (aid, new_grade, source)
    fail = 0
    start = time.time()

    client = httpx.Client()
    try:
        for i, (aid, src_path) in enumerate(targets, 1):
            if i % 25 == 0:
                elapsed = time.time() - start
                rate = i / elapsed if elapsed else 0
                eta = (len(targets) - i) / rate if rate else 0
                print(f"  진행 {i}/{len(targets)} (BEST {decisions.get('BEST', 0)}, "
                      f"EVENT {decisions.get('EVENT', 0)}, "
                      f"keep {decisions.get('EVENT-L', 0)}) "
                      f"{rate:.1f}/s ETA {eta/60:.1f}min")

            d = classify_via_service(client, aid, src_path)
            if d is None:
                fail += 1
                continue

            llm_grade = d.get("grade", "")
            # 보호선: LLM이 TRASH/MEMORY 등 판정해도 EVENT-L 유지
            if llm_grade in ("BEST", "EVENT", "FOOD"):
                new_grade = llm_grade
            else:
                new_grade = SAFE_FALLBACK

            decisions[new_grade] += 1

            if not args.dry_run and new_grade != "EVENT-L":
                update_db(aid, d, new_grade)
                promotions.append((aid, new_grade, d.get("source", "")))
    finally:
        client.close()

    print()
    print(f"📊 결정 분포 (실패 {fail}장):")
    for k, v in decisions.most_common():
        print(f"  → {k}: {v}")

    if args.dry_run:
        print("\n💡 dry-run — DB 변경 X")
        return

    if not promotions:
        print("\n(promote 자산 없음)")
        return

    print(f"\n🔧 Layer 5 폴더 정합 적용 ({len(promotions)}장)...")
    move_ok = move_fail = 0
    for i, (aid, new_grade, _src) in enumerate(promotions, 1):
        if i % 50 == 0:
            print(f"  진행 {i}/{len(promotions)} (move ok {move_ok})")
        success, _ = apply_grade_change(aid, new_grade)
        if success:
            move_ok += 1
        else:
            move_fail += 1

    print(f"\n📊 결과: promote {len(promotions)}장, "
          f"HDD move ok={move_ok} fail/skip={move_fail}")


if __name__ == "__main__":
    main()
