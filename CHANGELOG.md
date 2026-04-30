# Changelog

All notable changes to this project will be documented in this file.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
Versioning: 사진 시스템은 `vX.Y` (설계 문서), 코드는 `vX.Y.Z` (SemVer)

## [Unreleased] — Phase 0 준비

### Decisions Confirmed (2026-04-30, 24건 확정)

**인프라·운영 (1~8)**
- 로컬 LLM 정책: 유료 Vision API 폐기, Qwen2.5-VL 7B 단일
- HDD 암호화: ❌ 영구 미도입
- HDD 용량: 1TB 유지
- Postgres 분리: `photo` schema
- Redis Streams: Phase 1부터
- Loki 로그 통합: Phase 1부터
- Outbox pattern: 단순 폴링 (1초)
- Golden dataset: 100장
- 시크릿 관리: `.env.gpg`

**코드 구조·도구 (9~14)**
- 코드 구조: Clean Architecture (`core/{domain,repo,client,service,pipeline,infra}`)
- Python 도구: poetry + ruff + pytest
- 프롬프트: `prompts/*.md` 외부화
- n8n: 얇은 orchestration
- CI/CD: GitHub Actions

**HDD 폴더·스케줄 (15~24)**
- HDD 폴더 구조: 옵션 D 하이브리드 (등급 1차 + 뷰 심볼릭)
- 등급 폴더 8개: EVENT/EVENT-L/BEST/FOOD/MEMORY+/MEMORY-/NORMAL/TRASH
- 뷰 카테고리 4개: 행사별/月별/♥/음식
- 모든 동기화 03:00 일괄 (~13분)
- Layer 6 기기 정리: 03:30~05:30 윈도

### Documents
- `photo_system_design_v3.md` v3.7 FINAL — 설계 문서
- `local_llm_evaluation.md` v1.3 FINAL — LLM 평가
- `architecture_review.md` v1.4 FINAL — 아키텍처 평가 + 의사결정 24건

### Project Skeleton
- `.gitignore`, `pyproject.toml`, `CLAUDE.md`, `.env.example`, `CHANGELOG.md`
- `core/` Clean Architecture 디렉토리 (8개)
- `prompts/`, `runbooks/`, `scripts/`, `workflows/` 디렉토리 + README

### Implemented (Domain + Service stubs)
- `core/domain/grade.py` — 8등급 enum + EVENT 점수 가산제
- `core/domain/user.py` — UserContext (jw.son/eunju/shared)
- `core/domain/storage_layout.py` — HDD 옵션 D 폴더 경로 계산
- `core/service/storage_service.py` — 등급 폴더 이동 + 뷰 심볼릭 (Layer 5)

### Tests (38건)
- `test_grade.py` — 12 tests
- `test_user.py` — 7 tests
- `test_storage_layout.py` — 14 tests
- `test_storage_service.py` — 5 classes, ~15 tests

---

## Phase 0 (예정) — 사전 자산 인벤토리

- iPhone/Galaxy 사진 총 용량·HEIC 비율 측정
- iCloud/Galaxy Cloud 잔여 용량 측정
- SSD 가용공간 산출
- 트레이딩 시스템 baseline 기록

## Phase 0-LLM (예정) — 로컬 LLM 검증

- Ollama 설치 + Qwen2.5-VL 7B Q4_K_M 다운로드
- Whisper-small 다운로드
- 100장 벤치마크 (정확도 ≥ 80% 게이트)
- 메모리·속도 테스트
