"""Groq/Qwen 라우팅 가시화 알림 — 2026-05-08 P1-F.

분류 의도(`VISION_MODEL_CHAIN=groq,qwen`: Groq 1차)와 실제 분포 갭 감지.
Groq 비율이 임계 미만이면 Telegram 알림 (idempotent — 7일 내 중복 X).

원인 후보:
  - Groq Llama-4 Scout 무료 한도 소진
  - LiteLLM proxy 라우팅 버그
  - GROQ_API_KEY 만료/회수

Usage:
  PYTHONPATH=. poetry run python scripts/check_groq_routing.py [--telegram]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)

# 임계: Groq 비율 < 10% (LLM 분류 中) → 알림. min sample 50건.
GROQ_RATIO_THRESHOLD = 0.10
MIN_SAMPLE = 50


def fetch_routing_d7() -> dict[str, int]:
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT
              SUM(CASE WHEN grade_source = 'llm_groq' THEN 1 ELSE 0 END) AS groq,
              SUM(CASE WHEN grade_source = 'llm_qwen' THEN 1 ELSE 0 END) AS qwen,
              SUM(CASE WHEN grade_source = 'llm_ensemble' THEN 1 ELSE 0 END) AS ensemble,
              SUM(CASE WHEN grade_source LIKE 'llm_corrected%' THEN 1 ELSE 0 END) AS corrected,
              SUM(CASE WHEN grade_source LIKE 'auto_%' THEN 1 ELSE 0 END) AS auto_fallback
            FROM photo.classification
            WHERE classified_at > NOW() - INTERVAL '7 days'
        """)
        g, q, e, c, a = cur.fetchone()
    return {
        "groq": g or 0, "qwen": q or 0, "ensemble": e or 0,
        "corrected": c or 0, "auto_fallback": a or 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--telegram", action="store_true",
                        help="임계 미만 시 Telegram 알림")
    args = parser.parse_args()

    r = fetch_routing_d7()
    llm_total = r["groq"] + r["qwen"] + r["ensemble"]
    print("📊 7일 모델 라우팅 분포:")
    for k in ("groq", "qwen", "ensemble", "corrected", "auto_fallback"):
        pct = (r[k] / llm_total * 100) if llm_total else 0
        marker = "✅" if k != "groq" or pct >= GROQ_RATIO_THRESHOLD * 100 else "⚠️"
        print(f"  {marker} {k:14s} {r[k]:>6d}  ({pct:.1f}%)")

    if llm_total < MIN_SAMPLE:
        print(f"\n💡 sample {llm_total} < {MIN_SAMPLE} — 분포 평가 보류")
        return 0

    groq_ratio = r["groq"] / llm_total if llm_total else 0
    if groq_ratio >= GROQ_RATIO_THRESHOLD:
        print(f"\n✅ Groq 비율 {groq_ratio*100:.1f}% — 정상 라우팅")
        return 0

    msg = (
        f"Groq 비율 {groq_ratio*100:.1f}% (임계 {GROQ_RATIO_THRESHOLD*100:.0f}% 미만) — "
        f"의도(`groq,qwen` 1차)와 실제 분포 갭. 무료 한도 소진 또는 라우팅 버그 가능."
    )
    print(f"\n⚠️  {msg}")
    print(f"   확인: docker exec litellm_proxy curl -s localhost:4000/v1/models | jq .")
    print(f"   확인: docker logs litellm_proxy --tail 50 | grep -i groq")

    if args.telegram:
        # 7일 내 중복 알림 X (NSC-2 패턴)
        sig = hashlib.md5(f"groq_routing:{int(groq_ratio * 100)}".encode()).hexdigest()[:12]
        flag = Path(f"scripts/_inventory/groq_routing_alert_{sig}.flag")
        if flag.exists() and (time.time() - flag.stat().st_mtime) < 7 * 86400:
            print(f"  (같은 알림 7일 내 발송됨 — skip: {flag.name})")
        else:
            subprocess.run(
                ["bash", "scripts/notify_telegram.sh",
                 "Photo Groq 라우팅 갭 감지", msg],
                check=False,
            )
            flag.touch()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
