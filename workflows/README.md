# n8n Workflows (얇은 orchestration)

설계 의사결정 #13: **n8n 워크플로우는 얇게**. 비즈니스 로직은 `core/` Python 모듈에. n8n은 cron + HTTP 호출 + 에러 분기만.

## 작성 예정 Workflows

| 파일 | 트리거 | 호출 |
|---|---|---|
| `photo-1-upload.json` | Immich AssetUploaded Webhook | `core.pipeline.layer0_upload` |
| `photo-2-convert.json` | Webhook (큐 깊이 ≥ 1) | `core.pipeline.layer05_convert` |
| `photo-3-classify.json` | cron 매일 16:00 | `core.pipeline.layer1_preprocess` → 2 → 3 |
| `photo-4-vision.json` | cron 매일 03:00 | `core.pipeline.layer4_local_llm` |
| `photo-5-album.json` | cron 매일 03:30 | `core.pipeline.layer5_album` |
| `photo-6-feedback.json` | cron 매일 04:00 | `core.pipeline.layer7_feedback` |
| `photo-7-quarantine-purge.json` | cron 매일 06:00 | `core.service.conversion_service.purge_quarantine` |
| `photo-error.json` | 모든 워크플로우의 catch | `core.infra.error_handler.handle` |

## 작성 원칙

1. **얇게**: HTTP 노드 1~3개 + Function 노드 0~1개
2. **로직 금지**: Function 노드는 데이터 변환만, 분류·판정·DB 저장 금지
3. **트랜잭션 금지**: 트랜잭션은 Python에서만
4. **에러 표준화**: 모든 워크플로우 catch → photo-error 호출
5. **Idempotency**: 같은 자산 두 번 실행해도 결과 동일

## 트레이딩 워크플로우와 격리

n8n 인스턴스 공유, 단:
- 워크플로우 이름 prefix: `photo-` (트레이딩은 다른 prefix)
- 실행 시간 분리: 사진 16:00~05:00, 트레이딩 09:00~15:30
- 메모리 baseline 영향 ≤ 5% 모니터링
