-- 사진 시스템 DB schema 초기화
-- trading_postgres 안에 photo schema 분리 (의사결정 #2, v3.5)

CREATE SCHEMA IF NOT EXISTS photo;

-- ─────────────────────────────────────────────
-- photo.classification — 분류 결과 (메인 테이블)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS photo.classification (
    id BIGSERIAL PRIMARY KEY,
    asset_id UUID NOT NULL UNIQUE,

    -- 경로
    source_path TEXT NOT NULL,           -- 원본 (백업 폴더 등)
    storage_path TEXT,                   -- Immich-Storage 최종 (이동 후)

    -- 식별
    sha256 CHAR(64) NOT NULL,
    file_size_bytes BIGINT,
    is_video BOOLEAN DEFAULT FALSE,

    -- 분류 결과
    grade VARCHAR(20) NOT NULL,          -- 최종 등급 (8개 中 1)
    confidence INT,                      -- 1~10
    grade_source VARCHAR(20),            -- 'llm_qwen' | 'llm_groq' | 'llm_ensemble' | 'auto'

    -- 앙상블 상세 (의사결정 #37, v3.10)
    qwen_grade VARCHAR(20),
    qwen_conf INT,
    qwen_ms INT,
    groq_grade VARCHAR(20),
    groq_conf INT,
    groq_ms INT,

    -- 자동 분류 신호 (의사결정 #40b, v3.10)
    face_count INT,
    laplacian_variance NUMERIC(8,2),
    quality_score NUMERIC(6,4),          -- face_quality × √laplacian × scene
    is_screenshot BOOLEAN DEFAULT FALSE,
    similarity_group_id BIGINT,
    clip_cosine_max NUMERIC(4,3),

    -- 미디어 메타
    width INT,
    height INT,
    duration_seconds NUMERIC(8,2),
    exif_datetime TIMESTAMPTZ,
    gps_lat NUMERIC(10,7),
    gps_lon NUMERIC(10,7),
    camera_make VARCHAR(50),
    camera_model VARCHAR(100),

    -- 사용자 액션 (♥, 등급 수동 변경)
    favorite BOOLEAN DEFAULT FALSE,
    user_modified_grade VARCHAR(20),

    -- 폰 보관 (v3.9 동적 quota)
    device_kept BOOLEAN DEFAULT FALSE,
    cloud_synced_at TIMESTAMPTZ,

    -- 정리 (v3.7)
    cleanup_grace_until TIMESTAMPTZ,
    deleted_from_device_at TIMESTAMPTZ,
    trash_until DATE,

    -- 모델 버전 (v3.5 의사결정)
    model_version VARCHAR(80),

    -- 타임스탬프
    classified_at TIMESTAMPTZ DEFAULT NOW(),
    moved_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_classification_grade ON photo.classification(grade);
CREATE INDEX IF NOT EXISTS idx_classification_exif ON photo.classification(exif_datetime);
CREATE INDEX IF NOT EXISTS idx_classification_storage ON photo.classification(storage_path);
CREATE INDEX IF NOT EXISTS idx_classification_sim_group ON photo.classification(similarity_group_id);
CREATE INDEX IF NOT EXISTS idx_classification_cleanup ON photo.classification(cleanup_grace_until)
    WHERE deleted_from_device_at IS NULL;
-- 복원 감지 (detect_restored_assets) sha256 매칭 가속
CREATE INDEX IF NOT EXISTS idx_classification_sha256 ON photo.classification(sha256);

-- ─────────────────────────────────────────────
-- photo.conversion_log — Layer 0.5 변환 기록
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS photo.conversion_log (
    id BIGSERIAL PRIMARY KEY,
    original_path TEXT NOT NULL,
    converted_path TEXT,
    original_sha256 CHAR(64) NOT NULL,
    converted_sha256 CHAR(64),
    original_codec VARCHAR(20),          -- HEIC/HEVC/JPEG/MP4
    converted_codec VARCHAR(20),
    metadata_match BOOLEAN,
    decoded_ok BOOLEAN,
    converted_at TIMESTAMPTZ DEFAULT NOW(),
    quarantine_until DATE,               -- 변환일 + 7일
    purged_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_conversion_quarantine ON photo.conversion_log(quarantine_until)
    WHERE purged_at IS NULL;

-- ─────────────────────────────────────────────
-- photo.feedback — 사용자 피드백 (Layer 7)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS photo.feedback (
    id BIGSERIAL PRIMARY KEY,
    asset_id UUID NOT NULL,
    feedback_type VARCHAR(30) NOT NULL,  -- 'protect' | 'restored' (auto_detected) | 'favorite_added' | 'grade_changed_manual'
    old_grade VARCHAR(20),
    new_grade VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
-- protect/restored 매칭 가속 (cleanup_service 보호 검사)
CREATE INDEX IF NOT EXISTS idx_feedback_asset_type ON photo.feedback(asset_id, feedback_type);

-- 복원 감지 KPI view: scripts/migrate_restoration_audit.sql 별도 적용
-- (cleanup_audit 테이블 의존이라 init과 분리)

-- ─────────────────────────────────────────────
-- photo.cleanup_queue — 기기 삭제 대상 (Layer 5/6)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS photo.cleanup_queue (
    id BIGSERIAL PRIMARY KEY,
    asset_id UUID NOT NULL UNIQUE,
    grace_until TIMESTAMPTZ NOT NULL,
    cancelled BOOLEAN DEFAULT FALSE,
    processed_at TIMESTAMPTZ,
    deleted_at_device TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- photo.cloud_sync_queue — 클라우드 동기화 검증 (Layer 7)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS photo.cloud_sync_queue (
    id BIGSERIAL PRIMARY KEY,
    asset_id UUID NOT NULL,
    cloud_provider VARCHAR(20) NOT NULL, -- 'icloud' | 'galaxy_cloud'
    verified BOOLEAN DEFAULT FALSE,
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 권한 (trading_user 그대로 사용, 향후 photo_user 분리 가능)

COMMIT;
