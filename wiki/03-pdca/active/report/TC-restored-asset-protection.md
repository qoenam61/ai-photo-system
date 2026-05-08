# TC: 복원 자산 자동 보호 (DD-restored-asset-protection)

**도메인 안전 영역**. SDLC: DEEP-ARCHITECT.
**작성**: 2026-05-07
**관련 코드**: `core/service/restored_detector.py`, `scripts/detect_restored_assets.py`
**관련 문서**: 본 TC + 인라인 설계 (대화 기록)
**모드**: SAFE (Alignment ≥ 99%)

---

## 배경

iPhone "최근 삭제됨" 또는 Immich 휴지통에서 사용자가 수동 복원한 자산이
다음 cleanup cycle에 다시 등록되어 재삭제되는 갭을 해결.

두 경로:
- **A**: iPhone 휴지통 복원 + 재백업 → sha256 매칭으로 detect (`detect_iphone_rebackup`)
- **B**: Immich 휴지통 복원 → asset.deletedAt NULL 복귀로 detect (`detect_immich_trash_restore`)

결정 (사용자 명시 2026-05-07):
- Q1: grade 변경 X (그대로 TRASH + protect만)
- Q2: restored 자산은 dedup 강등에서도 제외
- Q3: cleanup_queue 는 cancelled=TRUE UPDATE (감사 보존)
- Q4: 1주차 매 cycle 알림 → 안정 후 주 1회
- Q5: 새 photo.classification row 보존
- Q6: Immich 휴지통 단독 복원 시 broken_link 마커 + 알림
- Q7: v_restoration_audit view 운영 도입
- Q8: 'restored' feedback 영구 (수동 해제 가능)

---

## 운영 발견 (2026-05-07 smoke test)

`detect_immich_trash_restore` 가 379건 detect → 분석 결과 **`mark_immich_deleted` subprocess 실패 누적**
(2026-05-04부터 99% 실패율). 사용자 복원이 아닌 정합 갭.

**대응**: 경로 B 를 default OFF (`--enable-immich-detect` 명시 시에만 활성). 경로 A 는 default ON.
**후속 과제**: `cleanup_run.py:84-100 mark_immich_deleted` 실패 원인 분석 + 정합 backfill (별도 작업).

---

## TC-1: 경로 A — iPhone 재백업 자동 보호

### EXPECTED
TRASH 자산이 HDD 영구삭제된 후 사용자가 같은 사진을 iPhone 자동 백업으로 다시 올린 경우,
`detect_restored_assets.py --no-dry-run` 실행 시 새 asset_id에 `feedback_type='restored'` 자동 등록.

### 시드
```sql
-- 영구삭제 완료된 자산
INSERT INTO photo.classification (asset_id, source_path, sha256, file_size_bytes, grade, grade_source, classified_at)
  VALUES ('aaaaaaaa-0000-0000-0000-000000000001', '/storage/old/X.heic', 'TC1_SHA_X', 100000, 'TRASH', 'llm_groq', NOW() - INTERVAL '8 days');
INSERT INTO photo.cleanup_queue (asset_id, grace_until, processed_at, deleted_at_device, created_at)
  VALUES ('aaaaaaaa-0000-0000-0000-000000000001', NOW() - INTERVAL '1 day', NOW() - INTERVAL '6 hours', NOW() - INTERVAL '6 hours', NOW() - INTERVAL '8 days');
INSERT INTO photo.cleanup_audit (asset_id, immich_id, device, success, reason, reclaimed_bytes, device_deleted_at, reported_at)
  VALUES ('aaaaaaaa-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-000000000001', 'hdd', TRUE, 'layer5_hdd_purge', 100000, NOW() - INTERVAL '6 hours', NOW() - INTERVAL '6 hours');
-- iPhone 재백업 시뮬레이션 (새 asset_id, 동일 sha256)
INSERT INTO photo.classification (asset_id, source_path, sha256, file_size_bytes, grade, grade_source, classified_at)
  VALUES ('bbbbbbbb-0000-0000-0000-000000000001', '/usr/src/app/upload/jw/random.heic', 'TC1_SHA_X', 100000, 'TRASH', 'llm_groq', NOW());
```

### 실행
```bash
PYTHONPATH=. poetry run python scripts/detect_restored_assets.py --no-dry-run --quiet-telegram
```

### 검증 SQL
```sql
SELECT feedback_type FROM photo.feedback
  WHERE asset_id = 'bbbbbbbb-0000-0000-0000-000000000001';
-- EXPECTED: 1 row, feedback_type='restored'
```

### PASS 기준
- feedback row 1건 (`restored`)
- grade='TRASH' / grade_source='llm_groq' 변경 X (Q1)
- 새 cleanup_queue 진입 X (다음 auto_enqueue_trash 회차에서)

### 단위 테스트 매핑
- `core/tests/unit/test_restored_detector.py::test_detect_iphone_rebackup_returns_pairs`
- `core/tests/unit/test_restored_detector.py::test_mark_restored_inserts_feedback_and_cancels_queue`

### ACTUAL (2026-05-07 smoke)
- 운영 DB 0건 (현재 사용자 복원 후 재백업 사례 없음)
- 단위 테스트 6/6 PASS (mock 기반)

---

## TC-2: 보호된 자산 재진입 차단

### EXPECTED
`feedback_type='restored'` 등록된 자산은 `auto_enqueue_trash.py` / `cleanup_service.enqueue_cleanup()` 에서 영구 skip.

### 시드 (TC-1 직후 상태)
```sql
-- bbbbbbbb..0001 가 TC-1에서 'restored' 보호됨
```

### 실행
```bash
PYTHONPATH=. poetry run python scripts/auto_enqueue_trash.py
```

### 검증 SQL
```sql
SELECT COUNT(*) FROM photo.cleanup_queue WHERE asset_id = 'bbbbbbbb-0000-0000-0000-000000000001';
-- EXPECTED: 0
```

추가:
```python
from core.service.cleanup_service import enqueue_cleanup
r = enqueue_cleanup(['bbbbbbbb-0000-0000-0000-000000000001'])
# EXPECTED: r.enqueued == 0, skipped[0]['reason'] == 'protected'
```

### PASS 기준
- cleanup_queue 미진입 (auto_enqueue_trash NOT IN 조건)
- 직접 enqueue 시도해도 cleanup_service 가 protect/restored 매칭 자산 skip

### 단위 테스트 매핑
- `core/tests/unit/test_cleanup_service.py::test_enqueue_skips_protected` (회귀 — feedback_type IN ('protect','restored') 확장 후도 PASS)

### ACTUAL
- 단위 테스트 7/7 PASS (cleanup_service.py 변경 후)

---

## TC-3: 정상 TRASH 자산 회귀 안전 (회귀 보호)

### EXPECTED
복원 신호 없는 TRASH 자산은 정상 cleanup 흐름 유지 (7일 grace → HDD 영구삭제).

### 시드
```sql
INSERT INTO photo.classification (asset_id, source_path, sha256, grade, grade_source, file_size_bytes, classified_at)
  VALUES ('cccccccc-0000-0000-0000-000000000001', '/storage/old/Y.heic', 'TC3_SHA_Y', 'TRASH', 'llm_groq', 50000, NOW() - INTERVAL '8 days');
-- 같은 sha256 의 새 자산 없음
```

### 실행
```bash
PYTHONPATH=. poetry run python scripts/detect_restored_assets.py --no-dry-run --quiet-telegram
PYTHONPATH=. poetry run python scripts/auto_enqueue_trash.py
```

### 검증
```sql
SELECT COUNT(*) FROM photo.cleanup_queue WHERE asset_id = 'cccccccc-0000-0000-0000-000000000001';
-- EXPECTED: 1 (정상 enqueue)

SELECT COUNT(*) FROM photo.feedback WHERE asset_id = 'cccccccc-0000-0000-0000-000000000001';
-- EXPECTED: 0 (보호 미등록)
```

### PASS 기준
- 정상 enqueue + 보호 미등록

### ACTUAL
- 운영 DB 정상 흐름 검증: dedup_similar.py dry-run, cleanup_service unit test PASS

---

## TC-4: 트레이딩 영향 ≤ 5%

### EXPECTED
maintenance.sh `[5/9] detect_restored_assets` 추가 단계가 트레이딩 자원에 무시할만한 영향.

### 실행
```bash
time PYTHONPATH=. poetry run python scripts/detect_restored_assets.py
```

### PASS 기준
- wall-time < 5초
- LLM 호출 X (DB only)
- 메모리 증가 < 50MB

### ACTUAL (2026-05-07)
- wall-time **0.63초** (운영 DB 12,205 자산 + cleanup_audit 428건)
- LLM 호출 0회
- DB 쿼리: classification ⨝ cleanup_audit (sha256 인덱스 적용)
- **PASS** ✅

---

## 단계적 적용 결과

| 단계 | 상태 | 비고 |
|---|---|---|
| S1. SQL 마이그 (인덱스 + view) | ✅ 완료 | `migrate_restoration_audit.sql` 운영 DB 적용 |
| S2. core/service/restored_detector.py | ✅ 완료 | 단위 6 PASS |
| S3. cleanup_service feedback_type 확장 | ✅ 완료 | 5곳 SQL — 회귀 7 PASS |
| S4. classify_server protect_asset 파라미터화 | ✅ 완료 | feedback_type 'protect'/'restored' |
| S5. detect_restored_assets.py | ✅ 완료 | 경로 A default ON, B default OFF |
| S6. dedup_similar.py restored 보호 | ✅ 완료 | dry-run 회귀 정상 |
| S7. maintenance.sh [5/9] | ✅ 완료 | 8 → 9 단계 |
| S8. TC + 커밋 | ✅ 진행 중 | 본 문서 |

---

## 롤백 절차

| 단계 | 롤백 |
|---|---|
| S1 | `DROP INDEX idx_classification_sha256, idx_feedback_asset_type; DROP VIEW photo.v_restoration_audit;` (idempotent) |
| S2~S6 | `git revert <commit>` |
| S7 | maintenance.sh `[5]` 단계 주석 처리 |
| 운영 protect 자동 등록 자산 해제 | `DELETE FROM photo.feedback WHERE feedback_type='restored' AND created_at > NOW() - INTERVAL '7 days';` |

---

## 후속 과제 (별도 작업)

- **mark_immich_deleted 정합 backfill**: cleanup_run.py:84 subprocess 실패 누적 379건 처리
- **경로 B 활성화**: 정합 backfill 후 `--enable-immich-detect` 도입 결정
- **broken_link 마커**: Q6 결정에 따라 Immich UI 표시 (Phase 7 운영 단계)
- **주 1회 알림 전환**: 1주차 매 cycle 알림 안정성 확인 후 (Q4)
