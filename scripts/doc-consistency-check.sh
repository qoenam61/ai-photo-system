#!/usr/bin/env bash
# 문서 정합성 검증 — CLAUDE.md ↔ 코드 현실 일치 확인.
# 글로벌 SDLC sdlc-core.md "문서는 코드 현실과 항상 일치해야 한다" 원칙.
#
# Usage:
#   bash scripts/doc-consistency-check.sh         # 검증만 (FAIL > 0 시 exit 1)
#   bash scripts/doc-consistency-check.sh --fix   # 자동 수정 (지원되는 항목만)

set -u

cd "$(dirname "$0")/.."

FIX=0
[ "${1:-}" = "--fix" ] && FIX=1

PASS=0
FAIL=0
FAILS=()

ok()   { PASS=$((PASS+1)); printf '  ✅ %-40s %s\n' "$1" "$2"; }
fail() { FAIL=$((FAIL+1)); FAILS+=("$1"); printf '  ❌ %-40s %s\n' "$1" "$2"; }

echo "=== Doc Consistency Check ==="

# 1. CLAUDE.md "Phase 5 단축 활성화" 섹션 존재 (날짜 무관 grep)
if grep -qE "단축 결정 \(사용자 명시" CLAUDE.md; then
  ok "CLAUDE.md:phase5_fastlane" "단축 결정 섹션 존재"
else
  fail "CLAUDE.md:phase5_fastlane" "단축 결정 섹션 미발견"
fi

# 2. cleanup_service.py 존재 + classify_server.py에서 import
if [ -f core/service/cleanup_service.py ]; then
  ok "code:cleanup_service.py" "존재"
else
  fail "code:cleanup_service.py" "미존재"
fi
if grep -q "from core.service.cleanup_service" core/api/classify_server.py; then
  ok "code:cleanup_service_import" "classify_server에서 import"
else
  fail "code:cleanup_service_import" "import 없음 — 엔드포인트 미가동"
fi

# 3. cleanup_run.py 호스트 워커 + maintenance.sh hook
if [ -f scripts/cleanup_run.py ]; then
  ok "script:cleanup_run.py" "존재"
else
  fail "script:cleanup_run.py" "미존재"
fi
if grep -q "cleanup_run.py" scripts/maintenance.sh; then
  ok "script:maintenance_hook" "Layer 5 cleanup hook 등록"
else
  fail "script:maintenance_hook" "maintenance.sh에 cleanup_run hook 없음"
fi

# 4. phase5_ready.flag 존재 (progressive limit 활성)
if [ -f scripts/_inventory/phase5_ready.flag ]; then
  ok "flag:phase5_ready" "활성"
else
  fail "flag:phase5_ready" "미생성 — cleanup_candidates progressive=True 시 0 반환"
fi

# 5. 정식 TC 파일 존재
if [ -f wiki/03-pdca/active/report/TC-phase5-fastlane.md ]; then
  ok "tc:phase5_fastlane" "존재"
else
  fail "tc:phase5_fastlane" "미작성"
fi

# 6. SESSION-CHECKPOINT 날짜 ↔ 오늘 (or 어제) 일치
if [ -f handoff/SESSION-CHECKPOINT.md ]; then
  cp_date=$(grep -m1 -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' handoff/SESSION-CHECKPOINT.md | head -1)
  today=$(date +%Y-%m-%d)
  yesterday=$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d 'yesterday' +%Y-%m-%d)
  if [ "$cp_date" = "$today" ] || [ "$cp_date" = "$yesterday" ]; then
    ok "checkpoint:date" "$cp_date (today=$today)"
  else
    fail "checkpoint:date" "$cp_date (today=$today) — 24h 이상 미갱신"
  fi
else
  fail "checkpoint:file" "handoff/SESSION-CHECKPOINT.md 없음"
fi

# 7. CLAUDE.md 분류 진행 표시 vs 실제 DB
classified_db=$(docker exec -i trading_postgres psql -U trading_user -d trading_db -t -A -c \
  "SELECT COUNT(*) FROM photo.classification" 2>/dev/null)
if [ -n "${classified_db:-}" ] && [ "$classified_db" -ge 12000 ]; then
  ok "db:classification_count" "$classified_db (>= 12,000)"
else
  fail "db:classification_count" "$classified_db (분류 미완)"
fi

# 8. cleanup_queue.processed = cleanup_audit.success 정합
read -r processed audit_ok < <(docker exec -i trading_postgres psql -U trading_user -d trading_db -t -A -F ' ' -c "
SELECT
  (SELECT COUNT(*) FROM photo.cleanup_queue WHERE processed_at IS NOT NULL),
  (SELECT COUNT(*) FROM photo.cleanup_audit WHERE success);
" 2>/dev/null)
if [ "$processed" = "$audit_ok" ]; then
  ok "db:queue_audit_consistency" "processed=$processed = audit_success=$audit_ok"
else
  fail "db:queue_audit_consistency" "processed=$processed != audit_success=$audit_ok"
fi

echo
echo "=== PASS $PASS / FAIL $FAIL ==="
if [ $FAIL -gt 0 ]; then
  echo "FAIL items: ${FAILS[*]}"
  if [ $FIX -eq 1 ]; then
    echo "(--fix 자동 수정은 향후 구현 예정. 현재는 수동 수정 필요)"
  fi
  exit 1
fi
exit 0
