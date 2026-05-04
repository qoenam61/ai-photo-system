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
  - Docker 호스트
- **금지 사항**:
  - 트레이딩 시스템 워크플로우·DB schema 변경 절대 금지
  - 트레이딩 장중(09:00~15:30) 사진 시스템 LLM 가동 금지
  - 트레이딩 메모리 baseline 영향 ≤ 5%

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
- 호스트 crontab (Phase 5 안정화 dev 모드, 2026-05-04~):
  - `*/30 * * * * maintenance.sh` — 5단계: health, 앨범, dedup, Immich sync, **Layer 5 HDD cleanup**
  - `*/30 * * * * memory_guard.sh` — 메모리 압력 감지·조치
  - `0 4 * * * docker restart photo-classify` — 일일 재시작 (메모리 정리)
  - `0 9 * * 0 weekly_kpi.py` — 주간 KPI (Groq + Telegram)
- 운영 안정화 후 `cron.prod` (03:00 daily) 로 교체. dev↔prod 전환은 사용자 결정.

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

### 단축 결정 (사용자 명시, 2026-05-03 / 2026-05-04)

> 14일 dry-run 게이트 + TRASH 30일 grace를 단축. 백업 검증·시범 limit·보호 게이트는 절대 우회 X.

| 항목 | 이전 정책 | 단축/변경 결정 |
|---|---|---|
| 14일 dry-run 게이트 | `min_age_days=14` | `min_age_days=0` (2026-05-03) |
| TRASH 30일 HDD grace | 30일 | 24h (2026-05-03) |
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
