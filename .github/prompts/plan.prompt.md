---
mode: 'agent'
description: 'PLAN 단계 — 작업 분류 + EXECUTION BRIEF 작성'
---

다음 작업에 대해 EXECUTION BRIEF를 작성하세요.

요청: ${input:task}

작성 항목:

1. **작업 분류**: FAST-VERIFY / SAFE-REVIEW / DEEP-ARCHITECT 중 하나
   - 도메인 안전 키워드(CLAUDE.md 참조) 감지 시 자동 DEEP-ARCHITECT
2. **모델 라우팅**: GPT-4o / Claude 3.5 Sonnet / o1 중 하나 + 근거
3. **수행 범위**:
   - 파일 목록 (예상 변경)
   - 금지 경로 (수정 금지)
4. **Builder 지시사항**: 단계별 구현 가이드
5. **검증 기준** (Reviewer):
   - 코드 매핑 (요구사항 ID → 코드 위치)
   - TC PASS 항목
   - Alignment 목표 (FAST 90% / SAFE 99%)
6. **리스크**: 트레이딩 시스템 영향 / 도메인 안전 영역 / 시간 정책 위반 가능성

출력 형식: 한국어 마크다운 (코드는 영어 OK).
