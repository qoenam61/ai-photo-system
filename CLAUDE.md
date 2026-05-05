# Claude Code 프로젝트 컨텍스트
### M4 맥미니 사진 자동화 시스템 (ai-photo-system)

이 파일은 Claude Code가 이 프로젝트에서 작업할 때 참조하는 도메인 컨텍스트와 규칙입니다.
글로벌 규칙(`~/.claude/CLAUDE.md`, RTK, SDLC)은 그대로 적용되고, 이 파일은 프로젝트 특화 사항만 정의합니다.

---

## 프로젝트 개요

- **목적**: jw.son(iPhone) · eunju(Galaxy) 가족 2명의 사진 자동 분류·정리 시스템
- **호스트**: M4 Mac mini 16GB (트레이딩 시스템과 공존)
- **저장**: 외장 HDD 1TB (Phase 6 이후) + iCloud 50GB (jw.son) + Galaxy Cloud 15GB (eunju)
- **분류**: 8등급 (EVENT / EVENT-L / BEST / FOOD / MEMORY+ / MEMORY- / NORMAL / TRASH)
- **LLM**: 로컬 Qwen2.5-VL 7B Q4_K_M (Ollama) — 유료 Vision API 미사용 ($0/월)
- **핵심 원칙 (v3.13, 2026-05-03 사용자 명시 변경)**: 원본은 절대 버리지 않음.
  - Vision 분류는 **`VISION_MODEL_CHAIN` env 기반 동적 라우팅**.
  - 기본 체인: `groq,qwen` — Groq Llama-4 Scout 1차, 무료 한도 소진/실패 시 자동 Qwen fallback.
  - 사용자가 언제든 `VISION_MODEL_CHAIN=qwen` 으로 로컬 전용 복귀 가능.
  - Groq 텍스트 작업(앨범명·KPI·NL)은 그대로 유지.
  - PII (이름·주소) 외부 전송은 여전히 금지.

## 진입 문서 (이 순서대로 읽기)

1. `photo_system_design_v3.md` (v3.7 FINAL) — 메인 설계 문서, 8-Phase 로드맵
2. `local_llm_evaluation.md` (v1.3 FINAL) — LLM 모델 평가
3. `architecture_review.md` (v1.4 FINAL) — 아키텍처 평가 + 의사결정 24건

## 도메인 안전 키워드 (자동 모델 승격)

다음 키워드 등장 시 FAST → DEEP-ARCHITECT 자동 승격:
- "사진 삭제", "기기 정리", "Layer 6", "cleanup_queue"
- "변환", "HEIC", "HEVC", "Layer 0.5", "quarantine"
- "마이그레이션", "Phase 6", "originalPath 치환"
- "분류 등급", "EVENT 자동판정", "♥", "favorite"
- "등급 폴더 이동", "storage_service", "뷰 심볼릭", "TRASH cleanup"
- "동기화 03:00", "Layer 5"
- **"사용자별", "jw.son만", "eunju만", "분기"** → 단일 파이프라인 원칙 위반 검토
- "트레이딩"이 등장하면 → 사진 시스템 변경 금지, 별도 검토

## 핵심 시간 정책 (절대 변경 금지 — 의사결정 #21)

- **모든 동기화 작업은 03:00 일괄 시작** (Layer 4/5/뷰갱신/Layer 7/quarantine 폐기)
- 16:00 분석 단계만 분리 유지 (시간 소요)
- Layer 6 기기 정리는 03:30~05:30 윈도 (기기 트리거 한계)

## 트레이딩 시스템과의 관계 (절대 규칙)

- **트레이딩 시스템 위치**: 별도 디렉토리 (이 프로젝트 외부)
- **공유 자원**:
  - PostgreSQL 컨테이너 (사진 시스템은 `photo` schema만 사용)
  - Redis 컨테이너 (사진 시스템은 별도 key prefix)
  - Docker 호스트 + ollama (host.docker.internal:11434)
- **금지 사항**:
  - 트레이딩 시스템 워크플로우·DB schema 변경 절대 금지
  - 트레이딩 장중(09:00~15:30 KST 평일) 사진 시스템 **로컬 Qwen LLM 가동 금지**
  - 트레이딩 메모리 baseline 영향 ≤ 5%
- **enforcement** (코드 게이트):
  - `core/client/llm_gateway.py:_is_trading_hours_kst()` — 평일 09:00-15:30 KST 시 Qwen fallback 차단
  - 장중 Groq 실패 시 → `LLMGatewayError` → classifier `auto signals` fallback 사용 (ollama 호출 X)
  - 환경변수 `TRADING_HOURS_LOCAL_BLOCK=0` 으로 일시 비활성 가능 (테스트/긴급)

## 코드 구조 (Clean Architecture)

```
core/
├── domain/        # 의존성 0 (User, Asset, Grade, Classification)
├── repository/    # DB CRUD (Repository 패턴)
├── client/        # 외부 시스템 (Immich, Ollama, Notifier)
├── service/       # 도메인 로직
├── pipeline/      # Layer 0~7
├── infra/         # cross-cutting (Logger, Retry, Queue, Lock)
└── tests/         # unit/integration/e2e/golden

prompts/           # Qwen2.5-VL 프롬프트 템플릿 9개
workflows/         # n8n JSON (얇은 orchestration)
scripts/           # 마이그레이션·롤백·복원
runbooks/          # 장애 복구 가이드
```

**의존성 방향**: `domain ← repository/client ← service ← pipeline ← workflows`

## 코딩 도구·표준

- **Python**: 3.12+
- **패키지**: poetry (`pyproject.toml`)
- **린트·포맷**: ruff (단일 도구, lint+format 통합)
- **테스트**: pytest + testcontainers + hypothesis
- **타입**: mypy (점진 도입, Phase 4 이후 strict)
- **로그**: structlog (JSON 표준, trace_id 전파)
- **CI**: GitHub Actions

## 시크릿 관리

- `.env`는 git 추적 금지 (`.gitignore` 명시)
- `.env.example`만 git (placeholder)
- `.env.gpg`로 암호화 git 저장 (gpg-agent 부팅 자동 복호화)
- API 토큰·DB 비번은 환경변수로만 주입

## Phase 진행 상태

- [x] 설계 문서 v3.10 FINAL
- [x] 의사결정 24건 확정
- [x] **Phase 0** — 사전 자산 인벤토리 (3,728장 분류 완료)
- [x] **Phase 0-LLM** — Qwen2.5-VL 7B + Groq Llama-4-scout 앙상블 검증
- [x] Phase 1 — 인프라 (Postgres·Redis·Caddy·Cloudflare 터널)
- [x] Phase 2 — Immich 4컨테이너 (External Library /Volumes/Immich-Storage)
- [x] Phase 3 — 백업 마이그레이션 (3,728장 + 본식 영상 보존)
- [x] **Phase 4** — 분류 자동화 (classify-service + n8n cron 5분, 2026-05-02 활성)
- [ ] **Phase 4.5** — 14일 dry-run 누적 (현재 진행 중, 자동 보고)
- [ ] Phase 5 — 실삭제 단계적 활성화 (도메인 안전, **DEEP-ARCHITECT 필수**)
- [ ] Phase 6 — HDD 마이그레이션 (HDD 도착 후)
- [ ] Phase 7 — 운영·모니터링·DR (Telegram 알림 부분 가동 중)

## 운영 컴포넌트 (현재 상태)

- `photo-classify` 컨테이너 (8765 노출, trading_net) — 분류 HTTP 서비스
- n8n `photo-auto-classify` 워크플로 — 5분 cron, `/process_pending` 호출
- 호스트 crontab (운영 모드, 2026-05-05~):
  - `*/30 * * * * maintenance.sh` — health, 앨범, dedup, Immich sync, Layer 5 cleanup, reconcile, view symlink (DB/파일 IO만, LLM 호출 X)
  - `*/30 * * * * memory_guard.sh` — 메모리 압력 감지·조치
  - `0 4 * * * docker restart photo-classify` — 일일 재시작 (메모리 정리)
  - `0 9 * * 0 weekly_kpi.py` — 주간 KPI (Groq + Telegram)
- n8n 워크플로:
  - `photo-auto-classify` cron: **`0 3 * * *` (매일 03:00 KST 1회)** — LLM 분류 트레이딩 자원 보호
- 정책 분리 (사용자 결정 2026-05-05):
  - **분류 (LLM 호출) = 03:00** — 트레이딩 자원 보호 + Phase 5 정책 일관
  - **maintenance (DB/파일 IO) = 30분** — 즉시성 유지 (view 정합, Album 동기화)

## v3.13 Cleanup 정책 (사용자 명시, 2026-05-03)

### iPhone 보존 정책 (Layer 6)
```sql
KEEP = (grade IN ('BEST', 'EVENT', 'MEMORY+') OR contains_child = TRUE)
   AND grade != 'TRASH'
   AND grade_source != 'dedup_demoted'
DELETE = 그 외 (EVENT-L/FOOD/MEMORY-/NORMAL with contains_child=FALSE, TRASH 전체, dedup_demoted 전체)
```
- `contains_child = TRUE` 자산은 등급 무관 iPhone 보존 (단 TRASH·dedup 제외)
- TRASH는 contains_child 무관 항상 삭제 (사용자 명시)
- dedup_demoted (중복 사본)는 iPhone·HDD 모두 삭제
- iOS "최근 삭제됨" 30일 보관으로 안전망

### HDD 영구 삭제 정책 (Layer 5)
```
영구 삭제: TRASH (30일 grace 후) + dedup_demoted (verify_backup_full PASS 후 즉시)
보존:      나머지 모든 등급 (MEMORY-, NORMAL, FOOD, EVENT-L 포함)
```
- TRASH 외 모든 등급은 HDD 영구 보존 (사용자 명시 안전 정책)
- 중복(dedup) 사본만 verify PASS 후 즉시 삭제 가능

### Phase 5 단계적 활성화 절차 (2026-05-03 결정 + 단축 결정)
1. 분류 100% 완료 (✅ 12,205/12,205, pending 0, 2026-05-03)
2. `verify_backup_full.py` PASS (>= 99%) — iPhone 자산 매칭 보강 포함
3. cleanup_queue 등록 — TRASH·MEMORY-·dedup_demoted 우선
4. iOS Shortcut 설치 (`runbooks/layer6_ios_shortcut.md`)
5. 시범 20장 (1주차) → 100장 (2주차) → 무제한 (3주차+) — `phase5_ready.flag` ctime 기반
6. TRASH HDD 영구삭제: 24h grace (단축) / dedup_demoted: verify PASS 후 즉시

### iCloud 보존 등급 (사용자 명시, 2026-05-05)

iCloud Photos 영구 보존 (Mac/iPhone 정리 대상 X):

| 등급 | 정의 | iCloud 보존 |
|---|---|---|
| **BEST** | 일반 좋은 컷 | ✅ 보존 |
| **EVENT** | 행사·이벤트 사진 | ✅ 보존 |
| **MEMORY+** | 사람 + 화질 OK | ✅ **보존** (사용자 명시 강화) |
| **EVENT-L** | 행사 영상/burst 강등 | iCloud 보관, 사용자 검토 |
| **FOOD** | 음식 사진 | iCloud 보관, 사용자 검토 |
| **MEMORY-** | 사람 + 흐림 | iCloud 보관, 사용자 검토 |
| **NORMAL** | 사람 없는 일반 | iCloud 보관, 사용자 검토 |
| **TRASH** | 의미 없는 사진 + 중복 | ❌ 자동 정리 대상 |

**Mac Photos 앨범 자동 동기** (`scripts/sync_photos_albums.py`):
- 8등급 모두 Mac Photos.app Manual Album에 자동 추가
- iCloud 동기로 iPhone/iPad 자동 표시
- 사용자가 Mac Photos에서 등급별 검토 + 정리 가능
- TRASH 앨범 정리 → iCloud → iPhone 자동 정리 (30일 안전망)

### 8등급 상세 명세 (사용자 명시, 2026-05-04)

| 등급 | 정의 | 분류 트리거 |
|---|---|---|
| **BEST** | 보존가치 高. 일반 인물 사진 / 풍경·사물 좋은 컷 (사람 1-2명, 자연스러운 일상) | LLM=BEST |
| **EVENT** | 행사·이벤트 사진. 사람 3+ 또는 행사 키워드 | LLM=EVENT (사람 3+ OR 케이크·꽃다발·드레스·한복·웨딩·돌잔치·생일·졸업·기념일·신생아·만삭·100일·돌·칠순) |
| **EVENT-L** | 행사 영상 또는 행사 burst dedup 강등. EVENT의 long-form/낮은 우선 보존 | 영상 ≥3초 (`auto_video`) / EVENT 그룹 dedup 강등 (`dedup_demoted`) / 사용자 명시 환원 자산 (`restored_from_dedup`) |
| **FOOD** | 음식 사진. 음식이 화면 50% 이상 | LLM=FOOD |
| **MEMORY+** | 추억 (사람 + 화질 OK). LLM 미평가 시 auto 신호 기반 | `face_count > 0 AND laplacian ≥ 100` (`auto_quality_ok`/`reclass_face`) |
| **MEMORY-** | 추억 (사람 + 흐림). 단순 흐림은 보존 (TRASH 아님) | `face_count > 0 AND laplacian < 100` (`auto_blurry`/`reclass_face_blurry`) |
| **NORMAL** | 일반 사진 (사람 없는 카메라 사진, 풍경/사물) | `face_count == 0 AND camera_make IS NOT NULL` (`auto_no_face`/`reclass_camera_no_face`) |
| **TRASH** | 의미 없는 사진 + 중복 (사용자 명시 정의 — 위 [TRASH 정의] 참조) | LLM=TRASH / `auto_screenshot` / `auto_short_video` (영상<3초) / `dedup_demoted` |

### TRASH 등급 정의 (사용자 명시, 2026-05-04)

TRASH = 다음 둘 중 하나:

1. **중복 사진** — 같은 시각(1초 단위)·같은 카메라 그룹의 quality rank 2+ (1장만 보존)
2. **의미 없는 사진** — 사진 내용 자체가 보존 가치 없음:
   - UI 스크린샷, 완전 흑백/단색 화면
   - 초점이 완전히 나간 사진 (피사체 식별 불가)
   - 바닥·벽·천장만 찍힌 사진 (피사체 없음)
   - 잘못 촬영된 사진 (손가락 가림, 심한 흔들림, 노출 완전 실패)
   - 매우 짧거나 잘못 찍힌 영상

**단순 흐림(약간 초점 안 맞음)은 TRASH 아님** → MEMORY-/BEST/EVENT 보존.

LLM prompt는 `core/service/classifier.py:PROMPT`에 반영.

### 외장 HDD 통합 view (사용자 명시 2026-05-04)

iPhone 자산(`immich-uploads/`) + legacy 자산(`immich-media/library/{GRADE}/`)은 Immich 자체 구조상 분리. 등급별 통합 가시화는 **`immich-views/{GRADE}/{asset_id}.{ext}` symlink**로 해결:

```
/Volumes/Immich-Storage/
├── immich-media/library/{GRADE}/    ← legacy 자산 원본 (External Library)
├── immich-uploads/upload/{user}/    ← iPhone 자동 백업 원본
└── immich-views/
    ├── 월별/                         ← 기존 월별 view
    ├── BEST/                         ← 신규: 등급별 통합 view (legacy + iPhone)
    ├── EVENT/
    ├── EVENT-L/
    ├── FOOD/
    ├── MEMORY+/
    ├── MEMORY-/
    ├── NORMAL/
    └── TRASH/
```

- symlink target = 호스트 절대경로 (외장 HDD 자산)
- 디스크 추가 ~0
- `core/pipeline/layer5_album.refresh_view_link` — 분류 변경 시 자동 갱신
- `scripts/build_grade_views.py` — 전수 일괄 생성 (`maintenance.sh` `[7/7]` 30분 cron)

### 자동 분류 룰 (분류 결정 트리)

신규 자산은 n8n `photo-auto-classify` (5분 cron) → `/process_pending` → `/classify_and_persist` 자동 흐름:

```
입력: Immich asset (이미지 또는 영상)
  │
  ├─ 영상?
  │   ├─ duration < 3초 → TRASH (auto_short_video)
  │   └─ duration ≥ 3초 → EVENT-L (auto_video)
  │
  └─ 이미지:
      │
      ├─ Vision LLM 호출 (Groq Llama-4 Scout 우선 → Qwen VL 7B fallback)
      │   ├─ LLM=TRASH → TRASH (llm_*)
      │   ├─ LLM=FOOD  → FOOD  (llm_*)
      │   ├─ LLM=EVENT → EVENT (llm_*)
      │   ├─ LLM=BEST  → BEST  (llm_*)
      │   └─ LLM 응답 X (gateway 실패) → ↓ auto 신호
      │
      └─ Auto 신호 fallback (OpenCV + EXIF):
          │
          ├─ is_screenshot (face=0 + camera_make=∅ + 종횡비 1.7~2.3) → TRASH (auto_screenshot)
          ├─ face_count > 0 + laplacian < 100 → MEMORY- (auto_blurry)
          ├─ face_count > 0 + laplacian ≥ 100 → MEMORY+ (auto_quality_ok)
          ├─ face_count == 0 + camera_make != ∅ → NORMAL (auto_no_face)
          └─ face_count == 0 + camera_make == ∅ → TRASH (auto_screenshot fallback)

분류 후:
  → DB INSERT photo.classification
  → Immich Album 자동 추가 (등급별)
  → 일정 후 dedup_similar (1초 그룹 + EVENT-L 강등)
  → 후속 reconcile_grade_folders (HDD 폴더 정합)
```

### 분류 결정 우선순위

1. **LLM 응답** > Auto 신호 (LLM이 응답하면 그대로 사용)
2. **EXIF camera_make** > 종횡비 휴리스틱 (카메라 메타 있으면 screenshot 아님)
3. **face_count** 우선 검사 (사람 있으면 절대 TRASH 아님 — 추억 보호)
4. **단순 흐림 ≠ TRASH** (laplacian < 100은 MEMORY-, < 30 정도만 LLM이 TRASH 판정 시 적용)

### 단축 결정 (사용자 명시, 2026-05-03 / 2026-05-04)

> 14일 dry-run 게이트 + TRASH 30일 grace를 단축. 백업 검증·시범 limit·보호 게이트는 절대 우회 X.

| 항목 | 이전 정책 | 단축/변경 결정 |
|---|---|---|
| 14일 dry-run 게이트 | `min_age_days=14` | `min_age_days=0` (2026-05-03) |
| TRASH 30일 HDD grace | 30일 | **7일** (사용자 명시 확대 2026-05-05) |
| `auto_short_video` 임계 | 5초 미만 | **3초 미만** (2026-05-04) |
| backup verify 4중 검증 | 필수 | 필수 (우회 X) |
| 시범 limit (`progressive=True`) | 20/100/200 | 20/100/무제한 |
| feedback_protect 자산 제외 | 필수 | 필수 (우회 X) |
| iPhone 보존 정책 (BEST/EVENT/MEMORY+/contains_child) | 필수 | 필수 (우회 X) |

> 정식 TC: `wiki/03-pdca/active/report/TC-phase5-fastlane.md`

## 절대 변경 금지 결정사항 (영구)

| 결정 | 영구 사유 |
|---|---|
| HDD 암호화 미도입 | 가정용 보관 + I/O 성능, 향후 재논의 안 함 |
| 유료 Vision API 미사용 | 무료 LLM만 사용 ($0/월). **v3.13 (2026-05-03)**: `VISION_MODEL_CHAIN` env 기반 동적 라우팅 (기본 groq→qwen fallback). v3.12 "외부 전송 절대 금지" 원복 — 사용자 명시 결정. |
| 코딩 도구 = Claude Code | 로컬 코딩 LLM 도입 안 함 |
| **단일 파이프라인 원칙** | 모든 사용자 동일 로직·n8n·Service. 사용자별 분기는 §3.7.2의 5가지 외 절대 금지. 새 분기 추가 시 DEEP-ARCHITECT 강제 승격. |

## SDLC 적용

- 글로벌 SDLC (`~/.claude/sdlc/`)는 그대로 적용
- 이 프로젝트의 도메인 안전 영역: 사진 삭제·기기 정리·HDD 마이그레이션
- 위 영역 변경 시 자동 DEEP-ARCHITECT 승격 + 정식 TC 파일 필수
