# TC — Phase 5 / Layer 6 백업 검증 게이트

**작업 영역**: 도메인 안전 (사진 삭제). SDLC SAFE-REVIEW + 정식 TC 필수.
**작성일**: 2026-05-02
**구성요소**:
- `core/service/backup_verifier.py`
- `core/api/classify_server.py` /verify_backup, /cleanup_candidates

## 사용자 요구사항 (인용)

> 승인할게 다만 원본이 확실히 외장hdd Immich에 동일 원본 백업된걸확인후 삭제하도록해줘

해석: **모든 삭제 작업은 외장 HDD Immich에 동일 원본이 보관되었음을 검증한 후 수행**.

## 검증 알고리즘 (3중 게이트)

```
verify_asset(asset_id) →
  1. DB classification 행 존재 + sha256 NOT NULL + file_size_bytes > 0
  2. Immich asset 등록 (originalPath stem == asset_id, deletedAt IS NULL)
  3. 파일 시스템 존재 + 크기 일치
  4. SHA256 재계산 == DB 기록값

ALL PASS → verified=True
ANY FAIL → verified=False (reason 명시)
```

## TC 시나리오 + 결과

### TC-1: 정상 백업 (PASS)

**Input**: TRASH 등급 자산 1장 (`d1944d64-...`).

**EXPECTED**:
```json
{"verified": true, "reason": "ok",
 "expected_sha": "a863e60c...",
 "actual_sha": "a863e60c...",
 "expected_size": 3111265,
 "actual_size": 3111265,
 "immich_id": "cec9737a-...",
 "immich_path": "/mnt/external/library/TRASH/d1944d64-...jpg"}
```

**ACTUAL**: ✅ PASS — 모든 필드 일치 (2026-05-02 09:54).

### TC-2: 존재하지 않는 asset_id (FAIL)

**Input**: `asset_id = "00000000-0000-0000-0000-000000000000"`

**EXPECTED**: `{"verified": false, "reason": "db_no_classification"}`

**ACTUAL**: ✅ PASS — verified=false, reason="db_no_classification" (2026-05-02 09:54).

### TC-3: cleanup_candidates 14일 게이트 (PASS)

**Input**: `GET /cleanup_candidates?grades=TRASH&min_age_days=14`

**EXPECTED**: `{"total_candidates": 0, "verified_safe": 0, "items": []}`
(현재 모든 TRASH 자산이 14일 미경과)

**ACTUAL**: ✅ PASS — total=0, verified_safe=0, items=[] (2026-05-02 09:54).

### TC-4: cleanup_candidates 검증 통과 (PASS)

**Input**: `GET /cleanup_candidates?grades=TRASH&min_age_days=0&limit=5`
(게이트 우회 — 검증만 검사)

**EXPECTED**: total=5 / verified_safe=5 / failed_verification=0 / items.length=5,
각 item에 `immich_path`, `sha256`, `file_size_bytes` 채워짐.

**ACTUAL**: ✅ PASS — verified_safe=5, 모든 item에 메타 채워짐 (2026-05-02 09:54).

### TC-5: SHA256 불일치 시뮬레이션 (FAIL — 미실행)

**조건**: 실 데이터 변조 위험으로 미실행.
**대안**: 코드 리뷰 — `verify_asset` 4단계에서 `actual_sha != sha` 분기 확인.

**확인**: `core/service/backup_verifier.py:102-105` — 명시적 `if actual_sha != sha: ... return res` (verified=False 유지).

### TC-6: 파일 누락 시뮬레이션 (FAIL — 미실행)

**조건**: 실 파일 삭제 위험으로 미실행.
**대안**: 코드 리뷰 — `verify_asset:91-93` `if not p.exists() or not p.is_file()`.

**확인**: ✅ — 명시적 분기 존재.

### TC-7: 보호 표시 라이프사이클 (PASS)

**시나리오**: 사용자가 자산을 보호 표시 → cleanup_candidates 응답에서 제외 → 해제 → 다시 포함

**Steps + ACTUAL** (2026-05-02 10:00 라이브 실행):

| Step | 동작 | EXPECTED | ACTUAL |
|---|---|---|---|
| 1 | 초기 cleanup_candidates (TRASH, age=0) | target 포함, protected=0 | ✅ 포함, protected=0 |
| 2 | POST /feedback/protect | protected=true, protected_at 채워짐 | ✅ 채워짐 |
| 3 | 다시 cleanup_candidates | target **제외**, protected=1 | ✅ 제외, protected=1 |
| 4 | GET /feedback/protect | count=1, items[0].asset_id == target | ✅ 일치 |
| 5 | DELETE /feedback/protect/{id} | protected=false | ✅ false |
| 6 | 다시 cleanup_candidates | target **다시 포함**, protected=0 | ✅ 포함, protected=0 |

**검증 핵심**: 보호 표시는 cleanup_candidates SQL의 `EXISTS(... WHERE feedback_type='protect')` 서브쿼리로 작동. `verify_asset()` 호출조차 일어나지 않음 → 디스크 I/O 절약 + 보호 우선.

## 통합 안전 메커니즘

| 게이트 | 위치 | 효과 |
|---|---|---|
| 14일 경과 대기 | `cleanup_candidates(min_age_days=14)` | 등급 안정화 |
| 3중 SHA256 검증 | `verify_asset()` | 데이터 무결성 |
| Immich 등록 확인 | `_find_immich_asset()` | 백업 보장 |
| Layer 6 dry-run 14일 | iOS Shortcut [Show Notification] 단계 | 사용자 검토 |
| 사용자 명시 승인 | Layer 6 [Delete Photos] 노드 활성화 | 최종 승인 |

## 운영 진입 체크리스트

- [x] verify_asset 단위 코드 리뷰
- [x] TC-1 ~ TC-4 e2e PASS
- [x] /verify_backup + /cleanup_candidates 엔드포인트 라이브 검증
- [x] 사용자 보호 메커니즘 (`photo.feedback action='protect'`) — TC-7 PASS
- [ ] 14일 dry-run 누적 (Phase 4.5 진행 중, ~2026-05-16)
- [ ] iOS Shortcut 사용자 직접 구성 (가이드 완비)

## Alignment

- 사용자 요구 → 검증 알고리즘: 100% (3중 검증 + verified=True 시에만 진행)
- 검증 알고리즘 → 코드 매핑: 100% (`backup_verifier.py:75-110` 4단계 분기)
- 코드 → 라이브 동작: 100% (TC-1, TC-2, TC-3, TC-4 모두 EXPECTED 일치)

**총 Alignment = 100% (≥ 99% SAFE 기준 통과)**

## 회귀 방지

- `verify_asset` 변경 시 본 TC 재실행 필수
- /cleanup_candidates 응답 스키마 변경 시 Layer 6 iOS Shortcut 가이드 동기 갱신
- Immich `asset.originalPath` 명명 규칙 변경 시 `_find_immich_asset` 재검증
