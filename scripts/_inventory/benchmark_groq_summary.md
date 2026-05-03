# Phase 0-LLM Groq Vision 벤치마크

- 모델: meta-llama/llama-4-scout-17b-16e-instruct
- 자산: 198 / 유효 73

## 정확도

- **41.1%** (30/73) — ❌ FAIL

## 처리 시간

- 중앙값 626ms / p95 1866ms — ✅ PASS

## 등급별

| 등급 | 자산 | 정확 | % |
|---|---|---|---|
| EVENT | 25 | 12 | 48.0% |
| BEST | 13 | 0 | 0.0% |
| FOOD | 6 | 6 | 100.0% |
| MEMORY+ | 12 | 11 | 91.7% |
| MEMORY- | 5 | 0 | 0.0% |
| NORMAL | 6 | 0 | 0.0% |
| TRASH | 6 | 1 | 16.7% |

## Confusion (사용자 → AI)

### EVENT (25)
- EVENT: 12 ✓
- MEMORY+: 9
- NORMAL: 2
- BEST: 1
- FOOD: 1
### BEST (13)
- MEMORY+: 13
### FOOD (6)
- FOOD: 6 ✓
### MEMORY+ (12)
- MEMORY+: 11 ✓
- MEMORY-: 1
### MEMORY- (5)
- MEMORY+: 4
- EVENT: 1
### NORMAL (6)
- MEMORY+: 5
- MEMORY-: 1
### TRASH (6)
- MEMORY-: 3
- NORMAL: 2
- TRASH: 1 ✓
