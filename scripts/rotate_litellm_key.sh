#!/usr/bin/env bash
# LITELLM_MASTER_KEY 자동 회전 — self-managed 키 분기 회전.
#
# 흐름:
#   1. macOS Keychain에서 현재 키 읽기 (또는 .env)
#   2. 새 UUID 키 생성
#   3. /Users/jw-home/.llm/.env 업데이트
#   4. classify-service docker-compose env 업데이트 (재시작 X — 다음 04:00 재시작 시 적용)
#   5. LiteLLM proxy 재시작
#   6. 기존 키와 신규 키 사용 검증 (구버전은 grace 1일)
#
# 외부 API 키 (GROQ_API_KEY, IMMICH_API_KEY)는 사용자 측 발급.
# 본 스크립트는 self-managed LITELLM_MASTER_KEY만 자동 회전.
#
# 분기 cron (3개월): 1 0 1 1,4,7,10 *
#
# Usage: bash scripts/rotate_litellm_key.sh

set -u
cd /Users/jw-home/Work/photo_system/ai-photo-system

LOG=scripts/_inventory/secret_rotation_$(date +%Y%m%d).log
mkdir -p scripts/_inventory
exec > >(tee -a "$LOG") 2>&1

echo "=== LITELLM_MASTER_KEY 회전 시작 $(date) ==="

# 1. 새 키 생성 (macOS uuidgen)
NEW_KEY="ll-$(uuidgen | tr -d '-' | tr 'A-Z' 'a-z')"
echo "신규 키: ${NEW_KEY:0:16}*** (${#NEW_KEY} chars)"

# 2. LiteLLM .env 백업 + 업데이트
LLM_ENV=/Users/jw-home/.llm/.env
if [ ! -f "$LLM_ENV" ]; then
  echo "❌ $LLM_ENV 미존재"
  exit 1
fi

cp "$LLM_ENV" "$LLM_ENV.bak.$(date +%Y%m%d)"
sed -i.tmp "s|^LITELLM_MASTER_KEY=.*|LITELLM_MASTER_KEY=$NEW_KEY|" "$LLM_ENV"
rm -f "$LLM_ENV.tmp"
echo "✅ $LLM_ENV 갱신"

# 3. macOS Keychain 보존 (사용자 측 백업)
security delete-generic-password -s "litellm_master_key" 2>/dev/null || true
security add-generic-password -s "litellm_master_key" -a "$USER" -w "$NEW_KEY"
echo "✅ macOS Keychain 보존"

# 4. LiteLLM proxy 재시작
cd /Users/jw-home/.llm
docker compose down
docker compose up -d
sleep 5

# 5. 인증 검증 (신규 키)
RESP=$(curl -s -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $NEW_KEY" \
  http://localhost:4000/v1/models --max-time 5)
if [ "$RESP" != "200" ]; then
  echo "❌ 신규 키 인증 FAIL (HTTP $RESP)"
  bash /Users/jw-home/Work/photo_system/ai-photo-system/scripts/notify_telegram.sh \
    "LITELLM 키 회전 실패" "신규 키 인증 fail (HTTP $RESP)"
  exit 1
fi
echo "✅ 신규 키 인증 PASS"

# 6. classify-service .env 업데이트 (다음 재시작 시 적용)
cd /Users/jw-home/Work/photo_system/ai-photo-system
# classify-service는 docker-compose.yml의 environment에서 LITELLM_MASTER_KEY 명시 X.
# Dockerfile.classify의 ENV LITELLM_MASTER_KEY=... 또는 docker-compose env 지정 필요.
# 현재는 LITELLM_BASE_URL만 명시 → 키는 LITELLM proxy의 env로 전달됨.
# 따라서 classify-service 측 변경 불필요 (LiteLLM proxy의 env LITELLM_MASTER_KEY가 인증 KEY).

# 단 photo-classify에 LITELLM_MASTER_KEY env 명시되어 있으면 갱신 필요
docker exec photo-classify env | grep -q "^LITELLM_MASTER_KEY=local-litellm-key" && {
  echo "⚠️  photo-classify가 옛 키 사용 중 — 컨테이너 재시작 권장"
  bash scripts/notify_telegram.sh \
    "LITELLM 키 회전 — 컨테이너 재시작 필요" \
    "photo-classify가 옛 키 환경변수 보유. 04:00 일일 재시작 시 자동 갱신 예정."
}

echo "=== 회전 완료 $(date) ==="
echo "다음 회전: 3개월 후"
