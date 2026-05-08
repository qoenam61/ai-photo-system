"""복원 자산 자동 감지 + 보호 (DD-restored-asset-protection.md, 2026-05-07).

cleanup_audit (hdd success) 자산이 다시 살아난 두 경로를 detect:
  A. iPhone 휴지통 복원 + 재백업 — sha256 매칭 (새 photo.classification) [DEFAULT ON]
  B. Immich 휴지통 복원 — Immich asset.deletedAt NULL 복귀 [DEFAULT OFF]

경로 B default OFF 사유 (smoke test 발견 2026-05-07):
  현재 운영 DB 의 cleanup_audit hdd success 428건 中 379건이 Immich deletedAt=NULL.
  분석 결과 사용자 복원이 아니라 cleanup_run.py mark_immich_deleted subprocess
  실패 누적 (5월 4일부터 99% 실패). 별도 정합성 문제로 본 작업 범위 외.
  --enable-immich-detect 명시 시에만 경로 B 동작.

동작:
  1. detect → photo.feedback (feedback_type='restored') INSERT
  2. cleanup_queue UPDATE cancelled=TRUE (미처리 행만)
  3. Telegram 알림 (감지 1+ 시)

호출:
  - maintenance.sh [4.5/9] (30분 cron, dry-run 기본)
  - 수동: PYTHONPATH=. poetry run python scripts/detect_restored_assets.py [--no-dry-run]

옵션:
  --no-dry-run            실제 보호 등록 (default: dry-run, 로그만)
  --since-days N          retro-detect 윈도우 (default: 무제한)
  --enable-immich-detect  경로 B (Immich 휴지통) 활성. mark_immich_deleted 정합 후 권장.

도메인 안전 영역. 본 스크립트는 LLM 호출 X (DB/IO only) — 트레이딩 시간 무관.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.service.restored_detector import (  # noqa: E402
    detect_iphone_rebackup,
    detect_immich_trash_restore,
    mark_restored,
)

load_dotenv()


def notify_telegram(title: str, body: str) -> None:
    """notify_telegram.sh wrapper. 실패해도 무시 (알림은 best-effort)."""
    script = os.path.join(os.path.dirname(__file__), "notify_telegram.sh")
    if not os.path.exists(script):
        return
    try:
        subprocess.run(
            ["bash", script, title, body],
            capture_output=True, timeout=15,
        )
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-dry-run", action="store_true",
        help="명시해야 실제 photo.feedback INSERT + cleanup_queue cancel 수행",
    )
    parser.add_argument(
        "--since-days", type=int, default=None,
        help="retro-detect 윈도우 (None=무제한). 신규 활성화 시 None으로 1회 전수 처리 권장.",
    )
    parser.add_argument(
        "--quiet-telegram", action="store_true",
        help="감지 0건이어도 알림 안 함 (cron 안정 후 default 권장)",
    )
    parser.add_argument(
        "--enable-immich-detect", action="store_true",
        help="경로 B (Immich 휴지통 복원) 활성. mark_immich_deleted 정합 작업 후 권장.",
    )
    args = parser.parse_args()
    dry_run = not args.no_dry_run

    # 경로 A: iPhone 재백업 (sha256 매칭)
    pairs = detect_iphone_rebackup(since_days=args.since_days)
    a_targets = [p.new_asset_id for p in pairs]

    # 경로 B: Immich 휴지통 복원 (deletedAt NULL 복귀) — default OFF
    b_targets: list[str] = []
    if args.enable_immich_detect:
        b_targets = detect_immich_trash_restore()

    # 중복 제거 (경로 A 의 new_asset_id 와 B 의 asset_id 가 겹치는 경우 X — 다른 모집단이지만 안전)
    all_targets = list({*a_targets, *b_targets})

    print(f"🔍 복원 감지 결과:")
    print(f"   경로 A (iPhone 재백업, sha256 매칭): {len(pairs)}건")
    for p in pairs[:5]:
        print(f"     {p.old_asset_id[:8]} → {p.new_asset_id[:8]} (sha={p.sha256[:12]}...)")
    if len(pairs) > 5:
        print(f"     ... +{len(pairs) - 5}건")
    if args.enable_immich_detect:
        print(f"   경로 B (Immich 휴지통 복원): {len(b_targets)}건")
        for aid in b_targets[:5]:
            print(f"     {aid[:8]}")
        if len(b_targets) > 5:
            print(f"     ... +{len(b_targets) - 5}건")
    else:
        print(f"   경로 B: 비활성 (--enable-immich-detect 옵션 명시 시 활성)")
    print(f"   보호 등록 대상 (중복 제거): {len(all_targets)}건")

    if not all_targets:
        if not args.quiet_telegram and not dry_run:
            pass  # 0건은 알림 X (안정 후)
        print("✅ 복원 감지 없음")
        return 0

    if dry_run:
        print(f"\n💡 DRY-RUN — 실제 등록 X. --no-dry-run 명시 시 보호 등록.")
        return 0

    # 실제 보호 등록
    res = mark_restored(all_targets)
    print(f"\n📝 보호 등록 결과:")
    print(f"   feedback INSERT (신규 'restored'): {res.feedback_inserted}")
    print(f"   feedback 이미 있음 (skip):         {res.feedback_already}")
    print(f"   cleanup_queue cancelled:           {res.queue_cancelled}")
    if res.errors:
        print(f"   ⚠️  오류 {len(res.errors)}건:")
        for e in res.errors[:5]:
            print(f"     {e}")

    if res.feedback_inserted > 0:
        body = (
            f"복원 감지 자동 보호 등록\n"
            f"- iPhone 재백업: {len(pairs)}건\n"
            f"- Immich 휴지통 복원: {len(b_targets)}건\n"
            f"- 신규 보호 등록: {res.feedback_inserted}건\n"
            f"- cleanup_queue 취소: {res.queue_cancelled}건"
        )
        if len(b_targets) > 0:
            body += f"\n\n⚠️ Immich 휴지통 복원 자산은 HDD 파일이 이미 삭제됨 (broken_link). " \
                    f"iPhone 재백업으로 복구 권장."
        notify_telegram("Photo 복원 감지", body)

    return 0


if __name__ == "__main__":
    sys.exit(main())
