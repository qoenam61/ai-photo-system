-- 2026-05-08 평가단 권고 일괄 마이그레이션
-- P0-A: album_member.dedup_excluded (build/dedup 무한 사이클 차단)
-- P0-B: cleanup_audit.reason → reason_category + reason_detail (카디널리티 정규화)
--
-- 적용:
--   docker exec -i trading_postgres psql -U trading_user -d trading_db \
--     < scripts/migrate_2026_05_08_evaluation.sql

BEGIN;

-- ============================================================================
-- P0-A: album_member에 dedup 영구 제외 마커 추가
-- ============================================================================
ALTER TABLE photo.album_member
  ADD COLUMN IF NOT EXISTS dedup_excluded BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS dedup_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_album_member_active
  ON photo.album_member (album_id) WHERE dedup_excluded = FALSE;

COMMENT ON COLUMN photo.album_member.dedup_excluded IS
  'TRUE면 dedup_album_clip이 클러스터 비최적 멤버로 판단해 제외 — 멱등 (build_albums가 다시 INSERT해도 dedup이 다시 마킹 X). 2026-05-08 무한 사이클 차단.';

-- ============================================================================
-- P0-B: cleanup_audit.reason 정규화
-- ============================================================================
ALTER TABLE photo.cleanup_audit
  ADD COLUMN IF NOT EXISTS reason_category VARCHAR(40),
  ADD COLUMN IF NOT EXISTS reason_detail TEXT;

CREATE INDEX IF NOT EXISTS idx_cleanup_audit_category
  ON photo.cleanup_audit (reason_category);

-- 기존 reason → category 백필 (idempotent)
-- 각 코드 경로의 reason 패턴을 카테고리로 매핑.
UPDATE photo.cleanup_audit
SET reason_category = CASE
    -- HDD layer 5
    WHEN reason = 'layer5_hdd_purge' THEN 'hdd_purge'
    WHEN reason LIKE 'layer5_hdd_purge:imm_marked%' THEN 'hdd_purge'
    WHEN reason LIKE 'layer5_hdd_purge:imm_mark_fail%' THEN 'hdd_purge_imm_unmarked'
    WHEN reason LIKE 'verify_fail:%' THEN 'verify_fail'
    WHEN reason LIKE 'host_path_missing:%' THEN 'host_path_missing'
    WHEN reason LIKE 'unlink_failed:%' THEN 'unlink_failed'
    -- Mac Photos
    WHEN reason LIKE 'mac_photos_delete:%' THEN 'mac_photokit_ok'
    WHEN reason LIKE 'mac_non_icloud:%' THEN 'mac_non_icloud_ok'
    WHEN reason LIKE 'error: Photos에 오류 발생%' THEN 'mac_album_error'
    WHEN reason LIKE 'error: AppleScript%' THEN 'mac_applescript_error'
    WHEN reason LIKE 'error: timeout%' THEN 'mac_timeout'
    WHEN reason ILIKE 'error:%' THEN 'mac_other_error'
    WHEN reason ILIKE '%not_found%' THEN 'mac_photokit_not_found'
    -- 그 외
    WHEN reason IS NULL THEN 'unknown'
    ELSE 'other'
  END,
  reason_detail = reason
WHERE reason_category IS NULL;

COMMENT ON COLUMN photo.cleanup_audit.reason_category IS
  '카디널리티 ≤ 30 카테고리. 알림/통계는 이 컬럼만 사용. 2026-05-08 추가.';
COMMENT ON COLUMN photo.cleanup_audit.reason_detail IS
  '원본 reason 문자열 (raw error 등). 디버깅용. 통계에 사용 X.';

COMMIT;

-- 검증 쿼리 (수동 실행)
-- SELECT reason_category, COUNT(*) FROM photo.cleanup_audit GROUP BY 1 ORDER BY 2 DESC;
-- SELECT COUNT(*) FROM photo.cleanup_audit WHERE reason_category IS NULL;  -- 0이어야 함
-- SELECT COUNT(*) FROM photo.album_member WHERE dedup_excluded;  -- 마이그레이션 직후 0
