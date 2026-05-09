-- 2026-05-09 안3 EVENT/EVENT-L 분할 (사용자 명시)
-- 목적: iCloud 50GB 한도 유지 (보존 4등급 122GB → 25GB)
--
-- 분할 정책:
--   EVENT  → EVENT+ (contains_child) / EVENT- (그 외, HDD only)
--   EVENT-L 이미지 → EVENT-L+ (contains_child) / EVENT-L- (그 외, HDD only)
--   EVENT-L 영상   → EVENT-L+ (source_path 본식) / EVENT-L- (iPhone 일상, HDD only)
--
-- BEST/MEMORY+/MEMORY-/NORMAL/FOOD/TRASH 그대로.
--
-- 적용:
--   docker exec -i trading_postgres psql -U trading_user -d trading_db \
--     < scripts/migrate_2026_05_09_event_split.sql

BEGIN;

-- 사전 분포
\echo '=== 사전 등급 분포 ==='
SELECT grade, COUNT(*) FROM photo.classification GROUP BY grade ORDER BY grade;

-- 1. EVENT 분할 — 자녀 등장 기반
UPDATE photo.classification
SET grade = CASE WHEN contains_child THEN 'EVENT+' ELSE 'EVENT-' END,
    updated_at = NOW()
WHERE grade = 'EVENT';

-- 2. EVENT-L 이미지 분할 — 자녀 등장 기반
UPDATE photo.classification
SET grade = CASE WHEN contains_child THEN 'EVENT-L+' ELSE 'EVENT-L-' END,
    updated_at = NOW()
WHERE grade = 'EVENT-L' AND is_video = FALSE;

-- 3. EVENT-L 영상 분할 — source_path 본식 폴더 매칭만 보존
UPDATE photo.classification
SET grade = CASE
              WHEN source_path ~* '본식' THEN 'EVENT-L+'
              ELSE 'EVENT-L-'
            END,
    updated_at = NOW()
WHERE grade = 'EVENT-L' AND is_video = TRUE;

-- 사후 분포
\echo '=== 사후 등급 분포 ==='
SELECT grade, COUNT(*),
       ROUND(SUM(file_size_bytes)/1024.0/1024/1024, 2) AS gb
FROM photo.classification GROUP BY grade ORDER BY grade;

COMMIT;
