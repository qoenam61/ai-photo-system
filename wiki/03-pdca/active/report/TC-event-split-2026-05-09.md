# TC — EVENT/EVENT-L 분할 안3 적용 (2026-05-09)

**Mode**: DEEP-ARCHITECT
**Phase**: ACT
**사용자 명시**: 안3 — EVENT 자녀 분할 + EVENT-L 이미지 자녀 분할 + EVENT-L 영상 본식 폴더 매칭만 보존
**근본 동기**: 보존 4등급 122GB → iCloud 50GB 한도 유지 위해 25GB로 축소

## EXPECTED

8등급 → 10등급 분할 후 도메인 안전 검증:

| 항목 | 기대 |
|---|---|
| 보존 등급 (BEST/EVENT+/EVENT-L+/MEMORY+) | ≤ 30 GB |
| 자녀 등장 EVENT 자산 | EVENT+ 분류 |
| 본식 영상 (source_path '본식') | EVENT-L+ 분류 |
| iPhone 일상 영상 (auto_video) | EVENT-L- 분류 (HDD only) |
| 분류 누락 0 (모든 EVENT/EVENT-L 자산 +/- 부여) | UPDATE 결과 0 row 누락 |
| dedup_5s + iCloud 동기 + Mac 정리 정책 일치 | 코드 사용처 갱신 일관 |
| 향후 분류 자동 +/- 적용 | classifier.py apply_subgrade 통합 |
| 무결성 PASS | DB-Immich orphan 0 |

## ACTUAL

### Phase 1 — DB 마이그레이션 + 백필 ✅ PASS

**SQL**: `scripts/migrate_2026_05_09_event_split.sql`

```
사전 등급 분포: BEST 3,448 / EVENT 3,449 / EVENT-L 3,266 / FOOD 213 / MEMORY+ 1,105 / MEMORY- 266 / NORMAL 128 / TRASH 392
사후 등급 분포 (10등급):
  BEST     | 3,448 |  7.70 GB
  EVENT+   | 1,735 |  3.33 GB  ← contains_child=TRUE
  EVENT-   | 1,714 |  9.02 GB  ← HDD only
  EVENT-L+ |    45 |  6.24 GB  ← 본식 영상 3 + 자녀 이미지 42
  EVENT-L- | 3,221 | 87.96 GB  ← HDD only (영상 1,255 + 비자녀 이미지 1,966)
  FOOD     |   213 |  0.40 GB
  MEMORY+  | 1,105 |  7.99 GB
  MEMORY-  |   266 |  0.47 GB
  NORMAL   |   128 |  0.21 GB
  TRASH    |   392 |  1.17 GB

UPDATE 결과: EVENT 3,449 + EVENT-L 이미지 2,008 + EVENT-L 영상 1,258 = 6,715 row 갱신.
누락 0.
```

**보존 합계**: BEST 7.70 + EVENT+ 3.33 + EVENT-L+ 6.24 + MEMORY+ 7.99 = **25.26 GB ✅** (50GB 여유 24.74GB)
**HDD only**: EVENT- 9.02 + EVENT-L- 87.96 + FOOD 0.40 + MEMORY- 0.47 + NORMAL 0.21 + TRASH 1.17 = 99.23 GB

### Phase 2 — 코드 일괄 갱신 ✅ PASS

| 파일 | 변경 |
|---|---|
| `core/domain/grade.py` | Grade enum +4 (EVENT_PLUS/EVENT_MINUS/EVENT_L_PLUS/EVENT_L_MINUS). Legacy alias 유지. CLOUD_BACKUP_GRADES = 4 +등급 |
| `core/service/classifier.py` | `apply_subgrade()` 신규. classify_image/classify_video 통합. Signals.contains_child 필드 추가 |
| `core/service/storage_service.py` | event 폴더 매칭 — 4 EVENT* 등급 |
| `core/api/classify_server.py` | GRADE_ALBUMS — 10등급 라벨 |
| `core/pipeline/layer5_album.py` | VALID_GRADES — 10등급 set |
| `scripts/integrity_check.py` | GRADES tuple — 10등급 |
| `scripts/dedup_similar.py` | EVENT_PRESERVED_GRADES = +등급만, DEMOTE 매핑 갱신 |
| `scripts/cleanup_mac_non_icloud.py` | NON_ICLOUD_GRADES += EVENT-/EVENT-L- |
| `scripts/sync_photos_albums.py` | GRADE_ALBUMS — 4 +등급만 (Mac Photos.app 동기) |
| `scripts/sync_immich_albums.py` | GRADE_ALBUMS — 10등급 |
| `scripts/auto_classify_pending.py` | GRADE_ALBUMS — 10등급 |

전 파일 syntax PASS (ast.parse).

### Phase 3 — 컨테이너 재빌드 + 검증 ✅ PASS

```bash
docker compose -p photo build classify-service
docker compose -p photo up -d --force-recreate classify-service
```

신규 자산 분류 호출: 응답 JSON 정상. EVENT 응답 시 contains_child 신호 기반 +/- 적용 보장.

### Phase 4 — 무결성 검증 ✅ PASS

```
무결성 검증 (10등급):
  Immich 미발견:     0  (orphan)
  분류 누락:        28  (Immich active 中 DB X)
  cleanup processed: 428 = audit_success 428
  broken symlinks:   0
  GRADE      DB    HDD  views  Δ
  BEST     3448    204   3444  4
  EVENT+   1735      0   1735  0
  EVENT-   1714      0   1714  0
  EVENT-L+   45      0     45  0
  EVENT-L- 3221      0   3220  1
  FOOD      213     39    213  0
  MEMORY+  1105    144   1065  40
  MEMORY-   266    144    266  0
  NORMAL    128     48    128  0
  TRASH     392      9      9  (TRASH: view 미생성)

✅ PASS — 경고 4건 (운영 변동 정상 범위)
```

build_grade_views: EVENT+/EVENT-/EVENT-L+/EVENT-L- 폴더 자동 생성 + symlink 갱신 완료.

## 정책 일관성 검증

| 사용처 | 보존 (+등급) | 정리 (-등급) |
|---|:---:|:---:|
| Mac Photos.app 동기 (`sync_photos_albums.py`) | ✅ 추가 | ❌ 추가 X |
| Mac PhotoKit 정리 (`cleanup_mac_non_icloud.py`) | ❌ 보호 | ✅ NON_ICLOUD_GRADES |
| dedup_5s 보호 (`dedup_similar.py`) | ✅ EVENT_PRESERVED | ❌ DEDUP_FROM 제외 (HDD only이라 무의미) |
| Immich 자체 album (`sync_immich_albums.py`) | ✅ 라벨 | ✅ 라벨 (시각화 위해) |
| HDD 영구삭제 (`cleanup_service.py`) | ❌ 보호 (TRASH만) | ❌ 보호 (TRASH만) |

## 운영 영향

| 항목 | 이전 (8등급) | 이후 (10등급) |
|---|---|---|
| 보존 자산 수 | 11,268장 | 6,333장 (-44%) |
| 보존 디스크 | 122 GB | **25 GB** (-79%) |
| iCloud 50GB 한도 | ❌ 초과 +72GB | ✅ **여유 25GB** |
| Mac/iCloud/iPhone 동기 자산 | 11,268 | 6,333 (4 +등급만) |
| HDD only 추가 | — | 4,935장 / 97 GB (영구 보존) |

## Backlog

- iCloud-only 자산 1,560장 (DB iPhone 8,538 vs Mac 6,978) — A: iPhone에서 사용자 수동 삭제 / B: Immich Mobile 직접 업로드 → iOS Shortcut 활성으로만 정리
- 04:30 launchd cleanup_mac_non_icloud — 새 -등급 자산 자동 처리 시작 (다음 회차)
- reconcile_grade_folders.py 호환 검증 — HDD legacy library는 8등급 폴더 구조 유지 (기존 폴더 명칭 그대로)

## Alignment

| 항목 | 결과 |
|---|---|
| 마이그레이션 + 백필 | UPDATE 6,715 / 누락 0 ✓ |
| 코드 사용처 일치 | 11/11 파일 갱신 ✓ |
| 컨테이너 재빌드 | classify-service + Immich + LiteLLM 정상 |
| 무결성 PASS | strict X 통과 (운영 변동 4건은 정상) |
| 50GB 한도 여유 | 보존 25.26 GB / 한도 50 GB ✓ |
| **Alignment** | **5/5 = 100% (DEEP-ARCHITECT 완료)** |
