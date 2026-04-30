# 운영 Runbooks

장애 시나리오별 복구 절차. 새벽 장애 시 빠른 복구를 위해 미리 검증된 단계 명시.

## 작성 예정 Runbooks (Phase 7 도달 시 완성)

| 파일 | 시나리오 | 목표 RTO |
|---|---|---|
| `recover_on_new_mac.md` | M4 mini 고장 → 다른 Mac 마이그레이션 | 4시간 |
| `hdd_failure.md` | HDD 고장 → 클라우드 복원 (EVENT/BEST/♥만) | 1일 |
| `ssd_failure.md` | 내장 SSD 고장 → TimeMachine 복원 | 1일 |
| `postgres_corruption.md` | DB 손상 → HDD `_backup/` pg_dump 복원 | 4시간 |
| `ollama_crash.md` | Ollama OOM·crash → 재시작 + 모델 재로드 | 30분 |
| `n8n_workflow_fail.md` | 워크플로우 실패 누적 | 1시간 |
| `disk_full.md` | HDD/SSD 용량 부족 | 즉시 |

각 Runbook은 SDLC sdlc-core.md 의 PDCA + 실패 에스컬레이션 정책 따름.
