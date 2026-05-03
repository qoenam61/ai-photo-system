#!/usr/bin/env bash
# 세션 종료 리포트 — wiki/03-pdca/active/report/YYYY-MM-DD.md append.
# 글로벌 SDLC commit-protocol.md "세션 종료 의무" 충족.
#
# Usage: bash scripts/session-report.sh "세션 제목"

set -eu

cd "$(dirname "$0")/.."

TITLE="${1:-세션 리포트}"
TODAY=$(date +%Y-%m-%d)
NOW=$(date '+%Y-%m-%d %H:%M:%S %Z')
DIR=wiki/03-pdca/active/report
FILE=$DIR/$TODAY.md

mkdir -p "$DIR"

if [ ! -f "$FILE" ]; then
  cat > "$FILE" <<HEADER
# 세션 리포트 — $TODAY

HEADER
fi

# 누적 통계 수집
read -r classified queued processed audit_ok reclaimed_mb < <(
  docker exec -i trading_postgres psql -U trading_user -d trading_db -t -A -F ' ' -c "
    SELECT
      (SELECT COUNT(*) FROM photo.classification),
      (SELECT COUNT(*) FROM photo.cleanup_queue),
      (SELECT COUNT(*) FROM photo.cleanup_queue WHERE processed_at IS NOT NULL),
      (SELECT COUNT(*) FROM photo.cleanup_audit WHERE success),
      (SELECT COALESCE(SUM(reclaimed_bytes),0)/1024/1024 FROM photo.cleanup_audit WHERE success);
  " 2>/dev/null
)

# 미커밋 파일
UNCOMMITTED=$(git status -s 2>/dev/null | wc -l | tr -d ' ')

cat >> "$FILE" <<APPEND

## $TITLE — $NOW

| 항목 | 값 |
|---|---|
| photo.classification | ${classified:-?}장 |
| cleanup_queue | total=${queued:-?} processed=${processed:-?} |
| cleanup_audit success | ${audit_ok:-?} |
| 누적 회수 | ${reclaimed_mb:-?} MB |
| 미커밋 파일 | $UNCOMMITTED |

APPEND

echo "✅ 세션 리포트 append → $FILE"
echo "   미커밋: ${UNCOMMITTED} 개"
