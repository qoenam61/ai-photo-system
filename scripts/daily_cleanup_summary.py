"""일일 cleanup 요약 — 매일 09:00 KST (사용자 명시 2026-05-08).

전날 자동 정리 결과 + 잔여 정리 대기 자산을 Telegram으로 보고.
사용자가 결과 확인 후 추가 처리 원하면 `bash scripts/cleanup_now.sh` 명시 호출.

내용:
  - 24h cleanup_audit 분포 (reason_category 기반)
  - 정리 대기 자산 (FOOD/MEMORY-/NORMAL/TRASH 中 mac-photos·hdd 미처리)
  - ToDelete 앨범 잔여 (사용자 GUI 비우기 권장)
  - iCloud-only 자산 추정치 (DB-Mac 갭)
  - 단축 명령 안내

Usage:
  PYTHONPATH=. poetry run python scripts/daily_cleanup_summary.py [--telegram]

trigger: launchd com.photo.daily-summary.plist (매일 09:00 KST)
"""
from __future__ import annotations

import argparse
import os
import subprocess

import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)


def fetch_audit_24h() -> dict[str, dict[str, int]]:
    """device × reason_category 24h 분포."""
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT device, reason_category,
                   COUNT(*) FILTER (WHERE success) AS ok,
                   COUNT(*) FILTER (WHERE NOT success) AS fail
            FROM photo.cleanup_audit
            WHERE reported_at > NOW() - INTERVAL '24 hours'
            GROUP BY 1, 2 ORDER BY 1, 3 DESC
        """)
        out: dict[str, dict[str, int]] = {}
        for dev, cat, ok, fail in cur.fetchall():
            out.setdefault(dev, {})[cat or "unknown"] = ok + fail
        return out


def fetch_pending_cleanup() -> dict[str, int]:
    """4등급 외 정리 대기 자산 (mac/hdd 미처리)."""
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT c.grade, COUNT(*)
            FROM photo.classification c
            WHERE c.grade IN ('FOOD','MEMORY-','NORMAL','TRASH')
              AND NOT EXISTS (
                SELECT 1 FROM photo.cleanup_audit a
                WHERE a.asset_id = c.asset_id AND a.success
                  AND (a.device='mac-photos' OR a.device='hdd')
              )
              AND NOT EXISTS (
                SELECT 1 FROM photo.feedback f
                WHERE f.asset_id = c.asset_id
                  AND f.feedback_type IN ('protect','restored')
              )
            GROUP BY c.grade ORDER BY 2 DESC
        """)
        return dict(cur.fetchall())


def fetch_routing_24h() -> dict[str, int]:
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT
              SUM(CASE WHEN grade_source = 'llm_groq' THEN 1 ELSE 0 END) AS groq,
              SUM(CASE WHEN grade_source = 'llm_qwen' THEN 1 ELSE 0 END) AS qwen,
              SUM(CASE WHEN grade_source LIKE 'auto_%' THEN 1 ELSE 0 END) AS auto_fb,
              COUNT(*) AS total
            FROM photo.classification
            WHERE classified_at > NOW() - INTERVAL '24 hours'
        """)
        g, q, a, t = cur.fetchone()
    return {"groq": g or 0, "qwen": q or 0, "auto_fb": a or 0, "total": t or 0}


def todelete_count() -> int:
    """Mac Photos.app 🗑 ToDelete 앨범 잔여."""
    try:
        import osxphotos
        db = osxphotos.PhotosDB()
        td = next((a for a in db.album_info if a.title == "🗑 ToDelete"), None)
        return len(td.photos) if td else 0
    except Exception:
        return -1


def format_message(audit, pending, routing, td_n) -> str:
    lines = ["📸 <b>Photo System 일일 정리 요약</b>", ""]

    # 24h 처리 결과
    lines.append("<b>지난 24h 처리</b>:")
    if not audit:
        lines.append("  (처리 없음)")
    else:
        for dev, cats in audit.items():
            total = sum(cats.values())
            lines.append(f"  • {dev}: {total}장")
            for cat, n in sorted(cats.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"      {cat}: {n}")
    lines.append("")

    # 정리 대기
    pending_total = sum(pending.values())
    lines.append(f"<b>정리 대기 (Mac+iCloud)</b>: {pending_total}장")
    for g, n in pending.items():
        lines.append(f"  · {g}: {n}")
    lines.append("")

    # ToDelete
    if td_n > 0:
        lines.append(f"<b>🗑 ToDelete 앨범</b>: {td_n}장")
        lines.append("  → Mac Photos.app GUI에서 비우기 권장")
        lines.append("")
    elif td_n == 0:
        lines.append("<b>🗑 ToDelete 앨범</b>: 비어있음 ✓")
        lines.append("")

    # 분류
    if routing["total"] > 0:
        groq_pct = routing["groq"] / max(1, routing["groq"] + routing["qwen"]) * 100
        lines.append(
            f"<b>분류</b>: {routing['total']}장 "
            f"(Groq {routing['groq']} / Qwen {routing['qwen']} = "
            f"Groq {groq_pct:.0f}%)"
        )
        lines.append("")

    # 액션 가이드
    lines.append("<b>승인 명령</b> (잔여 일괄 정리):")
    lines.append("  <code>bash scripts/cleanup_now.sh</code>")
    lines.append("")
    lines.append("<b>iCloud 즉시 회수</b>: Mac Photos.app → 최근 삭제됨 → 모두 삭제")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--telegram", action="store_true",
                        help="Telegram 발송 (미명시: stdout만)")
    args = parser.parse_args()

    audit = fetch_audit_24h()
    pending = fetch_pending_cleanup()
    routing = fetch_routing_24h()
    td_n = todelete_count()
    msg = format_message(audit, pending, routing, td_n)

    print(msg.replace("<b>", "").replace("</b>", "")
              .replace("<i>", "").replace("</i>", "")
              .replace("<code>", "").replace("</code>", ""))

    if args.telegram:
        # HTML 형식 그대로 전송 (notify_telegram.sh가 parse_mode=HTML)
        subprocess.run(
            ["bash", "scripts/notify_telegram.sh",
             "📸 Photo 일일 정리 요약", msg],
            check=False,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
