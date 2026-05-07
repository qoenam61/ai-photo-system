# GitHub Copilot 지침 — ai-photo-system 프로젝트

이 파일은 GitHub Copilot이 이 프로젝트에서 자동 로드하는 항상-적용 지침입니다.
글로벌 SDLC (`~/.copilot/sdlc/`)와 결합되어 작동합니다.

---

## 프로젝트 개요

- **목적**: jw.son(iPhone) · eunju(Galaxy) 가족 2명의 사진 자동 분류·정리 시스템
- **호스트**: M4 Mac mini 16GB (트레이딩 시스템과 공존)
- **저장**: 외장 HDD 1TB + iCloud 50GB + Galaxy Cloud 15GB
- **분류**: 8등급 (EVENT / EVENT-L / BEST / FOOD / MEMORY+ / MEMORY- / NORMAL / TRASH)
- **LLM**: 로컬 Qwen2.5-VL 7B Q4_K_M + Groq Llama-4-Scout (체인)
- **핵심 원칙**: 원본은 절대 버리지 않음, HDD 영구 보존 (TRASH 외)

## 진입 문서 (작업 시 이 순서로 참조)

1. `CLAUDE.md` — 프로젝트 컨텍스트 SSoT (Copilot도 동일 기준 적용)
2. `wiki/01-sot/grade_classification_spec.md` — 8등급 분류 SSoT
3. `photo_system_design_v3.md` — 메인 설계 + 8-Phase 로드맵

## 도메인 안전 키워드 (자동 DEEP-ARCHITECT 승격)

다음 키워드 등장 시 모델을 **o1 또는 Claude 3.5 Sonnet**으로 변경하고 PRD/DD 문서 작성을 권장:
- "사진 삭제", "기기 정리", "Layer 6", "cleanup_queue"
- "변환", "HEIC", "HEVC", "Layer 0.5", "quarantine"
- "마이그레이션", "Phase 6", "originalPath 치환"
- "분류 등급", "EVENT 자동판정", "♥", "favorite"
- "등급 폴더 이동", "storage_service", "뷰 심볼릭", "TRASH cleanup"
- "동기화 03:00", "Layer 5"
- "사용자별", "jw.son만", "eunju만", "분기" → 단일 파이프라인 원칙 위반 검토
- "트레이딩"이 등장하면 → 사진 시스템 변경 금지, 별도 검토

## 핵심 시간 정책 (절대 변경 금지)

- 모든 동기화 작업 03:00 일괄 시작
- Layer 6 기기 정리 03:30~05:30 윈도
- 분류 (LLM) 03:00 / maintenance (DB·파일 IO) 30분
- cleanup-mac 04:15 / cleanup-mac-non-icloud 04:30 / sync-albums 03:35

## 트레이딩 시스템과의 관계 (절대 규칙)

- **트레이딩 시스템 위치**: 별도 디렉토리 (이 프로젝트 외부)
- **공유 자원**: PostgreSQL (`photo` schema만), Redis (별도 prefix), Docker, ollama
- **금지 사항**:
  - 트레이딩 시스템 워크플로우·DB schema 변경 절대 금지
  - 평일 09:00~15:30 KST 사진 시스템 **로컬 Qwen LLM 가동 금지**
  - 트레이딩 메모리 baseline 영향 ≤ 5%
- **enforcement**: `core/client/llm_gateway.py:_is_trading_hours_kst()` 게이트

## 코드 구조 (Clean Architecture)

```
core/
├── domain/        # 의존성 0
├── repository/    # DB CRUD
├── client/        # 외부 시스템
├── service/       # 도메인 로직
├── pipeline/      # Layer 0~7
├── infra/         # cross-cutting
└── tests/         # unit/integration/e2e/golden

prompts/           # Qwen2.5-VL 프롬프트
workflows/         # n8n JSON
scripts/           # 마이그레이션·롤백·복원
runbooks/          # 장애 복구
```

**의존성 방향**: `domain ← repository/client ← service ← pipeline ← workflows`

## 코딩 도구·표준

- **Python**: 3.12+
- **패키지**: poetry (`pyproject.toml`)
- **린트·포맷**: ruff
- **테스트**: pytest + testcontainers + hypothesis
- **타입**: mypy (점진 도입)
- **로그**: structlog (JSON, trace_id 전파)

## 시크릿 관리

- `.env`는 git 추적 금지
- `.env.example`만 git
- `.env.gpg`로 암호화 git 저장
- API 토큰·DB 비번은 환경변수만

## 운영 컴포넌트 (현재)

- `photo-classify` 컨테이너 (8765, trading_net)
- n8n `photo-auto-classify` (03:00 일일 cron)
- 호스트 crontab:
  - `*/30 maintenance.sh` — health/album/dedup/sync/reconcile/view
  - `*/30 memory_guard.sh`
  - `0 4 docker restart photo-classify`
  - `0 9 weekly_kpi.py` (일요일)
- launchd:
  - 03:35 sync_photos_albums (Mac 4등급 동기)
  - 04:15 cleanup_photos_mac (verify 4중)
  - 04:30 cleanup_mac_non_icloud (verify 우회)

## v3.13 Cleanup 정책 (사용자 명시)

### iPhone 보존 (Layer 6)
```sql
KEEP = (grade IN ('BEST', 'EVENT', 'EVENT-L', 'MEMORY+'))
DELETE = 그 외 (FOOD/MEMORY-/NORMAL/TRASH)
```

### HDD 영구 삭제 (Layer 5)
```
영구 삭제: TRASH (7일 grace)
보존:      나머지 모든 등급 (dedup_demoted_* 포함)
```

### iCloud 백업 등급 (Mac → iCloud → iPhone)
- ✅ BEST / EVENT / EVENT-L / MEMORY+
- ❌ FOOD / MEMORY- / NORMAL / TRASH

## 절대 변경 금지 결정사항 (영구)

| 결정 | 영구 사유 |
|---|---|
| HDD 암호화 미도입 | 가정용 + I/O 성능 |
| 유료 Vision API 미사용 | 무료 LLM만 ($0/월) |
| 코딩 도구 = Copilot/Claude Code | 로컬 코딩 LLM 도입 안 함 |
| 단일 파이프라인 원칙 | 사용자별 분기 절대 금지 (5가지 외) |

## SDLC 적용

- 글로벌 SDLC (`~/.copilot/sdlc/`)는 그대로 적용
- 도메인 안전 영역: 사진 삭제·기기 정리·HDD 마이그레이션
- 위 영역 변경 시 자동 DEEP-ARCHITECT 승격 + 정식 TC 파일 필수

## Copilot 활용 권장 패턴

- `@workspace 현재 분류 룰 어디서 정의?` — SSoT 자동 검색
- `@workspace #file:wiki/01-sot/grade_classification_spec.md 이 룰을 기반으로 ...` — 명시 참조
- `/explain` — 선택 코드 설명
- `/tests` — TC-First 테스트 생성
- `/review` — 보안/도메인 안전 관점
- `/fix` — 진단된 문제 수정
- 인라인 Chat (`⌘I`) — 1줄 변경
- Edit 모드 (`⌘⇧I`) — 다중 파일 변경 (Claude 3.5 Sonnet 권장)
