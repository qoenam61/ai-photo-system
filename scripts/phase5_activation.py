"""Phase 5 활성화 readiness 체크 + 활성화 워크스루.

자동 호출: maintenance.sh 매 30분.
수동 호출: PYTHONPATH=. poetry run python scripts/phase5_activation.py

체크 항목:
  1. iPhone Immich 앱 백업 시작 여부 (User upload 자산 ≥ 1)
  2. 14일 dry-run 게이트 클리어 (aged_14d ≥ 1)
  3. 사용자 보호 메커니즘 가동 확인
  4. classify-service /verify_backup, /cleanup_candidates 가동
  5. Immich 외부 노출 (photo.jwcloud.my) 가동

ALL PASS → "활성화 가능" 알림 (Telegram)
ANY FAIL → 진행 상태 + 다음 액션 안내
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_DSN = (
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"
)
IMMICH_DSN = (
    "host=localhost port=5433 dbname=immich "
    "user=postgres password=immich_pg_2026"
)
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
CLASSIFY_URL = os.getenv("CLASSIFY_URL", "http://127.0.0.1:8765")


def _query(dsn: str, sql: str) -> list[tuple]:
    if dsn == IMMICH_DSN:
        # immich-postgres는 호스트 노출 X — docker exec 사용
        import csv
        import io
        import subprocess
        proc = subprocess.run(
            ["docker", "exec", "-i", "immich-postgres",
             "psql", "-U", "postgres", "-d", "immich",
             "--csv", "-c", sql],
            capture_output=True, text=True, check=True,
        )
        rows = [r for r in csv.reader(io.StringIO(proc.stdout)) if r]
        return rows[1:] if rows and not rows[0][0].isdigit() and "/" not in rows[0][0] else rows

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def check_iphone_backup() -> tuple[bool, str]:
    rows = _query(IMMICH_DSN, """
        SELECT COUNT(*) FROM asset
        WHERE "deletedAt" IS NULL
          AND "originalPath" LIKE '/usr/src/app/upload/upload/%'
    """)
    cnt = int(rows[0][0]) if rows else 0
    if cnt == 0:
        return False, "iPhone 백업 미시작 — Immich 앱 → 설정 → 자동 백업 활성"
    return True, f"iPhone 업로드 {cnt}장"


def check_14d_gate() -> tuple[bool, str]:
    rows = _query(DB_DSN, """
        SELECT COUNT(*) FROM photo.classification
        WHERE grade = ANY(ARRAY['NORMAL', 'TRASH', 'FOOD'])
          AND classified_at < NOW() - INTERVAL '14 days'
    """)
    aged = rows[0][0]
    if aged == 0:
        # 가장 오래된 분류 시각 → D-day 계산
        rows = _query(DB_DSN, """
            SELECT classified_at FROM photo.classification
            WHERE grade = ANY(ARRAY['NORMAL', 'TRASH', 'FOOD'])
            ORDER BY classified_at ASC LIMIT 1
        """)
        if rows:
            oldest = rows[0][0]
            d_day = (oldest.replace(tzinfo=timezone.utc) if oldest.tzinfo is None else oldest)
            target = d_day.timestamp() + 14 * 86400
            days_left = (target - datetime.now(timezone.utc).timestamp()) / 86400
            return False, f"14일 게이트 미충족 (D-{days_left:.1f}일)"
        return False, "분류 자산 없음"
    return True, f"14일 경과 자산 {aged}장 (cleanup 가능)"


def check_classify_service() -> tuple[bool, str]:
    try:
        r = httpx.get(f"{CLASSIFY_URL}/health", timeout=5)
        if r.status_code == 200 and r.json().get("ok"):
            return True, "classify-service 가동"
    except Exception:
        pass
    return False, "classify-service 미가동"


def check_external_exposure() -> tuple[bool, str]:
    try:
        r = httpx.get("https://photo.jwcloud.my/api/server/ping",
                      timeout=5, verify=False)
        if r.status_code == 200:
            return True, "https://photo.jwcloud.my 가동 (Immich)"
    except Exception:
        pass
    return False, "외부 노출 미확인"


def check_protect_endpoint() -> tuple[bool, str]:
    try:
        r = httpx.get(f"{CLASSIFY_URL}/feedback/protect", timeout=5)
        if r.status_code == 200:
            count = r.json().get("count", 0)
            return True, f"보호 메커니즘 가동 (현재 {count}건 보호)"
    except Exception:
        pass
    return False, "보호 메커니즘 미가동"


def send_telegram(text: str) -> None:
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
    checks = [
        ("iPhone 백업", check_iphone_backup()),
        ("14일 게이트", check_14d_gate()),
        ("classify-service", check_classify_service()),
        ("외부 노출", check_external_exposure()),
        ("보호 메커니즘", check_protect_endpoint()),
    ]
    print("📋 Phase 5 활성화 Readiness")
    all_ok = True
    for name, (ok, msg) in checks:
        mark = "✅" if ok else "⏳"
        print(f"  {mark} {name:18s} {msg}")
        if not ok:
            all_ok = False

    if all_ok:
        msg = (
            "🎉 <b>Phase 5 활성화 가능</b>\n"
            "모든 게이트 통과 — 사용자 명시 승인 시 Layer 6 iOS Shortcut 활성 가능.\n\n"
            "다음 단계:\n"
            "1. iPhone Shortcut 'Photo Cleanup (jw.son)' 의 [Show Notification] → [Delete Photos] 로 교체\n"
            "2. 첫 주: limit 20장 / 두번째 주: 100장 / 셋째 주: 무제한\n"
            "3. iCloud Recently Deleted 30일 안전망 확인"
        )
        print()
        print(msg.replace("<b>", "").replace("</b>", ""))
        send_telegram(msg)
    else:
        print()
        print("⏳ 미충족 항목 해결 후 재실행 (cron이 30분마다 자동 체크)")


if __name__ == "__main__":
    main()
