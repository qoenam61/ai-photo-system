# Session Checkpoint — Phase 5 + AI Promote 진행 중

**최종 갱신**: 2026-05-04 22:00
**세션 모드**: DEEP-ARCHITECT (도메인 안전 + AI 분류 본질 작업)

## 가동 중인 백그라운드 작업

| 작업 | PID | 시작 | 완료 예상 | 로그 |
|---|---|---|---|---|
| ~~promote v1 (4,290장)~~ | 7714 | 2026-05-04 | **완료 — 236장 promote** | `/tmp/promote_event_l.log` |
| ~~promote v2 (4,054장)~~ | 42937 | 2026-05-05 ~22:00 | **완료 — 737장 promote (2,469 fail)** | `/tmp/promote_event_l_v2.log` |
| **promote v3 (잔여 3,317장)** | **40329** | 2026-05-05 ~23:00 | ~30min~5h | `/tmp/promote_event_l_v3.log` |

> 강화 정책 발효 후 (TRASH 정의 / camera_make / 장중 차단) 재실행. Groq 우선 0.72초/장.

## cleanup_queue: **정지 상태 유지** (도메인 안전)

| 항목 | 값 |
|---|---|
| total | 3,443 |
| processed (이미 회수) | 386 (1,181.8 MB) |
| **active** | **0** ← 정지 |
| cancelled | 3,057 |

> 사용자 명시 없는 한 cleanup 재개 X.

## AI promote 완료 후 후속

1. `tail /tmp/promote_event_l.log` 결과 확인
2. 등급 분포 검증: `SELECT grade, COUNT(*) FROM photo.classification`
3. 사용자에게 BEST/EVENT promote 통계 보고
4. cleanup_queue 재개 결정 받기 (잔여 진짜 TRASH 42장)

## 가동 중인 자동화

| 자동화 | 일정 | 비고 |
|---|---|---|
| n8n photo-auto-classify | 5분 cron | 신규 자산 분류 |
| maintenance.sh (호스트 cron) | **30분** ← Phase 5 dev 모드 | health + 앨범 + Layer 5 cleanup + reconcile |
| memory_guard.sh | 30분 | 메모리 압력 |
| photo-classify 재시작 | 04:00 일일 | 메모리 정리 |

## 인프라 복구 (이번 세션)

- LiteLLM proxy (`litellm_proxy` 컨테이너) 401/500 → 복구
  - `/Users/jw-home/.llm/.env` 신규 (GROQ_API_KEY 주입)
  - `/Users/jw-home/.llm/litellm_config.yaml`: ollama URL `localhost` → `host.docker.internal`
- vision_classify 정책: Groq 우선 → Qwen fallback (사용자 명시 하이브리드)

## 다음 세션 진입 첫 단계

1. **AI promote 진행 확인**:
   ```bash
   ps -p 7714 && tail -20 /tmp/promote_event_l.log || echo "완료됨"
   ```
2. **등급 분포 변화**:
   ```bash
   docker exec trading_postgres psql -U trading_user -d trading_db -c \
     "SELECT grade, COUNT(*) FROM photo.classification GROUP BY grade ORDER BY grade;"
   ```
3. **결과 통계 사용자에게 보고** + cleanup_queue 재개 결정 받기

4. **운영 모드 적용 완료 (사용자 결정 B — 분리, 2026-05-05)**:
   - n8n photo-auto-classify: **`0 3 * * *` (매일 03:00 KST 1회)** ✅ 적용됨
   - crontab maintenance.sh: **`*/30 * * * *` (30분 그대로)** — view 정합 즉시성 유지
   - memory_guard.sh: 30분 그대로
   - photo-classify 재시작: 04:00 일일

   분리 정책:
   - **분류 (LLM 호출) = 03:00** — 트레이딩 자원 보호
   - **maintenance (DB/파일 IO) = 30분** — view symlink + Album 즉시성

## 미커밋 파일

```bash
git status -s
```

## 절대 보호선 (변경 X)

- 백업 verify 4중 검증
- feedback_protect 자산 자동 제외
- 결혼식 사진 SAFE_FALLBACK=EVENT-L (LLM이 TRASH 판정해도 EVENT-L 유지)
- iPhone 보존 정책 (BEST/EVENT/MEMORY+/contains_child)
- 시범 limit progressive (1주차 20 / 2주차 100 / 3주차+ 무제한)
