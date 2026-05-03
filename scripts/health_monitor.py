"""classify-service + 분류 파이프라인 헬스체크.

실행 주기: maintenance.sh와 동일 (cron 30분 또는 03:00).
출력: 표준 출력 + (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 설정 시) Telegram 알림.

체크 항목:
  1. classify-service /health 응답
  2. Immich /api/server/ping
  3. Ollama 모델 로딩 상태
  4. photo.classification 처리량 (지난 24h, 7d)
  5. pending 자산 누적 (>100 알림)
  6. classify-service 컨테이너 상태

Usage:
  PYTHONPATH=. poetry run python scripts/health_monitor.py [--alert-only]

  --alert-only: 정상 시 출력 없음, 이상 시만 알림
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import subprocess
from dataclasses import dataclass

import httpx
import psycopg
from dotenv import load_dotenv

load_dotenv()

CLASSIFY_URL = os.getenv("CLASSIFY_URL", "http://127.0.0.1:8765")
IMMICH_URL = "http://localhost:2283"
OLLAMA_URL = "http://localhost:11434"
DB_DSN = (
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"
)
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

PENDING_THRESHOLD = 100  # 대기 자산 알림 임계값


@dataclass(slots=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


def _check_classify() -> Check:
    try:
        r = httpx.get(f"{CLASSIFY_URL}/health", timeout=5)
        if r.status_code == 200 and r.json().get("ok"):
            return Check("classify-service", True, "200 OK")
        return Check("classify-service", False, f"{r.status_code}")
    except Exception as e:
        return Check("classify-service", False, str(e)[:60])


def _check_immich() -> Check:
    try:
        r = httpx.get(f"{IMMICH_URL}/api/server/ping", timeout=5)
        if r.status_code == 200:
            return Check("immich-server", True, "ping ok")
        return Check("immich-server", False, f"{r.status_code}")
    except Exception as e:
        return Check("immich-server", False, str(e)[:60])


def _check_ollama() -> Check:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            qwen = next((m for m in models if "qwen2.5vl" in m), None)
            if qwen:
                return Check("ollama", True, qwen)
            return Check("ollama", False, "qwen2.5vl 모델 없음")
        return Check("ollama", False, f"{r.status_code}")
    except Exception as e:
        return Check("ollama", False, str(e)[:60])


def _check_pending() -> Check:
    """Immich 자산 中 photo.classification 미존재 수."""
    try:
        proc = subprocess.run(
            ["docker", "exec", "-i", "immich-postgres",
             "psql", "-U", "postgres", "-d", "immich", "--csv", "-c",
             'SELECT id::text, "originalPath" FROM asset '
             "WHERE \"deletedAt\" IS NULL AND type='IMAGE' "
             "AND \"originalPath\" NOT LIKE '%/encoded-video/%' "
             "AND \"originalPath\" NOT LIKE '%/thumbs/%'"],
            capture_output=True, text=True, check=True, timeout=20,
        )
        rows = [r for r in csv.reader(io.StringIO(proc.stdout)) if r]
        rows = rows[1:] if rows and rows[0][0] == "id" else rows

        with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
            cur.execute("SELECT asset_id::text FROM photo.classification")
            classified = {r[0] for r in cur.fetchall()}

        from pathlib import Path
        pending = sum(
            1 for iid, path in rows
            if iid not in classified and Path(path).stem not in classified
        )
        ok = pending < PENDING_THRESHOLD
        return Check(
            "pending-queue", ok,
            f"{pending}장 대기 (임계 {PENDING_THRESHOLD})",
        )
    except Exception as e:
        return Check("pending-queue", False, str(e)[:60])


def _check_throughput() -> Check:
    """지난 24h / 7d 분류 자산 수."""
    try:
        with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT
                  COUNT(*) FILTER (WHERE classified_at > NOW() - INTERVAL '24 hours') AS d1,
                  COUNT(*) FILTER (WHERE classified_at > NOW() - INTERVAL '7 days') AS d7,
                  COUNT(*) AS total
                FROM photo.classification
            """)
            d1, d7, total = cur.fetchone()
        return Check(
            "throughput", True,
            f"24h {d1}장 / 7d {d7}장 / total {total}장",
        )
    except Exception as e:
        return Check("throughput", False, str(e)[:60])


def _check_container() -> Check:
    try:
        r = subprocess.run(
            ["docker", "ps", "--filter", "name=photo-classify",
             "--format", "{{.Status}}"],
            capture_output=True, text=True, check=True, timeout=5,
        )
        status = r.stdout.strip()
        if status.startswith("Up") and "healthy" in status:
            return Check("container", True, status)
        if status.startswith("Up"):
            return Check("container", True, status + " (health pending)")
        return Check("container", False, status or "not running")
    except Exception as e:
        return Check("container", False, str(e)[:60])


def _send_telegram(text: str) -> None:
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alert-only", action="store_true")
    args = parser.parse_args()

    checks = [
        _check_container(),
        _check_classify(),
        _check_immich(),
        _check_ollama(),
        _check_pending(),
        _check_throughput(),
    ]
    failed = [c for c in checks if not c.ok]

    if args.alert_only and not failed:
        return

    print("📊 Photo System Health")
    for c in checks:
        mark = "✅" if c.ok else "❌"
        print(f"  {mark} {c.name:18s} {c.detail}")

    if failed:
        msg_lines = ["⚠️ <b>Photo System Alert</b>"]
        for c in failed:
            msg_lines.append(f"❌ {c.name}: {c.detail}")
        _send_telegram("\n".join(msg_lines))


if __name__ == "__main__":
    main()
