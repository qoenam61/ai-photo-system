---
applyTo: "**/*.py"
description: "사진 시스템 코드 작성 시 도메인 룰"
---

# 사진 시스템 — Python 코드 작성 룰

## 도메인 SSoT (수정 시 동기화 필수)

- `wiki/01-sot/grade_classification_spec.md` — 8등급 분류 SSoT
- `core/service/classifier.py:PROMPT` — LLM 분류 프롬프트
- `CLAUDE.md` "8등급 상세 명세" 섹션

## 분류 등급 8종 (절대 변경 금지)

```python
VALID_GRADES = {"BEST", "EVENT", "EVENT-L", "FOOD", "MEMORY+", "MEMORY-", "NORMAL", "TRASH"}
```

새 등급 추가 절대 금지. 등급별 정책 변경은 DEEP-ARCHITECT 강제 승격.

## iCloud 동기 등급 (Mac 앨범)

```python
ICLOUD_GRADES = {"BEST", "EVENT", "EVENT-L", "MEMORY+"}
HDD_ONLY_GRADES = {"FOOD", "MEMORY-", "NORMAL"}
DELETE_TARGET = {"TRASH"}
```

## 사용자 명시 절대 룰

1. **얼굴 가시성**: EVENT/BEST/MEMORY+는 얼굴이 명확히 보여야 함
2. **단순 흐림 ≠ TRASH**: laplacian < 100은 MEMORY- 보존
3. **dedup_demoted_*는 등급 강등만**: HDD 영구 보존
4. **TRASH 외 모든 등급 HDD 영구 보존**
5. **단일 파이프라인**: 사용자별 분기 금지

## 트레이딩 시스템 보호

```python
# 평일 09:00~15:30 KST는 로컬 Qwen LLM 호출 차단
# core/client/llm_gateway.py:_is_trading_hours_kst() 게이트 사용 필수
```

## 코드 스타일

- Python 3.12+ 문법 (`X | None`, `dict[str, ...]`)
- ruff lint+format
- mypy type hints (점진 도입)
- structlog JSON 로그

## 의존성 방향

```
domain ← repository/client ← service ← pipeline ← workflows
```

상위 → 하위 import만 허용. 역방향 import 금지.

## 테스트

- pytest + testcontainers + hypothesis
- TC 파일은 `core/tests/{unit,integration,e2e,golden}/`
- 도메인 안전 영역 변경 시 정식 TC 파일 필수
