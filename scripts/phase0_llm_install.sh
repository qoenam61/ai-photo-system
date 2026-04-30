#!/usr/bin/env bash
# Phase 0-LLM — Ollama + Qwen2.5-VL 7B + Whisper-small 설치
# 설계: photo_system_design_v3.md §9 Phase 0-LLM
#       local_llm_evaluation.md §10 Phase 0-LLM 검증 계획
#
# 합격 기준 (Go/No-Go):
#   - 8등급 분류 정확도 ≥ 80% (사용자 라벨 100장 대비)
#   - 사진 1장 처리 시간 ≤ 6초
#   - 트레이딩 동시 가동 시 스왑 ≤ 100MB
#
# 사용: bash scripts/phase0_llm_install.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "🤖 Phase 0-LLM 설치 시작"
echo "  설계: photo_system_design_v3.md §9 Phase 0-LLM"
echo

# ──────────────────────────────────────────
# 1. Ollama 설치 확인
# ──────────────────────────────────────────
echo "▶ 1/4 Ollama 설치 확인"

if command -v ollama &> /dev/null; then
  OLLAMA_VER=$(ollama --version 2>&1 | head -1)
  echo "  ✅ Ollama 이미 설치됨: $OLLAMA_VER"
else
  echo "  Ollama 미설치. 설치 진행..."
  echo "  명령: brew install ollama"
  echo
  echo "  또는 공식 설치 스크립트:"
  echo "  curl -fsSL https://ollama.com/install.sh | sh"
  echo
  read -p "  brew install ollama 진행? (y/N): " yn
  if [[ "$yn" =~ ^[Yy]$ ]]; then
    /opt/homebrew/bin/brew install ollama
  else
    echo "  ❌ Ollama 설치 필요 — 수동 설치 후 재실행"
    exit 1
  fi
fi
echo

# ──────────────────────────────────────────
# 2. Ollama 서비스 시작
# ──────────────────────────────────────────
echo "▶ 2/4 Ollama 서비스 시작"

if ! pgrep -f "ollama serve" > /dev/null; then
  echo "  Ollama 백그라운드 시작..."
  brew services start ollama 2>&1 | head -3 || ollama serve &
  sleep 3
fi

if curl -s http://localhost:11434/api/version > /dev/null; then
  echo "  ✅ Ollama 실행 중 (http://localhost:11434)"
else
  echo "  ❌ Ollama 시작 실패 — 'ollama serve' 수동 실행 필요"
  exit 1
fi
echo

# ──────────────────────────────────────────
# 3. 모델 다운로드 (Qwen2.5-VL 7B + Whisper-small)
# ──────────────────────────────────────────
echo "▶ 3/4 모델 다운로드 (~5GB, 수 분 소요)"

# Qwen2.5-VL 7B Q4_K_M (4.5GB)
echo
echo "  📥 Qwen2.5-VL 7B Q4_K_M (4.5GB)"
if ollama list | grep -q "qwen2.5vl:7b"; then
  echo "  ✅ 이미 다운로드됨"
else
  echo "  다운로드 시작..."
  ollama pull qwen2.5vl:7b
fi

# Whisper-small (Ollama는 직접 지원 안 함, openai-whisper 별도 설치)
echo
echo "  📥 Whisper-small (한국어 음성 키워드용)"
echo "  ℹ️  Ollama는 Whisper 미지원 → Python openai-whisper 별도 설치"
echo "  poetry add openai-whisper"
echo "  (또는 LM Studio에서 별도 다운로드)"
echo

# ──────────────────────────────────────────
# 4. 간단 동작 검증
# ──────────────────────────────────────────
echo "▶ 4/4 간단 동작 검증"

echo "  Qwen2.5-VL 7B 로드 + 응답 시간 측정..."
START=$(date +%s)
RESP=$(curl -s http://localhost:11434/api/generate -d '{
  "model": "qwen2.5vl:7b",
  "prompt": "안녕하세요. 한국어로 짧게 답하세요.",
  "stream": false
}' | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('response','ERROR')[:80])")
END=$(date +%s)

echo "  응답 시간: $((END - START))초"
echo "  응답: $RESP"
echo

# 메모리 사용량
RSS_MB=$(ps aux | grep ollama | grep -v grep | awk '{s+=$6} END {print int(s/1024)}')
echo "  Ollama 메모리 사용: ${RSS_MB} MB"
echo

echo "✅ Phase 0-LLM 설치·기본 검증 완료"
echo
echo "다음 단계 (벤치마크):"
echo "  1. 사용자 사진 100장 준비 (jw.son 50 + eunju 50)"
echo "  2. 사용자 수동 라벨링 (8등급)"
echo "  3. poetry run python scripts/phase0_llm_benchmark.py"
echo "     → 정확도·속도·메모리 측정"
echo "  4. 합격 기준:"
echo "     - 8등급 정확도 ≥ 80%"
echo "     - 사진 1장 ≤ 6초"
echo "     - 트레이딩 동시 가동 시 스왑 ≤ 100MB"
echo
echo "Tier 1 미달 시 fallback: Qwen2.5-VL 3B (2.3GB)"
echo "  ollama pull qwen2.5vl:3b"
