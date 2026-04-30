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
- **핵심 원칙**: 사진은 절대 외부 API로 나가지 않음, 원본은 절대 버리지 않음

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

- [x] 설계 문서 v3.6 FINAL
- [x] 의사결정 14건 확정
- [ ] **Phase 0** — 사전 자산 인벤토리 (다음 단계)
- [ ] **Phase 0-LLM** — Ollama + Qwen2.5-VL 7B 벤치마크
- [ ] Phase 1 — 인프라 (SSD vault + Docker + Redis Streams + Loki)
- [ ] Phase 2 — Immich 4컨테이너
- [ ] Phase 3 — 원본 수집 + 변환
- [ ] Phase 4 — 분류 자동화 + 14일 dry-run
- [ ] Phase 5 — 실삭제 단계적 활성화
- [ ] Phase 6 — HDD 마이그레이션 (HDD 도착 후)
- [ ] Phase 7 — 운영·모니터링·DR

## 절대 변경 금지 결정사항 (영구)

| 결정 | 영구 사유 |
|---|---|
| HDD 암호화 미도입 | 가정용 보관 + I/O 성능, 향후 재논의 안 함 |
| 유료 Vision API 미사용 | 사용자 정책 ($0/월), 정확도 부족 시 더 큰 로컬 모델로 대응 |
| 코딩 도구 = Claude Code | 로컬 코딩 LLM 도입 안 함 |

## SDLC 적용

- 글로벌 SDLC (`~/.claude/sdlc/`)는 그대로 적용
- 이 프로젝트의 도메인 안전 영역: 사진 삭제·기기 정리·HDD 마이그레이션
- 위 영역 변경 시 자동 DEEP-ARCHITECT 승격 + 정식 TC 파일 필수
