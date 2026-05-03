"""주간 KPI 발송 — 일요일 09:00 cron.

설계 §15.B: kpi_summarizer로 Groq 요약 → Telegram 발송.

Usage:
  PYTHONPATH=. poetry run python scripts/weekly_kpi.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os

import httpx
from dotenv import load_dotenv

from core.service.kpi_summarizer import collect_stats, summarize

load_dotenv()


def send_telegram(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat, "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        return r.status_code == 200
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="발송 X, 출력만")
    args = parser.parse_args()

    stats = collect_stats()
    text = summarize(stats)

    print("=" * 50)
    print(text)
    print("=" * 50)

    if args.dry_run:
        print("\n💡 dry-run — Telegram 미발송")
        return

    sent = send_telegram(text)
    print(f"\n{'✅ 발송 완료' if sent else '❌ 발송 실패 (TG 토큰 확인)'}")


if __name__ == "__main__":
    main()
