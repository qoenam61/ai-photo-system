---
applyTo: "**"
description: "SDLC 핵심 원칙 — PDCA, 작업 분류, TC-First (글로벌 SSoT 동기화 본)"
---

# SDLC Core (이 프로젝트 적용판)

전역 SSoT는 `~/.copilot/sdlc/sdlc-core.md`. 이 파일은 프로젝트별 override만 포함.

## 작업 분류 (자동 적용)

```
FAST-VERIFY    — 단일 파일 + 비도메인 안전     → GPT-4o
SAFE-REVIEW    — 2~4파일 + 명확 범위           → Claude 3.5 Sonnet
DEEP-ARCHITECT — 신규 서비스/구조 변경         → o1 또는 Claude 3.5 Sonnet
```

도메인 안전 키워드(CLAUDE.md 참조) 감지 시 FAST → DEEP 자동 승격.

## PDCA 산출물 경로

| 단계 | 경로 |
|------|------|
| SSoT | `wiki/01-sot/` |
| PLAN | `wiki/03-pdca/active/plan/` |
| DESIGN | `wiki/03-pdca/active/design/` |
| DO | `wiki/03-pdca/active/do/` |
| CHECK | `wiki/03-pdca/active/report/` |
| 운영 가이드 | `wiki/04-guides/` |

## TC-First 원칙

```
EXPECTED 작성 → 구현 → ACTUAL 기록 → PASS → 배포
```

- 도메인 안전 영역: 정식 TC 파일 필수
- 비도메인 안전 영역: 커밋 메시지 인라인 TC 허용

## Alignment 기준

- SAFE: ≥ 99%
- FAST: ≥ 90%
