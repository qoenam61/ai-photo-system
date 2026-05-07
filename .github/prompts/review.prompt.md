---
mode: 'agent'
description: '도메인 안전 + 보안 + Alignment 관점 코드 리뷰'
---

선택한 코드 또는 ${input:targetFile}을 다음 기준으로 리뷰하세요.

## 1. 도메인 안전 영역 검증

CLAUDE.md "도메인 안전 키워드" 해당 시:
- [ ] DEEP-ARCHITECT 모드로 작성됐는가?
- [ ] 정식 TC 파일이 존재하는가?
- [ ] PRD/DD 문서가 wiki/03-pdca/active/ 에 있는가?

## 2. 분류 정책 정합성 (사진 시스템)

`wiki/01-sot/grade_classification_spec.md`와 정합:
- [ ] 8등급 외 새 grade 도입 X
- [ ] iCloud 등급(BEST/EVENT/EVENT-L/MEMORY+) vs HDD only 분리
- [ ] 얼굴 가시성 룰 준수 (EVENT/BEST는 얼굴 명확)
- [ ] dedup_demoted_*는 강등만 (HDD 보존)

## 3. 트레이딩 시스템 보호

- [ ] 평일 09:00~15:30 KST 로컬 LLM 차단 게이트 적용
- [ ] PostgreSQL `photo` schema만 사용 (다른 schema 영향 X)
- [ ] Redis 별도 prefix
- [ ] 메모리 baseline 영향 ≤ 5%

## 4. 보안

- [ ] SQL injection 방어 (parameterized queries)
- [ ] AppleScript injection 방어 (UUID regex 검증)
- [ ] 시크릿 git 추적 X (.env, credentials)
- [ ] subprocess 인자 list (shell=True 금지)

## 5. 코드 품질

- [ ] Python 3.12+ 문법 (X | None)
- [ ] structlog JSON 로그 + trace_id
- [ ] 의존성 방향 (domain ← repository ← service ← pipeline)
- [ ] mypy type hints

## 6. TC-First 원칙

- [ ] EXPECTED 결과가 명시됐는가?
- [ ] 테스트가 ACTUAL을 검증하는가?
- [ ] 80% 커버리지 (단위) 또는 도메인 안전 영역은 100%

## 출력

각 항목에 ✅/⚠️/❌ + 위반 시 구체적 코드 위치 + 수정 제안.
