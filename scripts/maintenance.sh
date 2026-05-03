#!/usr/bin/env bash
# 유지보수 cron — 신규 자산 감지 + 앨범 동기화.
#
# 일정:
#   개발 중: 30분마다 (크론 매시 0/30분)
#   배포 후: 매일 03:00
#
# 동작:
#   1. iPhone 업로드 감지 (monitor_iphone_uploads.py)
#   2. 추억앨범 갱신 (build_albums.py)
#   3. CLIP 앨범 dedup (dedup_album_clip.py)
#   4. Immich Album 동기화 (sync_immich_albums.py)
#   5. 통계 출력

set -e
cd /Users/jw-home/Work/photo_system/ai-photo-system

LOG=scripts/_inventory/maintenance_$(date +%Y%m%d).log
mkdir -p scripts/_inventory
exec > >(tee -a "$LOG") 2>&1

echo "=== Maintenance start $(date) ==="

POETRY=/Users/jw-home/.local/bin/poetry

# 0. Health (이상 시만 알림)
PYTHONPATH=. $POETRY run python scripts/health_monitor.py --alert-only

# 0b. Phase 5 활성화 readiness (전부 PASS 시 Telegram 알림 1회)
# 알림 중복 방지: 활성화 가능 상태 첫 도달 시만 알림 → 파일 기반 idempotent
READINESS_FLAG=scripts/_inventory/phase5_ready.flag
PHASE5_OUT=$(PYTHONPATH=. $POETRY run python scripts/phase5_activation.py 2>&1)
if echo "$PHASE5_OUT" | grep -q "활성화 가능" && [ ! -f "$READINESS_FLAG" ]; then
  echo "$PHASE5_OUT"  # 첫 활성화 가능 시점 로그
  touch "$READINESS_FLAG"
fi

# 1. iPhone 업로드 감지 (정보용 — Phase 4 파이프라인 완성까지 dry-run)
echo
echo "[1/4] iPhone 업로드 감지"
PYTHONPATH=. $POETRY run python scripts/monitor_iphone_uploads.py

# 2. 추억앨범 갱신 (재실행 안전 — get_or_create_album이 UPSERT)
echo
echo "[2/4] 추억앨범 갱신"
PYTHONPATH=. $POETRY run python scripts/build_albums.py 2>&1 | tail -25

# 3. CLIP 앨범 dedup (이미 정리된 앨범은 변경 0)
echo
echo "[3/4] CLIP 앨범 중복 정리"
PYTHONPATH=. $POETRY run python scripts/dedup_album_clip.py --threshold 0.97 2>&1 | tail -15

# 4. Immich 동기화 (기존 앨범에 신규 자산만 PUT — 이미 추가된 것은 중복 안 됨)
echo
echo "[4/4] Immich Album 동기화"
PYTHONPATH=. $POETRY run python scripts/sync_immich_albums.py 2>&1 | tail -20

# 5. Layer 5 HDD cleanup — grace 만료 자산 영구삭제 (도메인 안전)
# 정책: cleanup_queue grace_until <= NOW + verify PASS + 미보호. limit 100 / 1회.
echo
echo "[5/5] Layer 5 HDD cleanup"
PYTHONPATH=. $POETRY run python scripts/cleanup_run.py --limit 100 --no-dry-run 2>&1 | tail -10

echo
echo "=== Maintenance done $(date) ==="
