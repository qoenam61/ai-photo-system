#!/bin/bash
# memory_guard.sh — 메모리 압력 자동 감지 + 조치 sidecar
# 적용: */30 * * * * /Users/jw-home/Work/photo_system/ai-photo-system/scripts/memory_guard.sh
#
# 임계 값:
#   HIGH (>= 85%): immich-ml 정지 + photo-classify gc 강제 (process_pending limit=0 호출)
#   LOW  (<= 70%) AND immich-ml 정지 후 1시간 경과: immich-ml 자동 재개
#
# 압력 지표: (Wired + Compressor + Swap_used) / Total RAM

LOG=/Users/jw-home/Work/photo_system/ai-photo-system/scripts/_inventory/memory_guard.log
FLAG=/tmp/photo_memory_guard_immich_ml_stopped.ts
NOW_TS=$(date +%s)
NOW_HUMAN=$(date '+%Y-%m-%d %H:%M:%S')

# 1. 메모리 압력 계산 (간이)
PAGE_SIZE=16384
TOTAL_MB=$(sysctl -n hw.memsize | awk '{print $1/1024/1024}')

WIRED_PAGES=$(vm_stat | awk '/Pages wired/{print $4+0}')
COMP_PAGES=$(vm_stat | awk '/Pages occupied by compressor/{print $5+0}')
WIRED_MB=$(echo "$WIRED_PAGES $PAGE_SIZE" | awk '{print $1*$2/1024/1024}')
COMP_MB=$(echo "$COMP_PAGES $PAGE_SIZE" | awk '{print $1*$2/1024/1024}')
SWAP_USED_MB=$(sysctl vm.swapusage | awk -F'used = ' '{print $2}' | awk '{print $1+0}')

PRESSURE_MB=$(echo "$WIRED_MB $COMP_MB $SWAP_USED_MB" | awk '{print $1+$2+$3}')
PRESSURE_PCT=$(echo "$PRESSURE_MB $TOTAL_MB" | awk '{printf "%.0f", $1*100/$2}')

# 2. 상태 분기
ACTION=""

if [ "$PRESSURE_PCT" -ge 85 ]; then
  # HIGH: 조치
  if docker ps --filter name=immich-ml --filter status=running -q 2>/dev/null | grep -q .; then
    docker stop immich-ml >/dev/null 2>&1
    echo "$NOW_TS" > "$FLAG"
    ACTION="STOP immich-ml"
  fi
  # photo-classify gc 강제 (process_pending 0건이면 즉시 반환 + gc.collect 실행됨)
  curl -s --max-time 10 -X POST "http://localhost:8765/process_pending?limit=0" >/dev/null 2>&1
  ACTION="${ACTION:+$ACTION + }gc-classify"
elif [ "$PRESSURE_PCT" -le 70 ] && [ -f "$FLAG" ]; then
  # LOW: 재개 검토
  STOPPED_TS=$(cat "$FLAG")
  ELAPSED=$((NOW_TS - STOPPED_TS))
  if [ "$ELAPSED" -ge 3600 ]; then
    docker start immich-ml >/dev/null 2>&1
    rm -f "$FLAG"
    ACTION="RESUME immich-ml (정지 ${ELAPSED}초 경과)"
  else
    ACTION="HOLD (정지 ${ELAPSED}초, 1시간 미만)"
  fi
else
  ACTION="OK"
fi

# 3. 로그 기록
printf "[%s] pressure=%s%% wired=%.0fMB comp=%.0fMB swap=%.0fMB action=%s\n" \
  "$NOW_HUMAN" "$PRESSURE_PCT" "$WIRED_MB" "$COMP_MB" "$SWAP_USED_MB" "$ACTION" >> "$LOG"
