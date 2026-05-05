#!/usr/bin/env bash
# Telegram 알림 — cron 실패/이상 시 즉시 알림.
#
# Usage:
#   bash scripts/notify_telegram.sh "제목" "본문"
#
# 환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (.env)

set -u

cd "$(dirname "$0")/.."

# .env 로드
if [ -f .env ]; then
  TELEGRAM_BOT_TOKEN="$(grep '^TELEGRAM_BOT_TOKEN=' .env | head -1 | cut -d'=' -f2- | tr -d '\r\n"')"
  TELEGRAM_CHAT_ID="$(grep '^TELEGRAM_CHAT_ID=' .env | head -1 | cut -d'=' -f2- | tr -d '\r\n"')"
fi

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
  echo "(Telegram 미설정 — 알림 스킵)"
  exit 0
fi

TITLE="${1:-Photo System Alert}"
BODY="${2:-(no body)}"
HOST="$(hostname -s 2>/dev/null || echo unknown)"

MSG=$(printf '⚠️ <b>%s</b>\n<i>host: %s</i>\n\n%s' "$TITLE" "$HOST" "$BODY")

curl -sf -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${MSG}" \
  -d "parse_mode=HTML" \
  --max-time 10 > /dev/null 2>&1 || echo "(Telegram 전송 실패 — 무시)"
