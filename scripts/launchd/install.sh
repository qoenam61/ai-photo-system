#!/usr/bin/env bash
# launchd plist 설치/재로드 — git 버전 → ~/Library/LaunchAgents/ 자동 sync.
#
# Usage: bash scripts/launchd/install.sh
#
# 효과:
#   - scripts/launchd/*.plist (git, single source of truth) → ~/Library/LaunchAgents/ 복사
#   - launchctl unload + load (변경 즉시 반영)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="$HOME/Library/LaunchAgents"

mkdir -p "$TARGET_DIR"

for plist in "$SCRIPT_DIR"/*.plist; do
  [ -f "$plist" ] || continue
  name="$(basename "$plist")"
  target="$TARGET_DIR/$name"
  label="$(/usr/libexec/PlistBuddy -c 'Print :Label' "$plist" 2>/dev/null || echo "${name%.plist}")"

  echo "📋 $name → $target"
  launchctl unload -w "$target" 2>/dev/null || true
  cp "$plist" "$target"
  launchctl load -w "$target"

  if launchctl list | grep -q "$label"; then
    echo "  ✅ $label 등록"
  else
    echo "  ❌ $label 등록 실패"
  fi
done

echo
echo "✅ launchd 설치 완료. crontab과 같이 시간순:"
launchctl list | grep -iE 'photo|cleanup' | head
