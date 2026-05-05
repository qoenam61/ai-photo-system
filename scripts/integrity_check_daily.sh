#!/usr/bin/env bash
# 데이터 무결성 일일 검증 — 매일 03:00 (maintenance 전).
# 노이즈 방지: 30분 cron 대신 일일 1회 + Telegram 알림.

set -u
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

cd /Users/jw-home/Work/photo_system/ai-photo-system

LOG=scripts/_inventory/integrity_$(date +%Y%m%d).log
mkdir -p scripts/_inventory
exec > >(tee -a "$LOG") 2>&1

POETRY=/Users/jw-home/.local/bin/poetry

echo "=== Integrity check start $(date) ==="

PYTHONPATH=. $POETRY run python scripts/integrity_check.py --telegram

echo "=== Integrity check done $(date) ==="
