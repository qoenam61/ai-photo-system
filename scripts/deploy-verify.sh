#!/usr/bin/env bash
# 배포 검증 — 컨테이너 health + 핵심 엔드포인트 + DB 정합.
# FAIL > 0 시 exit 1 (배포 완료 선언 차단).

set -u

cd "$(dirname "$0")/.."

PASS=0
FAIL=0
WARN=0
FAILS=()

ok()   { PASS=$((PASS+1)); printf '  ✅ %-30s %s\n' "$1" "$2"; }
fail() { FAIL=$((FAIL+1)); FAILS+=("$1"); printf '  ❌ %-30s %s\n' "$1" "$2"; }
warn() { WARN=$((WARN+1)); printf '  ⚠️  %-30s %s\n' "$1" "$2"; }

echo "=== Photo System Deploy Verify ==="

# 1. 컨테이너 health
for c in photo-classify immich-server immich-postgres immich-redis trading_postgres trading_n8n; do
  status=$(docker inspect --format '{{.State.Health.Status}}' "$c" 2>/dev/null)
  if [ "$status" = "healthy" ]; then
    ok "container:$c" "healthy"
  else
    fail "container:$c" "${status:-not-running}"
  fi
done

# 2. classify-service 엔드포인트
for ep in /health /cleanup_audit '/feedback/protect'; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8765$ep")
  if [ "$code" = "200" ]; then ok "endpoint:$ep" "HTTP 200"; else fail "endpoint:$ep" "HTTP $code"; fi
done

# 3. POST 엔드포인트 (validation 422 = 정상)
for ep in /verify_backup /cleanup_enqueue; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8765$ep" \
        -H 'Content-Type: application/json' -d '{}')
  if [ "$code" = "422" ]; then ok "endpoint:$ep" "HTTP 422 (validation OK)"
  else fail "endpoint:$ep" "HTTP $code"; fi
done

# 4. Ollama
ollama_ok=$(curl -sf http://127.0.0.1:11434/api/tags 2>/dev/null | grep -c qwen2.5vl)
if [ "$ollama_ok" -gt 0 ]; then ok "ollama" "qwen2.5vl loaded"; else warn "ollama" "qwen2.5vl 미감지"; fi

# 5. DB 정합 (device별 분리 — NSC-10)
read -r classified queued processed hdd_ok mac_ok hdd_mb < <(docker exec -i trading_postgres psql -U trading_user -d trading_db -t -A -F ' ' -c "
SELECT
  (SELECT COUNT(*) FROM photo.classification),
  (SELECT COUNT(*) FROM photo.cleanup_queue),
  (SELECT COUNT(*) FROM photo.cleanup_queue WHERE processed_at IS NOT NULL),
  (SELECT COUNT(*) FROM photo.cleanup_audit WHERE success AND device='hdd'),
  (SELECT COUNT(*) FROM photo.cleanup_audit WHERE success AND device='mac-photos'),
  (SELECT COALESCE(SUM(reclaimed_bytes),0)/1024/1024 FROM photo.cleanup_audit WHERE success AND device='hdd');
" 2>/dev/null)

if [ -n "${classified:-}" ] && [ "$classified" -ge 1 ]; then
  ok "db:classification" "$classified rows"
else
  fail "db:classification" "rows=${classified:-?}"
fi
ok "db:cleanup_queue" "queued=$queued processed=$processed"
ok "db:cleanup_audit:hdd" "success=$hdd_ok reclaimed=${hdd_mb}MB"
ok "db:cleanup_audit:mac" "success=$mac_ok (Mac Photos 휴지통 이동, 디스크 회수 X)"

# 6. cleanup_audit success/failed 정합
audit_fail=$(docker exec -i trading_postgres psql -U trading_user -d trading_db -t -A -c \
  "SELECT COUNT(*) FROM photo.cleanup_audit WHERE NOT success" 2>/dev/null)
if [ "${audit_fail:-0}" -gt 0 ]; then
  warn "audit:failures" "$audit_fail rows (조회: SELECT * FROM photo.cleanup_audit WHERE NOT success;)"
else
  ok "audit:failures" "0"
fi

echo
echo "=== PASS $PASS / FAIL $FAIL / WARN $WARN ==="
if [ $FAIL -gt 0 ]; then
  echo "FAIL items: ${FAILS[*]}"
  exit 1
fi
exit 0
