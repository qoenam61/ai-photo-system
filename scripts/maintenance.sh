#!/usr/bin/env bash
# 유지보수 cron — health, 앨범, dedup, Immich sync, Layer 5 cleanup, reconcile, view.
# 30분 cron (Phase 5 안정화 dev 모드).
#
# 단계 실패 추적 (run_step + pipefail) + 종합 Telegram 알림.

set -u
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

cd /Users/jw-home/Work/photo_system/ai-photo-system

LOG=scripts/_inventory/maintenance_$(date +%Y%m%d).log
mkdir -p scripts/_inventory
exec > >(tee -a "$LOG") 2>&1

POETRY=/Users/jw-home/.local/bin/poetry
FAILED_STEPS=()

# bash -c 안에서 pipe 실패 추적 위해 항상 set -o pipefail 추가 (NSC-3 수정)
run_step() {
  local step_name="$1"
  shift
  if ! "$@"; then
    FAILED_STEPS+=("$step_name")
    echo "❌ FAIL: $step_name"
  fi
}

echo "=== Maintenance start $(date) ==="

# 0. Health (이상 시만 알림)
run_step "[0] health_monitor" \
  $POETRY run python scripts/health_monitor.py --alert-only

# 0b. Phase 5 활성화 readiness (idempotent — 첫 활성화 시 알림 1회)
READINESS_FLAG=scripts/_inventory/phase5_ready.flag
PHASE5_OUT=$($POETRY run python scripts/phase5_activation.py 2>&1) || true
if echo "$PHASE5_OUT" | grep -q "활성화 가능" && [ ! -f "$READINESS_FLAG" ]; then
  echo "$PHASE5_OUT"
  touch "$READINESS_FLAG"
fi

echo
echo "[1/10] iPhone 업로드 감지"
run_step "[1] monitor_iphone_uploads" \
  $POETRY run python scripts/monitor_iphone_uploads.py

echo
echo "[2/10] 추억앨범 갱신"
run_step "[2] build_albums" bash -c "
  set -o pipefail
  PYTHONPATH=. $POETRY run python scripts/build_albums.py 2>&1 | tail -25
"

echo
echo "[3/10] CLIP 앨범 dedup"
run_step "[3] dedup_album_clip" bash -c "
  set -o pipefail
  PYTHONPATH=. $POETRY run python scripts/dedup_album_clip.py --threshold 0.97 2>&1 | tail -15
"

echo
echo "[4/10] Immich Album 동기화"
run_step "[4] sync_immich_albums" bash -c "
  set -o pipefail
  PYTHONPATH=. $POETRY run python scripts/sync_immich_albums.py 2>&1 | tail -20
"

echo
echo "[5/10] 복원 자산 자동 보호 (DD-restored-asset-protection)"
run_step "[5] detect_restored_assets" bash -c "
  set -o pipefail
  PYTHONPATH=. $POETRY run python scripts/detect_restored_assets.py --no-dry-run --quiet-telegram 2>&1 | tail -10
"

echo
echo "[6/10] 신규 TRASH cleanup_queue 자동 등록 (grace 7일)"
run_step "[6] auto_enqueue_trash" bash -c "
  set -o pipefail
  PYTHONPATH=. $POETRY run python scripts/auto_enqueue_trash.py 2>&1 | tail -5
"

echo
echo "[7/10] Layer 5 HDD cleanup (grace 만료 + verify PASS만)"
run_step "[7] cleanup_run" bash -c "
  set -o pipefail
  PYTHONPATH=. $POETRY run python scripts/cleanup_run.py --limit 100 --no-dry-run 2>&1 | tail -10
"

echo
echo "[8/10] Immich deletedAt 정합 backfill (mark_immich_deleted 누락분 보정)"
run_step "[8] backfill_immich_deleted_at" bash -c "
  set -o pipefail
  PYTHONPATH=. $POETRY run python scripts/backfill_immich_deleted_at.py 2>&1 | tail -5
"

echo
echo "[9/10] 등급 폴더 정합 (reconcile)"
run_step "[9] reconcile_grade_folders" bash -c "
  set -o pipefail
  PYTHONPATH=. $POETRY run python scripts/reconcile_grade_folders.py 2>&1 | tail -8
"

echo
echo "[10/10] 등급별 view symlink 정합"
run_step "[10] build_grade_views" bash -c "
  set -o pipefail
  PYTHONPATH=. $POETRY run python scripts/build_grade_views.py 2>&1 | tail -10
"

# .DS_Store 정리 (macOS Finder 자동 생성, 무의미)
find /Volumes/Immich-Storage/immich-views -name '.DS_Store' -delete 2>/dev/null || true

echo
echo "=== Maintenance done $(date) ==="

# 실패 단계 발견 시 Telegram 알림
if [ ${#FAILED_STEPS[@]} -gt 0 ]; then
  bash scripts/notify_telegram.sh \
    "Photo maintenance.sh 실패" \
    "$(date '+%Y-%m-%d %H:%M') 다음 단계 FAIL:
$(printf -- '- %s\n' "${FAILED_STEPS[@]}")

로그: $LOG"
fi
