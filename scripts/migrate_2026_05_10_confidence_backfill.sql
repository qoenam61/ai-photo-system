-- 2026-05-10 confidence NULL 8,548장 백필 (P0 — classify_and_persist 누락 fix 후속)
-- grade_source별 default confidence 부여 (분류 품질 측정 + sanity 분기 정확도 ↑).

BEGIN;

\echo '=== 사전 NULL 카운트 ==='
SELECT COUNT(*) FROM photo.classification WHERE confidence IS NULL;

-- LLM 분류 (Groq 응답 신뢰도 평균 8)
UPDATE photo.classification SET confidence = COALESCE(groq_conf, 8)
WHERE confidence IS NULL AND grade_source = 'llm_groq';

UPDATE photo.classification SET confidence = COALESCE(qwen_conf, 8)
WHERE confidence IS NULL AND grade_source = 'llm_qwen';

UPDATE photo.classification SET confidence = COALESCE(GREATEST(qwen_conf, groq_conf), 8)
WHERE confidence IS NULL AND grade_source = 'llm_ensemble';

UPDATE photo.classification SET confidence = COALESCE(qwen_conf, groq_conf, 7)
WHERE confidence IS NULL AND grade_source LIKE 'llm_corrected%';

-- Auto 신호 (객관 신호 — 신뢰도 높음)
UPDATE photo.classification SET confidence = 10
WHERE confidence IS NULL AND grade_source IN ('auto_short_video', 'auto_screenshot');

UPDATE photo.classification SET confidence = 8
WHERE confidence IS NULL AND grade_source IN ('auto_video', 'auto_short_clip',
                                                'auto_quality_ok', 'auto_blurry',
                                                'auto_no_face');

-- Reclass (사후 보정 — 신호 기반)
UPDATE photo.classification SET confidence = 7
WHERE confidence IS NULL AND grade_source LIKE 'reclass%';

-- Dedup (베스트컷 외 — 강등이라 낮음)
UPDATE photo.classification SET confidence = 6
WHERE confidence IS NULL AND grade_source LIKE 'dedup_demoted%';

-- 사용자 환원 (명시 의지 — 매우 높음)
UPDATE photo.classification SET confidence = 9
WHERE confidence IS NULL AND grade_source = 'restored_from_dedup';

-- Folder bulk (사용자 명시 폴더 분류 — 가장 높음)
UPDATE photo.classification SET confidence = 10
WHERE confidence IS NULL AND grade_source LIKE 'folder_bulk%';

-- 잔여 NULL (예상 외 grade_source) — 보수적 default
UPDATE photo.classification SET confidence = 5
WHERE confidence IS NULL;

\echo '=== 사후 NULL 카운트 (0이어야 함) ==='
SELECT COUNT(*) FROM photo.classification WHERE confidence IS NULL;

\echo '=== confidence 분포 ==='
SELECT confidence, COUNT(*) FROM photo.classification
GROUP BY 1 ORDER BY 1;

COMMIT;
