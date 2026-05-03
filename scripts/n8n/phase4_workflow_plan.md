# Phase 4 — n8n 자동 분류 워크플로

**상태**: 설계 완료, 실 구현은 iPhone 업로드 시작 후 점진 활성화

## 트리거 옵션

| 옵션 | 장단점 | 권장 |
|---|---|---|
| Immich Webhook | 자산 즉시 처리 | ✅ 우선 |
| Cron Poll (5min) | 단순, Immich Webhook 미지원 시 | 폴백 |

현재 `maintenance.sh`가 30분마다 폴링 중 (cron.dev). n8n 진입 전 임시 운영.

## 워크플로 단계

```
1. Trigger
     │
2. HTTP GET /api/asset (External Library 외 신규 자산)
     │
3. SplitInBatches (size=10)
     │
4. HTTP POST → classify-service:8000/classify
     {asset_id, originalPath}  →  {grade, confidence}
     │
5. Postgres → INSERT INTO photo.classification
     │
6. HTTP PUT → Immich /api/albums/{grade_album}/assets
     │
7. Notification (옵션)
```

## 필요 컴포넌트 (이번 세션 미구현)

### 4-1. Classify Service (FastAPI 사이드카)

```python
# core/service/classifier.py 추출 → scripts/serve_classifier.py 로 wrap
# - core/client/groq_client.py 재사용
# - core/client/qwen_client.py 신설 (Ollama HTTP)
# - core/service/ensemble.py 신설 (가중 투표)
```

엔드포인트:
- `POST /classify` body: `{immich_id, image_b64}` → `{grade, conf, source}`
- `GET /health`

배포: `docker-compose.yml` 에 `classify-service` 추가, `trading_net` 합류

### 4-2. n8n 워크플로 import

`workflow_classify_new.json` (다음 세션 생성)

### 4-3. Immich Webhook 등록

`Settings → Server Settings → Webhooks → POST {n8n}/webhook/asset-uploaded`

## 마이그레이션 경로

1. **현재**: maintenance.sh + cron 폴링 (앨범 동기화만, 분류 X)
2. **다음**: classify-service 띄우기 + n8n 워크플로 import
3. **운영**: Immich Webhook 등록 → 실시간 분류

## 의존성 체크리스트

- [ ] core/client/qwen_client.py (Ollama 래퍼)
- [ ] core/service/classifier.py (migrate_backup.py 분류 로직 추출)
- [ ] scripts/serve_classifier.py (FastAPI)
- [ ] docker-compose.yml classify-service 추가
- [ ] scripts/n8n/workflow_classify_new.json
- [ ] Immich Webhook 설정
- [ ] iPhone 업로드 e2e 검증
