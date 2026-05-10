-- 2026-05-10 본식/웨딩 폴더 자산 강제 +등급 보존 (사용자 명시)
-- 5/9 안3 마이그레이션 시 folder_bulk 자산이 contains_child=FALSE → 잘못 강등됨.
-- grade_source LIKE 'folder_bulk%' 매칭으로 강제 +등급 환원
-- (source_path 한국어는 NFD 인코딩으로 SQL ~* 매칭 실패 — grade_source 사용).

BEGIN;

\echo '=== 사전 분포 (folder_bulk 자산) ==='
SELECT grade, grade_source, COUNT(*) FROM photo.classification
WHERE grade_source LIKE 'folder_bulk%'
GROUP BY 1, 2 ORDER BY 1, 2;

-- EVENT- → EVENT+ (웨딩 사진 폴더)
UPDATE photo.classification
SET grade='EVENT+',
    updated_at=NOW()
WHERE grade='EVENT-'
  AND grade_source LIKE 'folder_bulk%';

-- EVENT-L- → EVENT-L+ (본식 사진 폴더)
UPDATE photo.classification
SET grade='EVENT-L+',
    updated_at=NOW()
WHERE grade='EVENT-L-'
  AND grade_source LIKE 'folder_bulk%';

\echo '=== 사후 분포 (folder_bulk 자산) ==='
SELECT grade, grade_source, COUNT(*),
       ROUND(SUM(file_size_bytes)/1024.0/1024/1024, 2) AS gb
FROM photo.classification
WHERE grade_source LIKE 'folder_bulk%'
GROUP BY 1, 2 ORDER BY 1, 2;

\echo '=== 보존 4 +등급 합계 (50GB 한도 검증) ==='
SELECT
  ROUND(SUM(file_size_bytes)/1024.0/1024/1024, 2) AS preserved_gb,
  COUNT(*) AS preserved_n
FROM photo.classification
WHERE grade IN ('BEST','EVENT+','EVENT-L+','MEMORY+');

COMMIT;
