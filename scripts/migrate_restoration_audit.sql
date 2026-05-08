-- 복원 감지 KPI view + 보강 인덱스 (DD-restored-asset-protection.md, 2026-05-07)
--
-- detect_restored_assets.py 실행 + KPI 모니터링용. cleanup_audit 테이블 의존이라
-- migrate_db_init.sql 과 분리. 이미 cleanup_audit 존재하는 운영 DB에만 적용.
--
-- 적용:
--   docker exec -i trading_postgres psql -U trading_user -d trading_db \
--       < scripts/migrate_restoration_audit.sql

-- 경로 A (sha256 매칭) 가속 — migrate_db_init.sql에도 동일 인덱스 idempotent
CREATE INDEX IF NOT EXISTS idx_classification_sha256
    ON photo.classification(sha256);

-- 보호 자산 검사 가속
CREATE INDEX IF NOT EXISTS idx_feedback_asset_type
    ON photo.feedback(asset_id, feedback_type);

-- 운영 KPI: HDD에서 영구삭제된 자산 中 같은 sha256으로 재등장한 후보
CREATE OR REPLACE VIEW photo.v_restoration_audit AS
SELECT
  ca.asset_id::text       AS old_asset_id,
  c_new.asset_id::text    AS new_asset_id,
  ca.reported_at          AS deleted_at,
  c_new.classified_at     AS rebackup_at,
  c_old.sha256,
  c_new.grade             AS new_grade,
  EXISTS(
    SELECT 1 FROM photo.feedback f
    WHERE f.asset_id = c_new.asset_id
      AND f.feedback_type IN ('protect', 'restored')
  ) AS protected
FROM photo.cleanup_audit ca
JOIN photo.classification c_old ON c_old.asset_id = ca.asset_id
LEFT JOIN photo.classification c_new
       ON c_new.sha256 = c_old.sha256
      AND c_new.asset_id != c_old.asset_id
      AND c_new.classified_at > ca.reported_at
WHERE ca.success = TRUE AND ca.device = 'hdd';
