#!/usr/bin/env bash
# LLM-only 완료 후 자동 chain.
# polling으로 LLM 프로세스 종료 확인 → 후처리 자동.

set -e
cd /Users/jw-home/Work/photo_system/ai-photo-system

LOG=scripts/_inventory/after_llm_chain.log
mkdir -p scripts/_inventory
exec > >(tee -a "$LOG") 2>&1

echo "=== After-LLM Chain 시작 $(date) ==="

# 1. LLM-only 종료 대기 (5분 polling)
while pgrep -f "migrate_backup.py --llm-only" > /dev/null; do
  echo "$(date '+%H:%M') LLM-only 진행 중... (5분 후 재확인)"
  sleep 300
done

echo "✅ LLM-only 종료 감지 $(date)"
sleep 30  # safe margin

# 2. DB SHA256 dedup
echo
echo "[1/5] DB dedup"
docker exec trading_postgres psql -U trading_user -d trading_db -c "
DELETE FROM photo.classification
WHERE asset_id IN (
  SELECT asset_id FROM (
    SELECT asset_id, ROW_NUMBER() OVER (PARTITION BY sha256 ORDER BY classified_at) AS rn
    FROM photo.classification WHERE sha256 IS NOT NULL
  ) s WHERE rn > 1
);
SELECT 'after dedup', grade, COUNT(*) FROM photo.classification GROUP BY grade ORDER BY grade;
"

# 3. Storage reconcile (orphan)
echo
echo "[2/5] Storage reconcile"
PYTHONPATH=. /Users/jw-home/.local/bin/poetry run python scripts/reconcile_storage.py --apply

# 4. BEST 유사컷 강등 (옵션 C, 권장)
echo
echo "[3/5] BEST 유사컷 강등 (시간 ±10초 + 카메라 동일)"
docker exec trading_postgres psql -U trading_user -d trading_db -c "
WITH ranked AS (
  SELECT asset_id,
    ROW_NUMBER() OVER (
      PARTITION BY camera_make, camera_model,
                   FLOOR(EXTRACT(EPOCH FROM exif_datetime) / 10)
      ORDER BY (COALESCE(laplacian_variance, 0) * file_size_bytes) DESC NULLS LAST,
               file_size_bytes DESC
    ) AS rn,
    COUNT(*) OVER (
      PARTITION BY camera_make, camera_model,
                   FLOOR(EXTRACT(EPOCH FROM exif_datetime) / 10)
    ) AS gs
  FROM photo.classification
  WHERE grade = 'BEST' AND exif_datetime IS NOT NULL
)
UPDATE photo.classification c
SET grade = 'MEMORY+', grade_source = 'dedup_demoted', updated_at = NOW()
FROM ranked r
WHERE c.asset_id = r.asset_id AND r.rn > 1 AND r.gs > 1;
"

# 5. 추억앨범 재생성
echo
echo "[4/5] 추억앨범 재생성"
docker exec trading_postgres psql -U trading_user -d trading_db -c \
  "TRUNCATE photo.album, photo.album_member RESTART IDENTITY CASCADE;"
PYTHONPATH=. /Users/jw-home/.local/bin/poetry run python scripts/build_albums.py

# 6. Immich Album 동기화 (등급 + 추억)
echo
echo "[5/5] Immich Album 재동기화"
KEY=$(grep IMMICH_API_KEY .env | cut -d= -f2)
TARGETS="⭐ EVENT|⭐ EVENT-L|✦ BEST|🍽 FOOD|◆ MEMORY+|◇ MEMORY-|○ NORMAL|🗑 TRASH"
/usr/bin/curl -s -H "x-api-key: $KEY" http://localhost:2283/api/albums | \
  python3 -c "
import json, sys
albums = json.load(sys.stdin)
targets = '$TARGETS'.split('|')
for a in albums:
    if a['albumName'] in targets:
        print(a['id'])
" | while read id; do
  /usr/bin/curl -s -X DELETE "http://localhost:2283/api/albums/$id" -H "x-api-key: $KEY" > /dev/null
done
PYTHONPATH=. /Users/jw-home/.local/bin/poetry run python scripts/sync_immich_albums.py

# 7. 최종 통계
echo
echo "=== 최종 통계 $(date) ==="
docker exec trading_postgres psql -U trading_user -d trading_db -c "
SELECT 'classification' AS t, grade, COUNT(*) FROM photo.classification GROUP BY grade
UNION ALL SELECT 'album', name, asset_count::text::int::int FROM photo.album ORDER BY 1, 2;
" 2>&1 | head -30

echo "=== After-LLM Chain 완료 $(date) ==="
