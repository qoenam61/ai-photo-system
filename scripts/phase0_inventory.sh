#!/usr/bin/env bash
# Phase 0 — 사진 시스템 사전 자산 인벤토리
# 설계: photo_system_design_v3.md §9 Phase 0
#
# 측정 항목:
#   1. 시스템 baseline (디스크·메모리·트레이딩 영향 측정)
#   2. iPhone iCloud 사진 라이브러리 (jw.son)
#   3. Galaxy 사진 (eunju, USB 연결 후)
#   4. 코덱 분포 (HEIC/HEVC/JPEG/MP4 비율)
#   5. 변환 후 예상 용량 산출
#
# 출력: scripts/_inventory/inventory.json
# 사용: bash scripts/phase0_inventory.sh
#
# 주의: 갤럭시는 USB 연결 + OpenMTP 마운트 후 실행
#       (없으면 갤럭시 측정은 skip)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$REPO_ROOT/scripts/_inventory"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/inventory.json"
DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)

echo "📊 Phase 0 인벤토리 측정 시작 — $DATE"
echo

# ──────────────────────────────────────────
# 1. 시스템 baseline
# ──────────────────────────────────────────
echo "▶ 1/5 시스템 baseline"

SSD_TOTAL_GB=$(df -g / | awk 'NR==2 {print $2}')
SSD_USED_GB=$(df -g / | awk 'NR==2 {print $3}')
SSD_AVAIL_GB=$(df -g / | awk 'NR==2 {print $4}')

MEM_TOTAL_GB=$(($(sysctl -n hw.memsize) / 1024 / 1024 / 1024))
MEM_PRESSURE=$(memory_pressure 2>/dev/null | awk '/percentage of memory free/ {print $5}' || echo "N/A")

CPU_MODEL=$(sysctl -n machdep.cpu.brand_string)
CPU_CORES=$(sysctl -n hw.ncpu)

echo "  SSD: ${SSD_USED_GB}/${SSD_TOTAL_GB} GB used (${SSD_AVAIL_GB} GB 가용)"
echo "  RAM: ${MEM_TOTAL_GB} GB"
echo "  CPU: $CPU_MODEL ($CPU_CORES cores)"
echo

# ──────────────────────────────────────────
# 2. iPhone iCloud 사진 라이브러리 (Photos.app)
# ──────────────────────────────────────────
echo "▶ 2/5 iPhone (jw.son) Photos 라이브러리"

PHOTOS_LIB="$HOME/Pictures/Photos Library.photoslibrary"
JW_TOTAL_BYTES=0
JW_TOTAL_COUNT=0
JW_HEIC_COUNT=0
JW_HEVC_COUNT=0
JW_JPEG_COUNT=0
JW_MP4_COUNT=0
JW_LIVE_PHOTO_PAIRS=0

if [[ -d "$PHOTOS_LIB" ]]; then
  echo "  라이브러리 발견: $PHOTOS_LIB"
  echo "  (originals/ 스캔 — 시간 소요 가능)"

  if [[ -d "$PHOTOS_LIB/originals" ]]; then
    JW_TOTAL_BYTES=$(find "$PHOTOS_LIB/originals" -type f \
      \( -iname "*.heic" -o -iname "*.jpg" -o -iname "*.jpeg" \
         -o -iname "*.mov" -o -iname "*.mp4" -o -iname "*.heif" \
         -o -iname "*.dng" -o -iname "*.png" \) \
      -exec stat -f "%z" {} + 2>/dev/null | awk '{s+=$1} END {print s+0}')

    JW_TOTAL_COUNT=$(find "$PHOTOS_LIB/originals" -type f \
      \( -iname "*.heic" -o -iname "*.jpg" -o -iname "*.jpeg" \
         -o -iname "*.mov" -o -iname "*.mp4" -o -iname "*.heif" \
         -o -iname "*.dng" -o -iname "*.png" \) 2>/dev/null | wc -l | tr -d ' ')

    JW_HEIC_COUNT=$(find "$PHOTOS_LIB/originals" -type f \
      \( -iname "*.heic" -o -iname "*.heif" \) 2>/dev/null | wc -l | tr -d ' ')
    JW_HEVC_COUNT=$(find "$PHOTOS_LIB/originals" -type f -iname "*.mov" 2>/dev/null | wc -l | tr -d ' ')
    JW_JPEG_COUNT=$(find "$PHOTOS_LIB/originals" -type f \
      \( -iname "*.jpg" -o -iname "*.jpeg" \) 2>/dev/null | wc -l | tr -d ' ')
    JW_MP4_COUNT=$(find "$PHOTOS_LIB/originals" -type f -iname "*.mp4" 2>/dev/null | wc -l | tr -d ' ')

    # Live Photo: HEIC + 같은 이름 MOV 페어
    JW_LIVE_PHOTO_PAIRS=$(find "$PHOTOS_LIB/originals" -type f -iname "*.heic" 2>/dev/null \
      | while read -r heic; do
          base="${heic%.*}"
          [[ -f "${base}.mov" || -f "${base}.MOV" ]] && echo "1"
        done | wc -l | tr -d ' ')
  fi

  JW_GB=$((JW_TOTAL_BYTES / 1024 / 1024 / 1024))
  echo "  jw.son: $JW_TOTAL_COUNT 개, ${JW_GB} GB"
  echo "    HEIC: $JW_HEIC_COUNT, HEVC(MOV): $JW_HEVC_COUNT, JPEG: $JW_JPEG_COUNT, MP4: $JW_MP4_COUNT"
  echo "    Live Photo 페어: $JW_LIVE_PHOTO_PAIRS"
else
  echo "  ⚠️  Photos 라이브러리 없음 ($PHOTOS_LIB) — iCloud 동기화 활성화 + 원본 다운로드 후 재실행"
fi
echo

# ──────────────────────────────────────────
# 3. Galaxy 사진 (USB 연결 시)
# ──────────────────────────────────────────
echo "▶ 3/5 Galaxy (eunju)"

EUNJU_TOTAL_BYTES=0
EUNJU_TOTAL_COUNT=0
EUNJU_NOTE="Not measured"

# OpenMTP 마운트 또는 USB MTP 경로 시도
GALAXY_PATHS=(
  "/Volumes/Galaxy/DCIM/Camera"
  "/Volumes/SM-*/DCIM/Camera"
  "$HOME/galaxy_export/DCIM/Camera"
)

for p in "${GALAXY_PATHS[@]}"; do
  for pp in $p; do
    if [[ -d "$pp" ]]; then
      EUNJU_TOTAL_BYTES=$(find "$pp" -type f -exec stat -f "%z" {} + 2>/dev/null \
        | awk '{s+=$1} END {print s+0}')
      EUNJU_TOTAL_COUNT=$(find "$pp" -type f 2>/dev/null | wc -l | tr -d ' ')
      EUNJU_NOTE="Found at $pp"
      break 2
    fi
  done
done

EUNJU_GB=$((EUNJU_TOTAL_BYTES / 1024 / 1024 / 1024))
echo "  eunju: $EUNJU_TOTAL_COUNT 개, ${EUNJU_GB} GB — $EUNJU_NOTE"
[[ "$EUNJU_NOTE" == "Not measured" ]] && \
  echo "  ℹ️  Galaxy USB 연결 + OpenMTP 마운트 후 재실행하면 측정됨"
echo

# ──────────────────────────────────────────
# 4. 변환 후 예상 용량 산출
# ──────────────────────────────────────────
echo "▶ 4/5 변환 후 예상 용량"

# HEIC → JPEG: 약 1.5배
# HEVC → H.264: 약 1.3배
# JPEG/MP4 그대로
JW_HEIC_BYTES=$((JW_HEIC_COUNT * 4 * 1024 * 1024))  # 평균 HEIC 4MB 가정
JW_HEVC_BYTES=$((JW_HEVC_COUNT * 50 * 1024 * 1024)) # 평균 MOV 50MB 가정
JW_HEIC_AFTER=$((JW_HEIC_BYTES * 15 / 10))
JW_HEVC_AFTER=$((JW_HEVC_BYTES * 13 / 10))
JW_OTHER_BYTES=$((JW_TOTAL_BYTES - JW_HEIC_BYTES - JW_HEVC_BYTES))
JW_AFTER_BYTES=$((JW_HEIC_AFTER + JW_HEVC_AFTER + JW_OTHER_BYTES))
JW_AFTER_GB=$((JW_AFTER_BYTES / 1024 / 1024 / 1024))

TOTAL_AFTER_GB=$((JW_AFTER_GB + EUNJU_GB))

echo "  jw.son 변환 후 예상: ${JW_AFTER_GB} GB (HEIC ×1.5, HEVC ×1.3 가정)"
echo "  eunju 변환 후 예상: ~${EUNJU_GB} GB"
echo "  합계 예상: ${TOTAL_AFTER_GB} GB"
echo "  → SSD 가용 ${SSD_AVAIL_GB} GB 의 70%: $((SSD_AVAIL_GB * 7 / 10)) GB"
echo

if [[ $TOTAL_AFTER_GB -gt $((SSD_AVAIL_GB * 7 / 10)) ]]; then
  echo "  ⚠️  변환 후 예상 용량이 SSD 가용 70% 초과 — 점진 백필 전략 필수 (§17b)"
else
  echo "  ✅ SSD 임시 vault 가용 — Phase 1~5 진행 가능"
fi
echo

# ──────────────────────────────────────────
# 5. JSON 출력
# ──────────────────────────────────────────
echo "▶ 5/5 결과 JSON 저장"

cat > "$OUT" <<EOF
{
  "measured_at": "$DATE",
  "system": {
    "ssd_total_gb": $SSD_TOTAL_GB,
    "ssd_used_gb": $SSD_USED_GB,
    "ssd_available_gb": $SSD_AVAIL_GB,
    "ram_total_gb": $MEM_TOTAL_GB,
    "memory_pressure_pct_free": "$MEM_PRESSURE",
    "cpu_model": "$CPU_MODEL",
    "cpu_cores": $CPU_CORES
  },
  "jw_son": {
    "library_path": "$PHOTOS_LIB",
    "total_count": $JW_TOTAL_COUNT,
    "total_bytes": $JW_TOTAL_BYTES,
    "total_gb": $JW_GB,
    "heic_count": $JW_HEIC_COUNT,
    "hevc_mov_count": $JW_HEVC_COUNT,
    "jpeg_count": $JW_JPEG_COUNT,
    "mp4_count": $JW_MP4_COUNT,
    "live_photo_pairs": $JW_LIVE_PHOTO_PAIRS,
    "estimated_after_conversion_gb": $JW_AFTER_GB
  },
  "eunju": {
    "total_count": $EUNJU_TOTAL_COUNT,
    "total_bytes": $EUNJU_TOTAL_BYTES,
    "total_gb": $EUNJU_GB,
    "note": "$EUNJU_NOTE"
  },
  "total_estimated_after_gb": $TOTAL_AFTER_GB,
  "ssd_70pct_threshold_gb": $((SSD_AVAIL_GB * 7 / 10)),
  "phase1_gate_pass": $([ $TOTAL_AFTER_GB -le $((SSD_AVAIL_GB * 7 / 10)) ] && echo "true" || echo "false")
}
EOF

echo "  저장: $OUT"
echo
echo "✅ Phase 0 인벤토리 완료"
echo
echo "다음 단계:"
echo "  - Phase 0 게이트 통과 시 → Phase 0-LLM 스크립트 실행"
echo "  - 게이트 미달 시 → 점진 백필 전략 적용 (§17b)"
