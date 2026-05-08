# TC — 전문가 평가단 개선안 일괄 적용 (2026-05-08)

**Mode**: DEEP-ARCHITECT
**Phase**: ACT
**Alignment 목표**: 99% (도메인 안전 영역)

## EXPECTED

평가단 보고서(시스템 아키텍트 / SRE / 데이터 엔지니어 / ML / SEC) 권고
P0~P1 7건을 단일 세션에서 일괄 구현 + 실검증.

| ID | 권고 | 기대 결과 |
|---|---|---|
| P0-A | maintenance.sh dedup 무한 사이클 차단 | 매 30분 4,735 INSERT/DELETE → 멱등 (0 row write) |
| P0-B | cleanup_audit.reason 정규화 | reason_category 100% 백필, NULL=0 |
| P0-C | Mac Photos 매칭 0 한계 명시 | 매칭률 < 10% 시 명시 경고 |
| P1-G | 무결성 strict 모드 + exit code | 갭 > 0 시 FAIL + exit 1 |
| P1-D | EVENT-L 분류 룰 세분화 | 영상 3-10s → MEMORY+, EVENT-L 33% → 27% |
| P1-E | dedup 5s 환원 패턴 보호 | EVENT/EVENT-L 제외 + group≥3, 신규 후보 0 |
| P1-F | Groq/Qwen 라우팅 가시화 | /health.routing + weekly_kpi.routing_d7 |

## ACTUAL

### P0-A — dedup 무한 사이클 차단 ✅ PASS

**구현**:
- `migrate_2026_05_08_evaluation.sql`: `photo.album_member.dedup_excluded BOOLEAN` 추가
- `dedup_album_clip.py`: DELETE → UPDATE SET dedup_excluded=TRUE
- `sync_immich_albums.py` / `build_albums.py update_album_stats`: WHERE dedup_excluded=FALSE 필터

**검증**:
1. build_albums 첫 실행 → 폴더 2,393 + 연도 2,342 = **4,735 자산 추가**
2. dedup 첫 실행 → **총 신규 제외: 4,735장** (마킹)
3. build_albums 재실행 → **0 추가** (멱등)
4. dedup 재실행 → **총 신규 제외: 0장** (멱등)
5. album_member 최종: dedup_excluded=FALSE 2,170, TRUE 4,735

**효과**: 일일 write amplification 454,560 row → 0 row.

### P0-B — cleanup_audit.reason 정규화 ✅ PASS

**구현**:
- 마이그레이션: `reason_category VARCHAR(40)` + `reason_detail TEXT` + index
- 1,658 row 백필 (mac_album_error 712 / hdd_purge 428 / mac_todelete_album 356 / mac_non_icloud_ok 161 / mac_photokit_ok 1)
- INSERT 사이트 5곳 수정:
  - `core/api/classify_server.py` cleanup_result + `_infer_audit_category` helper
  - `core/service/cleanup_service.py` mark_processed (HDD)
  - `scripts/cleanup_run.py` mark_audit + `_hdd_reason_category`
  - `scripts/cleanup_photos_mac.py` record_audit
  - `scripts/cleanup_mac_non_icloud.py` record_audit

**검증**:
- `SELECT COUNT(*) FROM cleanup_audit WHERE reason_category IS NULL` → **0**
- 카테고리 분포 카디널리티 5 (이전 30+ raw error). 알림/통계용 인덱스 idx_cleanup_audit_category 추가.

### P0-C — Mac Photos 매칭 한계 명시 ✅ PARTIAL

**구현**:
- `cleanup_photos_mac.py` 매칭률 < 10% 시 명시 경고 출력 (운영자 사일런트 미작동 인지)
- 근본 한계: osxphotos PhotosDB는 iCloud-only 자산 인덱싱 X → PhotoCleanup.app에 PHAsset 직접 검색 명령 추가는 backlog (Swift 작업)

**검증**:
- 매칭률 0~1/606 = 0.2% — 현재 launchd 03:30이 매일 호출하지만 노이즈만 발생. 경고 출력으로 명시화.

**사용자 결정 필요**:
- A. Mac 정리 보류 (iOS Shortcut에만 집중) — iCloud Recently Deleted 30일 안전망
- B. PhotoCleanup.app Swift 강화 (PHAsset.fetchAssets with predicate)

### P1-G — 무결성 strict 모드 ✅ PASS

**구현**:
- `integrity_check.py` `--strict` (갭 > 0 즉시 FAIL) + `--exit-code` (CI/배포 검증)
- cleanup_audit reason_category 기반 실패율 분석 추가 (48h, 임계 20%)
- TRASH는 view 미생성 정책 명시 (이전 거짓 PASS 원인)

**검증**:
- 기본 모드 exit=1 (DB↔Immich 400장 갭)
- strict 모드 exit=1 (+ view symlink 갭 명시)
- 백필 후 view 갭 1건 (운영 변동 정상 범위)

### P1-D — EVENT-L 분류 룰 세분화 ✅ PASS

**구현**:
- `classifier.py`: `VIDEO_SHORT_THRESHOLD=3.0` / `VIDEO_LONG_THRESHOLD=10.0`
- 새 룰: `<3s → TRASH` / `3-10s → MEMORY+ (auto_short_clip)` / `≥10s → EVENT-L`
- `backfill_video_grade_v3.py`: 기존 auto_video 자산 재분류

**검증**:
- 백필 결과: TRASH +9 / MEMORY+ +739 / EVENT-L 1,254 유지 (≥10s 만)
- EVENT-L 비율: 4,013 (33%) → **3,265 (27%)** — iCloud 50GB 부담 감소
- MEMORY+ 비율: 365 → 1,104 (HDD only, iCloud 미동기)

### P1-E — dedup 5s 환원 패턴 보호 ✅ PASS

**구현**:
- `dedup_similar.py` `DEDUP_FROM` 에서 EVENT/EVENT-L 제외 (사용자 환원 1,599장의 93%)
- group_size ≥ 2 → ≥ **3** 변경 (단순 2장 쌍 보호)

**검증**:
- 새 정책 dry-run: **신규 dedup 후보 0 자산**. 기존 환원 자산 영향 없음, 미래 dedup만 보수적.

### P1-F — Groq/Qwen 라우팅 가시화 ✅ PASS

**구현**:
- `classify_server.py` `/health.routing.{24h,7d}` (groq/qwen/ensemble/corrected/auto_fallback)
- `kpi_summarizer.py` `WeeklyStats.routing_d7` + `cleanup_failures_d7` 추가

**검증** (2026-05-08 21:50 KST):
```json
"routing_d7": {
  "groq": 174,        // 3.0%
  "qwen": 5560,       // 94.5%
  "ensemble": 165,    // 2.8%
  "corrected": 56,
  "auto_fallback": 2510
}
"cleanup_failures_d7": {"mac_album_error": 712}
```
- 의도("Groq 1차") vs 실제(Qwen 94.5%) 갭 표면화 — Groq 무료 한도 정합 검토 필요 (별도 backlog)

## 운영 영향

| 지표 | 이전 | 이후 |
|---|---|---|
| 일일 album_member write | 454,560 row | 0 row |
| EVENT-L 비율 | 33% (4,013) | 27% (3,265) |
| cleanup_audit reason 카디널리티 | 30+ (raw error) | 5 (정규화) |
| 무결성 PASS 거짓 | DB-Immich 21장 갭 PASS | DB-Immich 400 FAIL ✓ |
| LLM 모델 분포 가시화 | 0 | /health + weekly_kpi |
| dedup 5s 환원율 (예측) | 13% | 0% (EVENT 보호) |

## 미커밋 산출물 (커밋 대기)

```
scripts/migrate_2026_05_08_evaluation.sql  (신규)
scripts/dedup_album_clip.py                (수정)
scripts/sync_immich_albums.py              (수정)
scripts/build_albums.py                    (수정)
scripts/cleanup_run.py                     (수정)
scripts/cleanup_photos_mac.py              (수정)
scripts/cleanup_mac_non_icloud.py          (수정)
scripts/integrity_check.py                 (수정)
scripts/dedup_similar.py                   (수정)
scripts/backfill_video_grade_v3.py         (신규)
core/api/classify_server.py                (수정)
core/service/cleanup_service.py            (수정)
core/service/kpi_summarizer.py             (수정)
core/service/classifier.py                 (수정)
wiki/03-pdca/active/report/TC-evaluation-improvement-2026-05-08.md  (신규)
```

## Backlog (다음 세션)

- DB-Immich 400장 갭 정합 (`backfill_immich_deleted_at.py` 보강)
- PhotoCleanup.app PHAsset 직접 검색 명령 추가 (Swift, P0-C 근본해결)
- Groq Llama-4 Scout 무료 한도 모니터링/알림
- mac_album_error 712 fail 자산 재시도 정책 (또는 별도 정리 경로)

## Alignment

| 항목 | 결과 |
|---|---|
| F-XXX 코드 매핑 | 7/7 (P0-A/B/C, P1-D/E/F/G) |
| 정식 TC 작성 | 본 파일 |
| 실검증 | 7/7 PASS (P0-C는 PARTIAL — 사용자 결정 영역 보고) |
| 코드 스타일 (ruff) | 미실행 (다음 세션) |
| **Alignment** | **6.5/7 = 92.8%** (FAST 모드 통과, SAFE 보강 필요) |
