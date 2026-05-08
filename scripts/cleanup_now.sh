#!/usr/bin/env bash
# 잔여 cleanup 일괄 처리 — 사용자 명시 승인 후 호출.
# daily_cleanup_summary.py 알림에서 안내된 단축 명령.
#
# 흐름:
#   1. cleanup_run.py — HDD 정리 (cleanup_queue grace 만료 자산)
#   2. cleanup_mac_non_icloud.py — 4등급 외 Mac 정리 (delete-by-meta fallback)
#   3. cleanup_photos_mac.py — verify 통과 자산 (PhotoKit UUID 매칭)
#
# 매번 호출 가능 (idempotent — 이미 처리된 자산은 query에서 제외).

set -u
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

cd /Users/jw-home/Work/photo_system/ai-photo-system

POETRY=/Users/jw-home/.local/bin/poetry
LOG=scripts/_inventory/cleanup_now_$(date +%Y%m%d_%H%M%S).log
mkdir -p scripts/_inventory
exec > >(tee -a "$LOG") 2>&1

echo "=== Cleanup now start $(date) ==="
echo

echo "[1/3] HDD cleanup (Layer 5)"
PYTHONPATH=. $POETRY run python scripts/cleanup_run.py --limit 500 --no-dry-run 2>&1 | tail -10
echo

echo "[2/3] Mac Photos non-iCloud (4등급 외)"
PYTHONPATH=. $POETRY run python scripts/cleanup_mac_non_icloud.py --limit 0 2>&1 | tail -15
echo

echo "[3/3] Mac Photos verify-passed (PhotoKit UUID 매칭)"
PYTHONPATH=. $POETRY run python scripts/cleanup_photos_mac.py --no-progressive --grades "FOOD,MEMORY-,NORMAL,TRASH" --limit 1000 --min-age-days 0 2>&1 | tail -10
echo

echo "=== Cleanup now done $(date) ==="
echo
echo "💡 즉시 iCloud 회수: Mac Photos.app → 최근 삭제됨 → 모두 삭제"
