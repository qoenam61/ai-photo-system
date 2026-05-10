-- 2026-05-11 ABCD 등급 세분화 (사용자 명시) + 잔여 backfill
-- 등급 자체는 10개 유지, sub_category 컬럼 추가로 단일 파이프라인 보존.
--
-- A. MEMORY+ → image / video
-- B. EVENT+/EVENT-L+ → wedding / family / birthday / anniversary / video / other
-- C. TRASH → duplicate / screenshot / no_face / short_video / llm
-- D. BEST → portrait / landscape
-- + 잔여 백필: EVENT 행사 환각 18장 + BEST 흐림 118장 강등

BEGIN;

-- 0. sub_category 컬럼 추가
ALTER TABLE photo.classification
  ADD COLUMN IF NOT EXISTS sub_category VARCHAR(40);

CREATE INDEX IF NOT EXISTS idx_classification_subcategory
  ON photo.classification (grade, sub_category);

COMMENT ON COLUMN photo.classification.sub_category IS
  '등급 내부 세분화 라벨 (10등급 등급 자체는 유지 — 정책 분기는 grade로만).
   2026-05-11 ABCD 세분화 추가.';

-- ============================================================================
-- A. MEMORY+ → image / video
-- ============================================================================
UPDATE photo.classification
SET sub_category = CASE WHEN is_video THEN 'video' ELSE 'image' END
WHERE grade = 'MEMORY+';

-- ============================================================================
-- B. EVENT+/EVENT-L+ → wedding / family / video / birthday / other
-- ============================================================================
-- EVENT+ (이미지 행사)
UPDATE photo.classification
SET sub_category = CASE
  -- 결혼식 폴더 (사용자 명시) — 최우선
  WHEN grade_source LIKE 'folder_bulk%' THEN 'wedding'
  -- 자녀 등장 + 카메라 명시 (DSLR/iPhone) = 가족 행사
  WHEN contains_child AND COALESCE(camera_make,'') != '' THEN 'family'
  -- 자녀 등장만 = 일반 가족
  WHEN contains_child THEN 'family'
  -- 자녀 미등장이지만 EVENT+로 분류 = 행사 사진 (성인 다수)
  ELSE 'other'
END
WHERE grade = 'EVENT+';

-- EVENT-L+ (long form)
UPDATE photo.classification
SET sub_category = CASE
  WHEN is_video AND grade_source LIKE 'folder_bulk_no_convert%' THEN 'wedding_video'
  WHEN is_video THEN 'video'
  WHEN grade_source LIKE 'folder_bulk%' THEN 'wedding'
  WHEN contains_child THEN 'family'
  ELSE 'other'
END
WHERE grade = 'EVENT-L+';

-- EVENT-/EVENT-L- (HDD only — 일관성 위해 sub_category 부여)
UPDATE photo.classification
SET sub_category = CASE
  WHEN is_video THEN 'video'
  WHEN grade_source LIKE 'folder_bulk%' THEN 'wedding_archive'
  ELSE 'other'
END
WHERE grade IN ('EVENT-', 'EVENT-L-');

-- ============================================================================
-- C. TRASH → duplicate / screenshot / short_video / llm / no_face / other
-- ============================================================================
UPDATE photo.classification
SET sub_category = CASE
  WHEN grade_source LIKE 'dedup_demoted%' THEN 'duplicate'
  WHEN grade_source = 'auto_screenshot' THEN 'screenshot'
  WHEN grade_source = 'auto_short_video' THEN 'short_video'
  WHEN grade_source LIKE 'llm_%' AND face_count = 0 THEN 'llm_no_face'
  WHEN grade_source LIKE 'llm_%' THEN 'llm_judged'
  ELSE 'other'
END
WHERE grade = 'TRASH';

-- ============================================================================
-- D. BEST → portrait / landscape
-- ============================================================================
UPDATE photo.classification
SET sub_category = CASE
  WHEN face_count > 0 THEN 'portrait'
  WHEN face_count = 0 AND COALESCE(camera_make,'') != '' THEN 'landscape'
  -- 사람 X + 카메라 X = 출처 불명 (sanity는 별도 강등)
  ELSE 'unknown'
END
WHERE grade = 'BEST';

-- ============================================================================
-- 잔여 backfill (사용자 결정 5/10 → 진행)
-- ============================================================================
-- EVENT+/EVENT- 行 사람0+카메라X+lap<100 = LLM 환각 의심 → NORMAL
UPDATE photo.classification
SET grade='NORMAL',
    grade_source='reclass_event_hallucination',
    updated_at=NOW()
WHERE grade IN ('EVENT+', 'EVENT-')
  AND face_count = 0
  AND COALESCE(camera_make,'') = ''
  AND laplacian_variance > 0
  AND laplacian_variance < 100;

-- BEST 行 인물 매우 흐림 (lap<50) → MEMORY-
UPDATE photo.classification
SET grade='MEMORY-',
    grade_source='reclass_best_blurry_face',
    updated_at=NOW()
WHERE grade = 'BEST'
  AND face_count > 0
  AND laplacian_variance > 0
  AND laplacian_variance < 50;

-- 백필된 NORMAL은 sub_category 'image' (영상 X)
UPDATE photo.classification SET sub_category='image'
WHERE grade='NORMAL' AND sub_category IS NULL AND NOT is_video;
UPDATE photo.classification SET sub_category='video'
WHERE grade='NORMAL' AND sub_category IS NULL AND is_video;
UPDATE photo.classification SET sub_category='image'
WHERE grade='MEMORY-' AND sub_category IS NULL AND NOT is_video;
UPDATE photo.classification SET sub_category='video'
WHERE grade='MEMORY-' AND sub_category IS NULL AND is_video;

-- 나머지 등급 sub_category default (FOOD, NORMAL, MEMORY-)
UPDATE photo.classification
SET sub_category = CASE WHEN is_video THEN 'video' ELSE 'image' END
WHERE sub_category IS NULL AND grade IN ('FOOD','MEMORY-','NORMAL');

\echo '=== 등급 × sub_category 분포 ==='
SELECT grade, sub_category, COUNT(*) FROM photo.classification
GROUP BY 1, 2 ORDER BY 1, 3 DESC;

\echo '=== 백필 영향 ==='
SELECT grade, COUNT(*) FROM photo.classification
WHERE grade_source IN ('reclass_event_hallucination', 'reclass_best_blurry_face')
GROUP BY 1;

\echo '=== sub_category NULL 잔여 ==='
SELECT COUNT(*) FROM photo.classification WHERE sub_category IS NULL;

COMMIT;
