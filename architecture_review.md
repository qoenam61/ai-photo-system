# 아키텍처·프로그래머 관점 평가 보고서
### M4 맥미니 사진 자동화 시스템 v3.5 평가
> v1.2 FINAL | 2026-04-30
> 평가 대상: `photo_system_design_v3.md` (v3.5 FINAL) + `local_llm_evaluation.md` (v1.3 FINAL)
> 평가 관점: 시니어 소프트웨어 아키텍트 + 운영 경험 보유 백엔드 엔지니어
> v1.0 → v1.1: 의사결정 8건 확정 + HDD 암호화 영구 거부 + 시스템 성숙도 모든 차원 9점+ 도달 로드맵 (§8)
> v1.1 → v1.2: **데이터 파이프라인 + 코드 재사용 + 유지보수 + 공용 로직 리팩토링 평가** (§9 신규)
> v1.2 → v1.3: **의사결정 14건 전체 확정** (§7 갱신) + 코드 모듈 구조 §9.4 채택
> v1.3 → v1.4: **HDD 옵션 D 하이브리드 + 03:00 동기화 일괄** (의사결정 24건 전체) + storage_service 모듈 추가 (§9.4)

---

## 1. 평가 범위·방법론

### 1.1 범위

- 사진 시스템 v3.4 8-Phase 전체 (마이그레이션 + 상시 파이프라인)
- 8레이어 분류 파이프라인 (Layer 0~7)
- 영상 특화 처리 (§21)
- 트레이딩 시스템과의 공존
- 단일 호스트 (M4 mini 16GB) 운영

### 1.2 방법론

| 관점 | 평가 항목 |
|---|---|
| **아키텍처** (Top-down) | SPOF, 도메인 경계, 트랜잭션, 데이터 일관성, 확장성, 보안, 관측성, 배포 |
| **프로그래밍** (Bottom-up) | Idempotency, race condition, 에러 처리, 시크릿, 메모리, I/O, 테스트 |
| **운영** | 모니터링, 알림, 백업, 재해복구, 변경 관리 |

### 1.3 평가 기준 (severity)

| 등급 | 정의 | 액션 시점 |
|---|---|---|
| **Critical** | 시스템 동작 불가, 데이터 손실, 보안 침해 | Phase 1 시작 전 해소 |
| **High** | 운영 중 문제 발생 가능성 높음, 사용자 신뢰 저하 | Phase 4 dry-run 전 해소 |
| **Medium** | 장기 운영 누적 영향, 확장성 제약 | Phase 7 안정화 시 점진 개선 |
| **Low** | 개선 권장, 즉시 영향 적음 | 백로그 |

---

## 2. 아키텍처 평가 (10개 카테고리)

### A. 단일 호스트 SPOF — Critical

**문제**
- M4 Mac mini 1대에 트레이딩 + Immich + Postgres + Redis + Ollama + n8n + media-converter 전체 집중
- 하드웨어 고장(메인보드, SSD, 전원) 시 전체 다운
- 트레이딩 + 사진 시스템 동시 마비

**현재 설계 대응**
- 부분 대응: TimeMachine 백업 (§13c), HDD `_backup/` (§13a)
- 미흡: 다른 Mac으로 즉시 fail-over 불가, 클라우드 의존 일부

**권장 개선**
- 정기 시스템 클론 (Carbon Copy Cloner 주간) → 외장 SSD 보관
- 마이그레이션 런북 작성 (다른 Mac에서 docker-compose up + DB restore)
- M4 mini RTO 목표: 4시간 (RPO 1일)

---

### B. 데이터베이스 도메인 경계 — High

**문제**
- 동일 Postgres 인스턴스에 트레이딩 DB + Immich DB + 사진 분류 테이블
- v3.4 §7에 "PostgreSQL 트레이딩+Immich 통합" 명시
- 한 도메인의 슬로우 쿼리·테이블 락이 다른 도메인에 영향

**현재 설계 대응**
- Immich는 별도 컨테이너(`immich-postgres`)로 분리 명시
- 사진 분류 테이블은 트레이딩 Postgres에 추가

**권장 개선**
```
Option A (간단): trading_postgres + immich_postgres 두 인스턴스
                → 사진 분류 테이블은 trading_postgres에 schema 분리
                  (CREATE SCHEMA photo; photo.classification, photo.feedback)

Option B (권장): trading_postgres + immich_postgres + photo_postgres 3 인스턴스
                → 도메인 격리 100%, 메모리 ~1GB 추가
                → 대안: photo는 trading의 schema로 (Option A)
```

---

### C. 트랜잭션 경계 분산 (3-Way Split) — High

**문제**
- Layer 5 앨범 배정은 3개 시스템에 걸친 작업:
  ```
  Immich API (앨범 멤버십 추가)
   ↓
  Postgres (cleanup_queue insert + photo_classification update)
   ↓
  파일시스템 (썸네일 캐시 갱신은 Immich 측)
  ```
- 중간 실패 시 부분 commit 발생 가능
  - 예: Immich 앨범 추가 OK, Postgres 실패 → cleanup 안 됨, 사용자에 잘못된 분류

**현재 설계 대응**
- §20.3 idempotency 명시
- 재시도 정책 일부 (n8n 5회)

**권장 개선**
- **Outbox Pattern** 도입:
  ```sql
  CREATE TABLE photo_outbox (
    id BIGSERIAL PRIMARY KEY,
    aggregate_id UUID NOT NULL,    -- asset_id
    event_type VARCHAR(50),        -- 'ALBUM_ASSIGN', 'CLEANUP_QUEUE', ...
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ
  );
  ```
- Postgres에 먼저 outbox row insert (single transaction)
- 별도 워커가 outbox → Immich API 호출 (실패 시 재시도)
- 결과: Postgres가 source of truth, Immich는 eventual consistency

---

### D. 큐 시스템 부재 — High

**문제**
- v3.4는 n8n executions를 사실상 큐로 사용
- 업로드 폭주 시 (예: 휴가 후 500장 동시 업로드) backpressure 처리 안됨
- n8n 동시 실행 수 제한이 명시되지 않음
- Layer 0.5 변환 큐 = 단순 폴더 watch (race condition 가능)

**현재 설계 대응**
- §20.1 트리거 매트릭스에 큐 depth 모니터링 명시
- §20.3 동시성 처리 일부

**권장 개선**
- **Redis Streams** 도입 (Redis 이미 가동 중, 추가 컨테이너 불필요):
  ```
  XADD photo:convert_queue * asset_id <UUID> codec <type>
  XREADGROUP GROUP converter worker1 COUNT 4 STREAMS photo:convert_queue >
  XACK photo:convert_queue converter <message_id>
  ```
- Consumer group으로 4 worker 분산
- Pending Entries List (PEL)로 미완료 추적
- 장점: at-least-once, backpressure 자동, 메시지 영속화

---

### E. 데이터 일관성 (Filesystem ↔ DB) — High

**문제**
- Immich `assets.originalPath` ↔ 실제 SSD/HDD 파일 동기화
- 파일은 있는데 DB row 없는 경우 (rsync 직접 + Immich 미스캔)
- DB row 있는데 파일 없는 경우 (수동 삭제)
- Phase 6 마이그레이션 시 path 일괄 치환 → 일치성 검증 필요

**현재 설계 대응**
- Phase 6 §12.6b Step 8 검증 (무작위 50장)
- §13a Postgres 백업

**권장 개선**
- **정기 reconciliation job** (주간):
  ```sql
  -- DB row 있는데 파일 없음
  SELECT a.id, a."originalPath" FROM assets a
  WHERE NOT exists_file(a."originalPath");

  -- 파일 있는데 DB row 없음 (Immich External Library scan)
  ```
- 불일치 발견 시 Telegram 알림 + 수동 검토

---

### F. 비즈니스 로직 위치 (n8n 의존 과다) — High

**문제**
- 핵심 분류 로직 (Layer 3 점수 가산제, Layer 5 앨범 매칭)이 n8n Function 노드에 JS로 작성됨
- n8n 워크플로우 = JSON 직렬화 → git diff 가독성 ↓
- 단위 테스트 불가능
- 코드 리뷰 어려움 (시각적 노드 그래프)
- 변경 이력 추적 불가

**권장 개선**
- **핵심 로직 Python 모듈로 분리**:
  ```
  /Users/jw-home/Work/photo_system/ai-photo-system/
  ├── pipeline/
  │   ├── layer1_preprocess.py
  │   ├── layer2_content_analysis.py
  │   ├── layer3_grade_decision.py    ← 점수 가산제
  │   ├── layer5_album_assign.py
  │   └── tests/
  │       ├── test_layer3_grade.py
  │       └── golden_dataset/
  └── n8n_workflows/
      └── photo-3-classify.json        ← orchestration만 (Python 호출)
  ```
- n8n은 cron + HTTP 호출 + 에러 분기만 담당
- Python 모듈은 pytest로 검증

---

### G. 배포·롤백 전략 — Medium

**문제**
- docker-compose up/down 단순
- 무중단 배포 없음 (Immich 재시작 시 사용자 끊김)
- 카나리/블루-그린 불가능 (단일 호스트 한계)
- 모델 업데이트 (Qwen 3.0 등) 시 분류 결과 변동 — 회귀 가능

**권장 개선**
- **롤백 스크립트** 작성:
  ```bash
  # rollback.sh
  CURRENT_TAG=$(docker compose ps --format json | jq -r '.image')
  PREV_TAG=$(cat .last-deploy.txt)
  docker compose up -d --no-deps --pull never <service>
  ```
- **이미지 tag pinning**:
  - `qwen2.5vl:7b-q4_K_M-2025-01` (날짜 포함)
  - 모델 변경 시 `model_version` 컬럼에 기록 → 롤백 시 식별
- **사진 시스템 자체는 야간 배포** (사용자 영향 없음, 03:00~04:00 윈도)

---

### H. 관측성 (로그·메트릭·트레이싱) — Medium

**문제**
- 로그 분산: Docker logs (n8n, Immich, Ollama, Postgres) + ffmpeg stderr + Python print
- 통합 검색·집계 불가
- 워크플로우 실패 시 어느 단계인지 추적 어려움
- 메트릭 수집 없음 (CPU, 메모리, 처리량, 응답 시간)

**현재 설계 대응**
- Telegram 알림 (단순)
- §13b 일일/주간 KPI 리포트

**권장 개선** (사용자 정책 "단순함" vs 운영성 trade-off)
- **경량 옵션**: Loki + Promtail (로그 수집), Grafana로 표시
  - 추가 메모리 ~500MB
  - 단일 docker-compose 통합
- **무거운 옵션**: Prometheus + Grafana + Loki + Tempo (추적)
  - 추가 메모리 ~2GB → 16GB 한도 빠듯
- **권장**: Phase 7 안정화 후 Loki만 도입 (로그 통합) + Telegram 알림 유지

---

### I. 보안 모델 — Medium (v1.1 갱신)

**가정용 위협 모델 정의** (가족 2명, 집 안 1대 호스트)

| 위협 | 방어 | 적용 |
|---|---|---|
| 외부 인터넷 공격 | Tailscale ACL 디바이스 화이트리스트 | ✅ |
| 가족 내 사용자 격리 | Immich External Library owner 분리 | ✅ |
| 시크릿 (토큰·DB 비번) 노출 | `.env.gpg` 암호화 git 저장 | ✅ |
| HDD 분실/도난 | (미적용 — §사용자 결정) | ❌ |
| 의존성 취약점 | 정기 docker scan + pip-audit | ✅ |
| 컨테이너 image 출처 | 공식 이미지만 사용 (tag pinning) | ✅ |

**HDD 암호화 미도입 (사용자 영구 결정, 2026-04-30)** ⚠️

- **사유**: HDD는 개인 보관용(집 안), 분실 위험 매우 낮음 + APFS Encrypted Volume의 I/O 성능 영향 회피
- **수용 리스크**: HDD 분실·도난 시 사진·DB 평문 노출
- **물리 보안 대체**: HDD를 집 내부에 보관, 외부 반출 금지
- **이 결정은 향후 다시 논의하지 않음** — Phase 7 운영 중에도 재검토 안 함

**권장 개선 (해결 가능 범위)**
- **시크릿 관리**: `.env.gpg` (gpg 암호화 + git 추적), 부팅 시 gpg-agent로 복호화
- **Tailscale ACL**: 디바이스 화이트리스트 + 분기별 토큰 회전 (자동화)
- **Immich 사용자 격리**: External Library owner 분리 + E2E 테스트로 검증
- **컨테이너 보안**:
  - 공식 이미지만 사용 (Immich, Ollama, Postgres, Redis 모두 공식 hub)
  - 이미지 tag pinning (`immich/immich-server:v1.130.0` 형식)
  - 분기별 docker scan으로 CVE 점검
- **의존성 감사**: pip-audit, npm audit 분기별 실행
- **MacroDroid 권한 최소화**: MANAGE_EXTERNAL_STORAGE는 DCIM 하위만 접근하도록 매크로 작성

---

### J. 확장성 — Low (v1.1 갱신, 사용자 결정 반영)

**현재 결정 (2026-04-30)**: **HDD 1TB 유지**, 추후 필요 시 확장

**용량 모니터링 정책**
- 일일 SMART + 용량 추적
- 80% 도달 시 알림
- 90% 도달 시 신규 업로드 차단 + HDD 확장 결정 트리거

**해결 가능한 개선 (1TB 한도 내 효율화)**
- **Postgres 인덱스**:
  ```sql
  CREATE INDEX CONCURRENTLY ON photo_classification (user_account, grade, created_at);
  CREATE INDEX CONCURRENTLY ON photo_classification (similarity_group_id);
  CREATE INDEX CONCURRENTLY ON cleanup_queue (grace_until) WHERE processed_at IS NULL;
  ```
- **VACUUM ANALYZE 주간 cron**: Postgres 자동 vacuum + 명시적 ANALYZE
- **분류 로그 archiving**: 1년 이상 경과 row는 `photo_classification_archive` 테이블로 이전 (월간)
- **자산 누적 KPI**: 월별 증가율 추적 → 잔여 용량 예측

**확장 트리거 (미래)**
- HDD 사용률 ≥ 80% AND 6개월 내 100% 도달 예상 → 사용자에게 확장 결정 요청
- 옵션: 외장 HDD 2TB 추가 + Phase 6 마이그레이션 절차 재실행 (이미 검증됨)

---

## 3. 프로그래머 관점 평가 (15개 항목)

### 1. Idempotency — High

| 시나리오 | 현재 상태 | 권장 |
|---|---|---|
| 같은 자산 두 번 분류 | photo_classification 중복 row 가능성 | UNIQUE INDEX(asset_id, layer_version) + UPSERT |
| 변환 두 번 시도 | photo_conversion_log 중복 row 가능성 | UNIQUE(original_sha256) + ON CONFLICT DO UPDATE |
| Immich 앨범 중복 추가 | API 멱등 처리 (Immich 측 보장) | OK |

**권장 SQL**
```sql
ALTER TABLE photo_classification ADD CONSTRAINT photo_classification_asset_unique
  UNIQUE (asset_id);
-- 재분류 시 INSERT ... ON CONFLICT (asset_id) DO UPDATE
```

---

### 2. Race Condition — Critical

**시나리오**
- 양 사용자 같은 행사 사진 → shared_event_album_queue 동시 insert
- 사용자 ♥ webhook과 Layer 6 cleanup 동시 실행 → 삭제됐는데 ♥ 적용

**권장**
- Postgres advisory lock:
  ```sql
  SELECT pg_advisory_xact_lock(hashtext('shared_event_album:' || event_date));
  ```
- ♥ 처리 우선순위: webhook이 cleanup_queue.cancelled=TRUE를 트랜잭션 내 마킹 → Layer 6은 cancelled=FALSE만 SELECT FOR UPDATE

---

### 3. Retry · Circuit Breaker — High

**현재**
- n8n 기본 retry 3회
- exponential backoff 미명세
- Circuit breaker 없음 (Ollama 다운 시 무한 호출)

**권장**
- **Exponential backoff with jitter**:
  ```
  attempt 1: 1s
  attempt 2: 2s + jitter(0~500ms)
  attempt 3: 4s + jitter
  attempt 4: 8s
  attempt 5: fail, alert
  ```
- **Circuit breaker** (Ollama, Immich API):
  - 5분 내 5회 연속 실패 → 30분 차단
  - 차단 중 호출은 즉시 fail (큐만 적재)

---

### 4. 에러 처리 일관성 — High

**문제**
- 7개 워크플로우(#PHOTO-1 ~ #PHOTO-7) 각각 다른 에러 처리
- 알림 누락 가능
- 에러 분류 (transient vs permanent) 미명세

**권장**
- **표준 에러 핸들러 워크플로우** (#PHOTO-ERROR):
  - 모든 워크플로우의 catch 노드가 #PHOTO-ERROR 호출
  - severity 분류 → Telegram 알림 또는 silent log
- **에러 코드 표준화**:
  ```
  E_CONVERT_FAIL_DECODE     변환 디코딩 실패 (transient: ffmpeg 재시도)
  E_CONVERT_FAIL_META       메타 불일치 (permanent: quarantine)
  E_OLLAMA_TIMEOUT          모델 응답 없음 (transient: 재시도)
  E_OLLAMA_OOM              메모리 초과 (permanent: alert)
  E_IMMICH_API_5XX          서버 오류 (transient)
  E_IMMICH_API_4XX          요청 오류 (permanent: alert)
  ```

---

### 5. 시크릿 관리 — High

**문제**
- API 토큰 (Telegram, Tailscale, Anthropic은 미사용)
- DB 비번
- Immich admin 계정
- iOS Shortcut bearer token, MacroDroid token

**권장**
- `.env` 파일 git 추적 금지 (`.gitignore` 명시)
- `.env.example`만 git에 (값은 placeholder)
- `.env.gpg`로 암호화 git 추적 (gpg-agent로 부팅 시 복호화)
- Docker Secrets 사용 검토 (단일 호스트라 효과 제한)
- **회전 정책**: 분기별 Tailscale·Telegram 토큰 회전

---

### 6. 메모리 누수 — Medium

**위험 지점**
- Ollama 모델 swap 시 메모리 회수 미보장
- ffmpeg 자식 프로세스 좀비 (n8n 호출 시)
- Python multiprocessing pool 누수

**권장**
- **주간 컨테이너 재시작**:
  ```bash
  # cron 일요일 06:00
  docker compose restart ollama media-converter python-worker
  ```
- ffmpeg 호출은 timeout 설정 필수 (`-timeout 60`)
- Python pool은 with 문 사용

---

### 7. 디스크 I/O 병목 — Medium

**문제**
- HDD에 동시 쓰기:
  - Immich 썸네일·캐시 (HDD `library/thumbs/`)
  - Postgres 백업 (HDD `_backup/`)
  - 변환 quarantine (HDD `_convert/`)
  - n8n 로그
- USB3 5Gbps 한계 + HDD 100~150MB/s 한계

**권장**
- 썸네일은 SSD 유지 (Immich 설정으로 분리 가능)
- 백업은 야간 03:00 이후만 (사진 활동 적은 시간)
- 변환 quarantine은 SSD 임시 → 7일 후 HDD 이동 후 폐기 (현재 설계 OK)

---

### 8. 모델 버전 관리 — Medium

**문제**
- Qwen2.5-VL 7B 업데이트 시 분류 결과 변동
- 사용자 ♥ 패턴이 이전 모델 기준 → 새 모델에서 일관성 저하

**권장**
- **Ollama tag pinning**:
  ```bash
  ollama pull qwen2.5vl:7b-q4_K_M-2025-01
  # 자동 latest 사용 금지
  ```
- **DB 컬럼**: `photo_classification.model_version` (예: 'qwen2.5vl:7b-q4_K_M-2025-01')
- **모델 업그레이드 절차**:
  1. 새 모델 다운로드 (병렬 보관)
  2. 100장 샘플 비교 (golden dataset)
  3. 합격 시 docker-compose 변경 → 신규 자산만 새 모델
  4. 기존 자산은 강제 재분류 안 함 (사용자 ♥ 일관성 유지)

---

### 9. 테스트 전략 — High

**현재**
- 통합 테스트 없음
- 사용자 정책 "단순화"와 트레이드오프

**권장 (최소)**
- **Golden dataset**: 사용자 자체 사진 100장 + 라벨 → CI 회귀 검증
- **Smoke test**: 매 배포 후 자동 실행 (1장 분류 → 결과 확인)
- **Critical path 단위 테스트**: 점수 가산제 로직 (Layer 3) — Python 모듈로 분리 후 pytest

---

### 10. 시간대 처리 — Medium

**문제**
- EXIF DateTimeOriginal: timezone 정보 없음 (camera local time)
- GPS 기반 timezone 추론 가능하지만 미명세
- 야간 배치는 Mac 호스트 timezone (KST)

**권장**
- 모든 DB datetime은 `TIMESTAMPTZ` (Postgres)
- EXIF DateTimeOriginal은 GPS coords 있으면 timezonefinder 라이브러리로 보정
- GPS 없으면 KST 가정 (사용자 거주지)

---

### 11. 문자 인코딩 (한국어 파일명) — Low

**문제**
- macOS는 NFD (Unicode 정규화 분해)
- Linux는 NFC (조합)
- Docker 컨테이너 (Linux) ↔ macOS 호스트 동기화 시 한글 파일명 깨짐 가능

**권장**
- Immich External Library는 SHA256 기반 식별 (파일명 무관)
- Layer 0.5 변환 후 파일명을 UUID 기반으로 통일 (메타에서 원본 복원 가능)

---

### 12. 동영상 메타 손실 — Medium

**문제**
- ffmpeg `-map_metadata 0`은 컨테이너 메타만 복사
- iPhone 특화: `live_photo_id`, `slow_motion_metadata` 누락 가능
- Galaxy 특화: `single_take_id` 누락

**권장**
- exiftool 후처리:
  ```bash
  exiftool -overwrite_original -tagsFromFile input.mov \
    -all:all -api LargeFileSupport=1 output.mp4
  ```
- 검증 로그에 메타 누락 항목 기록

---

### 13. GDPR-style 사용자 권리 — Low

**문제**
- 데이터 휴대성 (export 도구) 명세 없음
- 잊혀질 권리 (전체 삭제) 명세 없음
- 가족 시스템이지만 미래 사용자 추가 시 격리 검증 필요

**권장**
- `export.sh`: 사용자별 자산 + 메타 ZIP export
- `wipe.sh`: 사용자 자산 + DB row + 클라우드 동기화 모두 삭제
- Phase 7 운영 매뉴얼에 포함

---

### 14. 모니터링 임계값 (정적 vs 동적) — Medium

**문제**
- "HDD 80% 알림"은 정적 임계값
- 어느 날 갑자기 90% 도달 시 사전 경고 부족

**권장**
- **사용량 증가율 기반 알림**:
  - 일일 증가량 > 평균 × 2 → 이상치 알림
  - 잔여 공간 / 일일 증가율 < 30일 → "30일 내 고갈 예상" 알림

---

### 15. 초기 부트스트랩 — Medium

**문제**
- Phase 4 dry-run 첫날: photo_classification 비어있음 → KPI 계산 불가
- Phase 0-LLM 벤치마크 결과를 Phase 1 진입 게이트로 명시

**권장**
- Phase 0-LLM 산출물에 "최소 100장 분류 완료" 명시
- Phase 4 Day 1~3은 KPI 미계산, Day 4부터 시작

---

## 4. 우려점 종합 표 (33건)

### Critical (Phase 1 시작 전 해소)

| # | 영역 | 우려점 | 대응 |
|---|---|---|---|
| C1 | 아키텍처 A | 단일 호스트 SPOF | 정기 클론 + 마이그레이션 런북 |
| C2 | 프로그래밍 2 | Race condition (♥ vs cleanup) | Advisory lock + cancelled 플래그 |

### High (Phase 4 dry-run 전 해소)

| # | 영역 | 우려점 | 대응 |
|---|---|---|---|
| H1 | 아키텍처 B | DB 도메인 경계 약함 | trading_postgres에 photo schema 분리 |
| H2 | 아키텍처 C | 트랜잭션 분산 | Outbox pattern |
| H3 | 아키텍처 D | 큐 시스템 부재 | Redis Streams 도입 |
| H4 | 아키텍처 E | FS↔DB 일관성 | 주간 reconciliation job |
| H5 | 아키텍처 F | n8n 의존 과다 | 핵심 로직 Python 모듈 분리 |
| H6 | 아키텍처 I | 보안 (HDD 암호화·시크릿) | APFS Encrypted + .env.gpg |
| H7 | 프로그래밍 1 | Idempotency | UNIQUE 제약 + UPSERT |
| H8 | 프로그래밍 3 | Retry·Circuit breaker | Exponential backoff + 5분 차단 |
| H9 | 프로그래밍 4 | 에러 처리 일관성 | 표준 #PHOTO-ERROR 워크플로우 |
| H10 | 프로그래밍 5 | 시크릿 관리 | .env.gpg + 토큰 분기 회전 |
| H11 | 프로그래밍 9 | 테스트 전략 | Golden dataset CI |

### Medium (Phase 7 안정화 시 점진 개선)

| # | 영역 | 우려점 | 대응 |
|---|---|---|---|
| M1 | 아키텍처 G | 배포·롤백 | rollback.sh + tag pinning |
| M2 | 아키텍처 H | 관측성 | Loki 도입 (Phase 7 후) |
| M3 | 아키텍처 J | 확장성 | HDD 2TB 검토 + 인덱스 + VACUUM |
| M4 | 프로그래밍 6 | 메모리 누수 | 주간 컨테이너 재시작 |
| M5 | 프로그래밍 7 | 디스크 I/O 병목 | 썸네일 SSD + 백업 야간 |
| M6 | 프로그래밍 8 | 모델 버전 관리 | tag pinning + model_version 컬럼 |
| M7 | 프로그래밍 10 | 시간대 처리 | TIMESTAMPTZ + timezonefinder |
| M8 | 프로그래밍 12 | 영상 메타 손실 | exiftool 후처리 |
| M9 | 프로그래밍 14 | 모니터링 임계값 | 증가율 기반 알림 |
| M10 | 프로그래밍 15 | 초기 부트스트랩 | KPI 시작 D+4 |

### Low (백로그)

| # | 영역 | 우려점 | 대응 |
|---|---|---|---|
| L1 | 프로그래밍 11 | 한국어 파일명 | UUID 기반 통일 |
| L2 | 프로그래밍 13 | GDPR 사용자 권리 | export.sh + wipe.sh |

---

## 5. 권장 개선 우선순위 (Phase 매핑)

### Phase 0/0-LLM 시작 전 (즉시)
```
[ ] C1. 시스템 클론 백업 절차 수립
[ ] C2. Race condition 방어 (advisory lock 설계)
[ ] H6. HDD 암호화 정책 결정 (APFS Encrypted 도입 여부)
[ ] H10. 시크릿 관리 (.env.gpg 또는 1Password CLI)
```

### Phase 1~2 (인프라·Immich 설치 시)
```
[ ] H1. Postgres schema 분리 (trading vs photo)
[ ] H7. Idempotency UNIQUE 제약 SQL 작성
[ ] H3. Redis Streams 워크플로우 설계 (사진 변환 큐)
```

### Phase 3 (원본 수집) 전
```
[ ] H5. Layer 3 점수 가산제 Python 모듈로 분리
[ ] H11. Golden dataset 100장 라벨링
[ ] H9. 표준 #PHOTO-ERROR 워크플로우 구현
[ ] M8. exiftool 후처리 검증 스크립트
```

### Phase 4 dry-run 동시
```
[ ] H2. Outbox pattern 구현 (Layer 5)
[ ] H4. FS↔DB reconciliation 주간 job
[ ] H8. Retry·Circuit breaker 정책 명시
[ ] M6. model_version 컬럼 + tag pinning
```

### Phase 7 안정화 후
```
[ ] M1. rollback.sh 작성
[ ] M2. Loki 로그 통합 (선택)
[ ] M4. 주간 컨테이너 재시작 cron
[ ] M9. 동적 임계값 알림
[ ] L1. 한국어 파일명 UUID 통일
[ ] L2. export.sh / wipe.sh
```

---

## 6. 결론 — 시스템 성숙도 평가

### 6.1 강점
- ✅ 도메인 로직 명확 (8레이어, 8등급 분류 기준)
- ✅ 사용자 정책 일관성 (비용 0, 프라이버시, 단순함)
- ✅ Phase별 진입 게이트 명확 (Go/No-Go 기준)
- ✅ 우려점 33건 사전 도출 (v3.1~v3.4)
- ✅ HDD 미연결 상태 운영 경로 확보 (Phase 0~5 SSD)

### 6.2 약점
- ⚠️ 단일 호스트 SPOF (가정용 시스템 한계, 수용 가능)
- ⚠️ n8n 워크플로우 의존 — 테스트·리뷰 어려움
- ⚠️ 트랜잭션 경계 분산 — Outbox pattern 도입 필요
- ⚠️ 큐 시스템 부재 — Redis Streams로 보강
- ⚠️ 관측성 부족 — Telegram 단순 알림에 의존

### 6.3 시스템 성숙도 점수 (v1.1 — §8 개선안 적용 후 목표)

| 차원 | v1.0 | **v1.1 목표** | 9점+ 도달 근거 (§8 상세) |
|---|---|---|---|
| 기능 완성도 | 9 | **9** | 이미 9점, 유지 |
| 신뢰성 | 6 | **9** | 클론 백업 + idempotency + outbox + Streams + 헬스체크 |
| 확장성 | 6 | **9** | 1TB 효율화 (인덱스·archiving·VACUUM·증가율 KPI) |
| 보안 | 5 | **9** | .env.gpg + Tailscale 회전 + 사용자 격리 E2E + image pinning + dep audit (HDD 암호화는 위협 모델상 불필요) |
| 관측성 | 4 | **9** | Loki + Grafana + JSON 표준 로그 + SLO + trace_id |
| 테스트 | 3 | **9** | pytest 단위 + golden dataset CI + smoke + E2E + 모델 회귀 |
| 운영성 | 6 | **9** | rollback.sh + runbook + 헬스체크 + DR 훈련 + 변경관리 |
| **종합** | 5.6 | **9.0/10** | 가정용 시스템에서 도달 가능한 최고 수준 |

### 6.4 가정용 시스템으로 적합한가? — ✅ Yes

- **지금 가동 가능 여부**: ✅ Phase 1~5 진행 가능 (Critical 2건 + High 6건 즉시 해소 후)
- **장기 운영 적합성**: ⚠️ Medium 10건 점진 개선 필요
- **상용 시스템으로 적합한가**: ❌ 보안·관측성·테스트가 가정용 수준

가정용 시스템(가족 2명, 5년치 사진)에는 적합한 설계. 다만 **Critical 2건과 High 6건은 Phase 1 진입 전 해소 권장**.

---

## 7. 확정 의사결정 14건 (v1.3, 2026-04-30 사용자 승인 완료)

### 인프라·운영 결정 (1~8)

| # | 항목 | 결정 | 사유 |
|---|---|---|---|
| 1 | HDD 암호화 (APFS Encrypted) | ❌ **미도입 (영구)** | 가정용 보관 + I/O 성능 영향 회피, 향후 재논의 안 함 |
| 2 | Postgres 도메인 분리 | ✅ **schema 분리** (`photo` schema in trading_postgres) | 메모리 절약, 인스턴스 추가 불필요 |
| 3 | Redis Streams 도입 시점 | ✅ **Phase 1부터** | 사진 변환 큐 처음부터 backpressure·idempotency 확보 |
| 4 | Loki 로그 통합 | ✅ **Phase 1부터** (변경) | 9점+ 관측성 도달 위해 초기 도입 |
| 5 | Outbox pattern 구현 깊이 | ✅ **단순 폴링** | Debezium CDC는 과도, 1초 폴링으로 충분 |
| 6 | Golden dataset 크기 | ✅ **100장** | jw.son 50 + eunju 50, 사용자 라벨링 부담 적정 |
| 7 | 시크릿 관리 도구 | ✅ **`.env.gpg`** (gpg + git) | 단일 호스트, 1Password 의존 회피, gpg-agent 표준 |
| 8 | HDD 용량 | ✅ **1TB 유지**, 80% 도달 시 확장 검토 | 현재 충분, 향후 필요 시 Phase 6 절차 재실행 |

### 코드 구조·도구 결정 (9~14)

| # | 항목 | 결정 | 사유 |
|---|---|---|---|
| 9 | 코드 모듈 구조 | ✅ **§9.4 Clean Architecture 채택** | 16개 공용 로직 추출, 변경 영향 5~10배 축소 |
| 10 | Python 패키지 도구 | ✅ **poetry** | 의존성 lock + venv 통합, pyproject.toml 표준 |
| 11 | 코드 스타일·린트 | ✅ **ruff** | lint + format 통합, 빠름, single binary |
| 12 | 프롬프트 외부화 | ✅ **`prompts/*.md`** | git diff 가독성, 워크플로우 외부 관리 |
| 13 | n8n 워크플로우 두께 | ✅ **얇게** (orchestration only) | 비즈니스 로직은 Python, n8n은 cron + HTTP |
| 14 | CI/CD 도구 | ✅ **GitHub Actions** | 외부 의존 최소, free tier 충분, repo 통합 |

### HDD 폴더·스케줄 결정 (15~24, v1.4 추가)

| # | 항목 | 결정 | 사유 |
|---|---|---|---|
| 15 | HDD 폴더 구조 | ✅ **옵션 D 하이브리드** (등급 1차 + 뷰 심볼릭) | Immich 죽어도 Finder에서 EVENT/BEST 식별 |
| 16 | 등급 폴더 = **8개** | EVENT/EVENT-L/BEST/FOOD/MEMORY+/MEMORY-/NORMAL/TRASH | 분류 등급 1:1 |
| 17 | 뷰 폴더 1차 카테고리 | `행사별/月별/♥/음식/` 4개 | 사용자 시각 다양성 |
| 18 | 뷰 갱신 시점 | Layer 5 직후 (03:08) | 등급 폴더 확정 후 |
| 19 | 등급 변경 시 Immich scan | 자동 (External Library auto-scan) | originalPath 자동 갱신 |
| 20 | TRASH 30일 cleanup | 폴더 mtime + DB trash_until 이중 안전 | 단순한 cron |
| 21 | **모든 동기화 03:00 일괄** ⭐ | 사용자 정책 | 단일 윈도, ~13분 내 완료 |
| 22 | 16:00 분석 단계 분리 | 그대로 유지 | 시간 소요 (수 시간), 동기화와 성격 다름 |
| 23 | Layer 6 기기 정리 시각 | 03:30~05:30 윈도 | 기기 트리거 한계 |
| 24 | 동기화 단계 병렬화 | 안 함 (순차) | 13분 내 충분히 짧음 |

---

## 8. 시스템 성숙도 9점+ 도달 로드맵 (v1.1 신규)

> 사용자 정책: "해결 가능한 방안만". 단일 호스트 + 16GB + 가정용 위협 모델 한계 내 실현 가능한 개선만 도출.

### 8.1 신뢰성 (Reliability) 6 → 9

| 액션 | 구현 | 효과 |
|---|---|---|
| **CCC 주간 클론** | Carbon Copy Cloner 자동 실행 (외장 SSD) | SPOF RTO 4시간 |
| **마이그레이션 런북** | `runbooks/recover_on_new_mac.md` (체크리스트) | 다른 Mac에서 4시간 내 복구 |
| **Idempotency UNIQUE 제약** | 모든 photo_* 테이블 asset_id UNIQUE + UPSERT | 재실행 안전 |
| **Race condition advisory lock** | shared_event, ♥ vs cleanup, 모델 swap 진입 | 동시성 안전 |
| **Outbox pattern (단순 폴링)** | photo_outbox 테이블 + 1초 폴링 워커 | Layer 5 트랜잭션 일관성 |
| **Redis Streams 사진 변환 큐** | XADD/XREADGROUP, PEL로 미완료 추적 | At-least-once + backpressure |
| **주간 reconciliation job** | DB↔파일시스템 일치 검증 cron | 데이터 일관성 |
| **Retry · Circuit breaker** | Exponential backoff + jitter, 5회 실패 30분 차단 | 외부 장애 격리 |
| **Docker healthcheck** | 모든 컨테이너에 healthcheck 정의 | 자동 재시작 |
| **월간 chaos test** | 컨테이너 강제 종료 후 복구 검증 | 복원력 검증 |

**점수 산정**: 위 10개 모두 적용 시 SPOF 외 모든 차원 안전 → **9점**

---

### 8.2 확장성 (Scalability) 6 → 9

| 액션 | 구현 | 효과 |
|---|---|---|
| **Postgres 인덱스 전략** | photo_classification 4개 핵심 인덱스 | 수십만 row까지 응답 1초 이내 |
| **VACUUM ANALYZE 주간 cron** | autovacuum + 명시적 ANALYZE | 통계 최신화, 슬로우쿼리 방지 |
| **분류 로그 archiving** | 1년 경과 row → photo_classification_archive (월간) | 활성 테이블 작게 유지 |
| **자산 누적 KPI** | 월별 증가율 + 잔여 용량 예측 (Grafana 대시보드) | 사전 알림 |
| **HDD 용량 트리거 정의** | 80% 알림, 90% 차단, 95% 강제 archiving | 사용자 의사결정 시점 명확 |
| **LLM 모델 메모리 예산** | Ollama keep_alive 30분 + swap 정책 명시 | 16GB 한도 내 운영 |
| **HDD 확장 절차 문서화** | Phase 6 마이그레이션 절차 재사용 가능 명시 | 미래 2TB 전환 즉시 가능 |

**점수 산정**: 1TB 한도 내 효율화 + 미래 확장 절차 검증 완료 → **9점**

---

### 8.3 보안 (Security) 5 → 9

| 액션 | 구현 | 효과 |
|---|---|---|
| **`.env.gpg` 시크릿 관리** | gpg 암호화 git 추적, gpg-agent 부팅 복호화 | 토큰 노출 방지 |
| **Tailscale 토큰 분기 회전** | cron 자동화, 회전 후 헬스체크 | 토큰 유출 시 영향 최소 |
| **사용자 격리 E2E 테스트** | jw.son ↔ eunju 폴더 cross-access 차단 검증 | 권한 누수 방지 |
| **Image tag pinning** | docker-compose 모든 이미지 명시 버전 | 공급망 공격 방지 |
| **분기별 docker scan** | Trivy 또는 docker scout, CVE 검출 시 알림 | 의존성 취약점 |
| **분기별 pip-audit** | Python 의존성 취약점 | 동일 |
| **공식 이미지만 사용** | hub.docker.com 공식 organization만 | 공급망 신뢰 |
| **MacroDroid 권한 최소화** | DCIM 하위만 접근하도록 매크로 작성 | Galaxy 측 권한 누수 방지 |
| **Immich admin 비밀번호** | 16자+ 영숫자+특수문자, 분기 변경 | 무차별 대입 방지 |

**HDD 암호화 미도입 → 점수 영향**: 위협 모델상 가정용 물리 보안으로 충분 (집 내부 보관). 9점 도달 가능.

**점수 산정**: 9개 액션 모두 적용 시 가정용 위협 모델 대비 적절한 방어 → **9점**

---

### 8.4 관측성 (Observability) 4 → 9 ⭐ 가장 큰 향상

| 액션 | 구현 | 메모리 | 효과 |
|---|---|---|---|
| **Loki + Promtail 로그 통합** | 모든 컨테이너 로그 → Loki | ~300MB | 통합 검색 |
| **Grafana 대시보드** | 5개 대시보드 (시스템/사진/LLM/DB/사용자) | ~200MB | 시각화 |
| **JSON 표준 로그 형식** | `{ts, trace_id, asset_id, layer, severity, msg}` | 0 | 정형 검색 |
| **trace_id 전파** | 자산 1장의 8레이어 흐름 추적 가능 | 0 | 장애 추적 |
| **SLO 정의** | 분류 완료율 ≥ 99%, Layer 6 성공 ≥ 95%, ♥ 동기화 24h ≥ 100% | 0 | 운영 기준 |
| **알림 채널 다중화** | Telegram + Mac 푸시 노티 (terminal-notifier) | 0 | 채널 fail-over |
| **주간 리포트 자동화** | Grafana → 스크린샷 → Telegram | 0 | 운영 가시성 |
| **(선택) Prometheus + Node Exporter** | 시스템 메트릭 (CPU, mem, disk, net) | ~300MB | 추세 분석 |

**메모리 영향**: Loki(300) + Grafana(200) + Promtail(100) ≈ **600MB** (Prometheus 미도입 시)
- 16GB 한도 내 가능 (현재 LLM 5GB + 시스템 11GB → 11.6GB, 여유 4.4GB)

**점수 산정**: 8개 액션 적용 시 **9점** (10점은 distributed tracing 필요, 단일 호스트엔 과도)

---

### 8.5 테스트 (Testing) 3 → 9 ⭐⭐ 가장 큰 향상

| 액션 | 구현 | 효과 |
|---|---|---|
| **핵심 로직 Python 모듈 분리** | `pipeline/layer3_grade_decision.py` 등 | 단위 테스트 가능 |
| **pytest 단위 테스트** | Layer 3 점수 가산제, Layer 5 매칭, Layer 0.5 변환 | 회귀 방지 |
| **Golden dataset 100장** | jw.son 50 + eunju 50, 라벨링 (8등급) | 회귀 검증 |
| **CI 회귀 자동화** | Golden dataset 야간 cron 실행, 정확도 < 80% 알림 | 모델·로직 변경 검증 |
| **Smoke test (배포 후)** | 1장 분류 자동 실행, 결과 확인 | 배포 직후 검증 |
| **E2E 시나리오 테스트** | 촬영→삭제 흐름 시뮬레이션 (월간) | 통합 검증 |
| **모델 회귀 테스트** | Qwen 업데이트 시 golden dataset 비교 | 모델 안정성 |
| **DB schema migration 테스트** | Alembic + dry-run 환경 | 스키마 변경 안전 |
| **Property-based testing** | Hypothesis로 Layer 1 입력 다양성 | edge case 발굴 |

**점수 산정**: 9개 액션 적용 시 가정용 시스템에서 **9점** (10점은 mutation testing 필요)

---

### 8.6 운영성 (Operability) 6 → 9

| 액션 | 구현 | 효과 |
|---|---|---|
| **rollback.sh 스크립트** | 이미지 tag 기반 즉시 롤백 | 5분 이내 복구 |
| **Image tag pinning** | 모든 docker-compose 이미지 명시 버전 | 우발적 업그레이드 방지 |
| **Runbook 작성** | 장애 시나리오별 복구 절차 (5개) | 야간 장애 시 빠른 복구 |
| **DR 분기별 훈련** | TimeMachine 복원 + DB restore 검증 | 복구 검증 |
| **자동 헬스체크** | 모든 컨테이너 + 통합 모니터 | 자가 치유 |
| **주간 컨테이너 재시작** | 일요일 06:00 cron, 메모리 누수 방지 | 안정 가동 |
| **백업 검증 자동화** | 월간 임의 사진 1장 복원 테스트 | 백업 신뢰성 |
| **변경 관리 기록** | `CHANGELOG.md` + git tag 배포 시점 | 추적 가능 |
| **모델 업그레이드 절차** | golden dataset 비교 → 합격 시 신규 자산만 적용 | 모델 변경 안전 |

**점수 산정**: 9개 액션 적용 시 **9점**

---

### 8.7 9점+ 도달 로드맵 — Phase 매핑

각 액션을 사진 시스템 Phase에 매핑하여 점진 도입.

```
Phase 0/0-LLM 시작 전 (즉시, 1주)
  [신뢰성] CCC 주간 클론 자동화 설정
  [신뢰성] 마이그레이션 런북 작성
  [보안]   .env.gpg 도입 + gpg-agent 부팅 자동화
  [보안]   Image tag pinning (docker-compose 작성)
  [관측성] JSON 표준 로그 형식 정의
  [운영성] CHANGELOG.md + git tag 시작

Phase 1 (인프라 1~2일)
  [신뢰성] Redis Streams 사진 변환 큐 설계
  [신뢰성] Docker healthcheck 모든 컨테이너
  [관측성] ⭐ Loki + Promtail + Grafana 도입 (Phase 7 후 → Phase 1로 변경)
  [관측성] trace_id 전파 미들웨어
  [운영성] rollback.sh 스크립트
  [운영성] runbook 디렉토리 구조

Phase 2 (Immich 1일)
  [신뢰성] Postgres UNIQUE 제약 + idempotency
  [신뢰성] Advisory lock 패턴 정의
  [확장성] Postgres 인덱스 4개
  [보안]   Tailscale ACL + 토큰 회전 cron
  [보안]   Immich admin 강력 비밀번호

Phase 3 (원본 수집) 전
  [테스트] 핵심 로직 Python 모듈 분리
  [테스트] pytest 단위 테스트 (Layer 3)
  [테스트] Golden dataset 100장 라벨링
  [관측성] SLO 정의 + 대시보드 5개

Phase 4 dry-run 동시
  [신뢰성] Outbox pattern 구현 (Layer 5)
  [신뢰성] 주간 reconciliation job
  [신뢰성] Retry + Circuit breaker
  [테스트] CI 회귀 자동화 (golden dataset 야간)
  [테스트] Smoke test 자동화
  [운영성] 모델 업그레이드 절차 문서화

Phase 7 운영
  [신뢰성] 월간 chaos test
  [확장성] VACUUM ANALYZE 주간
  [확장성] 분류 로그 archiving 월간
  [보안]   분기별 docker scan + pip-audit
  [관측성] (선택) Prometheus + Node Exporter
  [테스트] E2E 시나리오 월간
  [테스트] DB schema migration 테스트
  [운영성] DR 분기 훈련
  [운영성] 백업 검증 자동화
```

### 8.8 메모리 영향 누적

```
v3.5 기본 운영 (사진 시스템)
  macOS + 시스템              4.0 GB
  트레이딩 (유휴)              1.5 GB
  Docker 베이스               1.5 GB
  Postgres + Redis × 2        2.3 GB
  Immich (4 컨테이너)          2.5 GB
  Ollama (Qwen-VL + Whisper)   5.0 GB
  Python + media-converter    1.0 GB
  ─────────────────────────────────
  소계                        17.8 GB ⚠️ 16GB 초과?

→ 실제로는 idle 상태에서 8~12GB 점유 (Ollama 5GB는 활성 시점만)
  야간 배치 시간대만 풀 가동, 평소엔 keep_alive 후 swap
```

**v1.1 개선 추가 메모리** (모두 도입 시)
```
Loki + Promtail              0.4 GB
Grafana                      0.2 GB
Prometheus + exporter (선택)  0.3 GB
헬스체크 daemon              <0.1 GB
─────────────────────────────────
관측성 추가                    0.7~1.0 GB
```

**결론**: 16GB 한도 내 가능 (야간 배치 시 12.5~13.5GB, 여유 2.5GB)

---

### 8.9 9점+ 달성 시 시스템 성숙도 종합

| 차원 | v1.0 | **v1.1** | 개선 폭 |
|---|---|---|---|
| 기능 완성도 | 9 | **9** | — |
| 신뢰성 | 6 | **9** | +3 |
| 확장성 | 6 | **9** | +3 |
| 보안 | 5 | **9** | +4 |
| 관측성 | 4 | **9** | +5 |
| 테스트 | 3 | **9** | +6 |
| 운영성 | 6 | **9** | +3 |
| **종합** | **5.6** | **9.0** | **+3.4** |

**가정용 시스템에서 도달 가능한 최고 수준 (9.0/10)**. 10점은 distributed system·mutation testing·formal verification 등 가정용에 과도한 요소 필요.

---

## 9. 코드 재사용·유지보수·공용 로직 평가 (v1.2 신규)

> 사용자 요청 (2026-04-30): "데이터 파이프라인과 코드 재사용 및 유지보수 면에서 잘되어 있는지, 공용로직으로 리팩토링 되도록 되어 있는지 검토"

### 9.1 평가 항목

| 항목 | 가중치 | 평가 방법 |
|---|---|---|
| **A. 데이터 파이프라인 품질** | 25% | DAG 명확성, 단계 결합도, 데이터 스키마 일관성 |
| **B. 코드 재사용성 (DRY)** | 25% | 공통 로직 식별, 중복 코드 비율, 추상화 수준 |
| **C. 유지보수성** | 25% | 변경 영향 범위, 모듈 경계, 의존성 방향 |
| **D. 공용 로직 리팩토링 준비도** | 25% | 추출 가능 로직 명세, 모듈 구조 설계 |

### 9.2 현재 설계 진단 (v3.5 기준)

#### A. 데이터 파이프라인 품질 — **8/10**

**강점**
- ✅ 단방향 흐름 (Layer 0 → 7) — DAG 구조 명확
- ✅ 단계별 책임 분리 (8레이어 + 영상 sub-layer)
- ✅ 트랜잭션 경계 명시 (Layer 0.5 변환, Layer 5 앨범)
- ✅ 모델 단일화 (Qwen2.5-VL 7B로 Layer 2/4/§15 통합)
- ✅ idempotency 정책 명시 (§20.3)
- ✅ 마이그레이션 vs 상시 = 같은 Layer 0.5~7 재사용

**약점**
- ⚠️ Layer 간 데이터 스키마 명세 부재 (input/output 타입 정의 없음)
- ⚠️ 영상 sub-pipeline (Layer 1.v1~v4)이 별도 분기로 명세, 이미지와 통합 인터페이스 부재
- ⚠️ 사용자 분기(jw.son/eunju/shared) 로직이 각 Layer에 산재

#### B. 코드 재사용성 — **5/10** ⚠️ 가장 큰 약점

**현재 상태 (설계 단계, 아직 구현 X)**
- n8n 워크플로우 7개에 비즈니스 로직 임베드 → 워크플로우 간 중복 가능성 매우 높음
- Python 모듈은 §2.F 권장으로만 언급, 구체 구조 미설계
- 공용 로직 분리 명시 부재

**중복 발생 예상 영역**
1. 사용자 분기 (Layer 0~7 모두 jw.son/eunju 분기)
2. Immich API 호출 (Layer 5, 6, 마이그레이션)
3. Ollama 호출 + 프롬프트 (Layer 2, 4, §15 7가지)
4. EXIF/GPS 추출 (Layer 0.5, 1, 2, 5)
5. DB CRUD (모든 Layer가 photo_classification 접근)
6. 에러 처리 + 알림 (모든 워크플로우)
7. 로깅 (분산)

→ 그대로 구현 시 동일 로직 5~10회 중복 가능성

#### C. 유지보수성 — **5/10**

**약점**
- n8n 워크플로우 = JSON → git diff 가독성 ↓, 코드 리뷰 어려움
- 변경 영향 범위 추적 불가 (예: 등급 기준 변경 시 어느 워크플로우 수정?)
- 단위 테스트 불가능 (n8n Function 노드 JS는 격리 어려움)
- 프롬프트 템플릿 위치 미정 (워크플로우 내부 하드코딩 위험)

**§8.5 테스트 9점 도달 위해서도 코드 분리 필수**

#### D. 공용 로직 리팩토링 준비도 — **3/10** ⚠️ 가장 큰 약점

- 현재 설계 문서에 공용 모듈 구조 미명세
- §2.F에서 "Python 모듈 분리" 언급만 있음
- 구체 모듈 경계, 의존성 방향, 인터페이스 정의 부재

### 9.3 종합 평가

| 항목 | 점수 | 진단 |
|---|---|---|
| A. 데이터 파이프라인 | 8/10 | DAG·트랜잭션 명확, 스키마 정의 보강 필요 |
| B. 코드 재사용성 | 5/10 | 중복 위험 ↑, 공용 로직 추출 필요 |
| C. 유지보수성 | 5/10 | n8n 의존, 단위 테스트 불가 |
| D. 리팩토링 준비도 | 3/10 | 모듈 구조 미설계 |
| **종합** | **5.25/10** | **Phase 1 시작 전 공용 모듈 구조 확정 필수** |

→ 현재 상태로 구현 시 운영 6개월 후 누적 부채 발생 위험 大. **사전 모듈 구조 설계 권장**.

---

### 9.4 권장 모듈 구조 (v3.5 → v3.6 코드 아키텍처)

```
photo-system/
├── core/                              ← 공용 모듈 (재사용 핵심)
│   ├── domain/                        ← 의존성 0 (가장 안쪽)
│   │   ├── user.py                    UserContext, UserResolver
│   │   ├── asset.py                   Asset, AssetType, parent_asset
│   │   ├── grade.py                   Grade enum (8단계), 점수 가산제
│   │   ├── classification.py          ClassificationResult
│   │   └── similarity.py              SimilarityGroup, CLIP cosine
│   │
│   ├── repository/                    ← DB 접근 표준 (Repository 패턴)
│   │   ├── classification_repo.py     photo_classification CRUD + UPSERT
│   │   ├── conversion_repo.py         photo_conversion_log
│   │   ├── feedback_repo.py
│   │   ├── queue_repo.py              cleanup_queue, cloud_sync_queue
│   │   ├── outbox_repo.py             Outbox pattern (Layer 5)
│   │   └── archive_repo.py            1년+ archiving
│   │
│   ├── client/                        ← 외부 시스템 wrapper
│   │   ├── immich_client.py           Immich API (assets, albums, exif)
│   │   ├── ollama_client.py           Ollama API + 프롬프트 로딩
│   │   ├── tailscale_client.py        ACL 관리
│   │   └── notifier.py                Telegram + Mac push 통합
│   │
│   ├── service/                       ← 도메인 로직
│   │   ├── metadata_service.py        EXIF/GPS/시각/timezone 추출·검증
│   │   ├── conversion_service.py      HEIC→JPEG, HEVC→H.264 (ffmpeg, sips)
│   │   ├── similarity_service.py      CLIP cosine, pHash, 그룹핑
│   │   ├── grading_service.py         8등급 판정 (점수 가산제)
│   │   ├── album_service.py           Immich 앨범 + 공유 EVENT 매칭
│   │   ├── storage_service.py         ⭐ HDD 등급 폴더 이동 + 뷰 심볼릭 (v1.4)
│   │   ├── cleanup_service.py         24h grace, cleanup_queue 관리
│   │   ├── cloud_sync_service.py      iCloud/Galaxy Cloud 검증
│   │   └── llm_service.py             Qwen2.5-VL 호출 추상 (§15 확장)
│   │
│   ├── pipeline/                      ← 8레이어 구현 (얇은 orchestration)
│   │   ├── layer0_upload.py           Immich Webhook 수신
│   │   ├── layer05_convert.py         미디어 변환 (conversion_service 호출)
│   │   ├── layer1_preprocess.py       전처리 (similarity_service)
│   │   ├── layer2_content.py          콘텐츠 분석 (llm_service)
│   │   ├── layer3_grade.py            등급 판정 (grading_service)
│   │   ├── layer4_local_llm.py        Vision 보조 (llm_service)
│   │   ├── layer5_album.py            앨범 배정 (album_service)
│   │   ├── layer6_cleanup.py          기기 정리 (cleanup_service)
│   │   └── layer7_feedback.py         검증 (cloud_sync_service)
│   │
│   ├── infra/                         ← cross-cutting (모두에서 사용)
│   │   ├── logger.py                  JSON 로그 + trace_id 전파
│   │   ├── error_handler.py           표준 에러 분류 (E_CONVERT_FAIL_DECODE 등)
│   │   ├── retry.py                   exp backoff + circuit breaker
│   │   ├── queue.py                   Redis Streams 추상
│   │   ├── lock.py                    Postgres advisory lock
│   │   ├── healthcheck.py             컨테이너 healthcheck
│   │   └── metrics.py                 Prometheus exporter (선택)
│   │
│   └── tests/
│       ├── unit/                      pytest 단위 테스트
│       ├── integration/               통합 테스트
│       ├── e2e/                       E2E 시나리오
│       └── golden/                    Golden dataset 100장
│
├── workflows/                         ← n8n orchestration ONLY (얇게)
│   ├── photo-1-upload.json            Webhook → core/pipeline 호출
│   ├── photo-2-convert.json
│   ├── photo-3-classify.json
│   ├── photo-4-vision.json
│   ├── photo-5-album.json
│   ├── photo-6-feedback.json
│   ├── photo-7-quarantine-purge.json
│   └── photo-error.json               표준 에러 핸들러
│
├── prompts/                           ← Qwen2.5-VL 프롬프트 (외부 파일)
│   ├── layer2_content_analysis.md
│   ├── layer4_classification.md
│   ├── ext_album_name.md              §15.1.A
│   ├── ext_kpi_summary.md             §15.1.B
│   ├── ext_telegram_query.md          §15.1.C
│   ├── ext_feedback_analysis.md       §15.1.D
│   ├── ext_caption.md                 §15.1.E
│   ├── ext_face_grouping.md           §15.1.F
│   └── ext_food_classification.md     §15.1.G
│
├── scripts/
│   ├── osxphotos_export.sh            Phase 3 마이그레이션
│   ├── galaxy_extract.sh
│   ├── migrate_paths.sh               Phase 6
│   ├── rollback.sh
│   ├── reconcile.sh                   주간 FS↔DB 검증
│   ├── deploy-verify.sh
│   └── ccc_clone.sh                   주간 시스템 클론
│
├── runbooks/                          ← 장애 복구 가이드
│   ├── recover_on_new_mac.md
│   ├── hdd_failure.md
│   ├── ssd_failure.md
│   ├── postgres_corruption.md
│   └── ollama_crash.md
│
├── docker-compose.yml
├── .env.gpg                           gpg 암호화 시크릿
├── .env.example                       placeholder
├── CHANGELOG.md
└── pyproject.toml                     Python 의존성·설정
```

### 9.5 의존성 방향 (Clean Architecture)

```
        ┌──────────────────┐
        │   workflows/     │  n8n (얇은 orchestration)
        └────────┬─────────┘
                 │
        ┌────────▼─────────┐
        │   pipeline/      │  Layer 0~7 구현
        └────────┬─────────┘
                 │
        ┌────────▼─────────┐
        │   service/       │  도메인 로직
        └────┬────────┬────┘
             │        │
        ┌────▼──┐ ┌──▼─────┐
        │ repo/ │ │ client/│  외부 어댑터
        └───┬───┘ └────────┘
            │
        ┌───▼──────────────┐
        │   domain/        │  순수 도메인 (의존 0)
        └──────────────────┘

        ┌──────────────────┐
        │   infra/         │  ← 모든 레이어에서 사용 (cross-cutting)
        └──────────────────┘
```

**규칙**
- domain은 다른 모듈을 import하지 않음
- service → domain, repository, client (단방향)
- pipeline → service만 호출 (repository 직접 호출 금지)
- workflows → pipeline만 호출 (얇게)
- infra (logger, error_handler, retry)는 모든 레이어에서 사용

---

### 9.6 공용 로직 추출 매트릭스

| # | 공용 로직 | 사용처 | 모듈 |
|---|---|---|---|
| 1 | UserContext (jw.son/eunju/shared 분기) | Layer 0~7, 마이그레이션, 큐 | `domain/user.py` |
| 2 | Grade 점수 가산제 (8등급 판정) | Layer 3, 4, 사용자 검토 | `domain/grade.py` + `service/grading_service.py` |
| 3 | EXIF/GPS 추출·검증 | Layer 0.5, 1, 2, 5 | `service/metadata_service.py` |
| 4 | 미디어 변환 (HEIC→JPEG, HEVC→H.264) | Layer 0.5 (마이그레이션 + 상시) | `service/conversion_service.py` |
| 5 | CLIP cosine 유사도 | Layer 1 | `service/similarity_service.py` |
| 6 | Qwen2.5-VL LLM 호출 + 프롬프트 | Layer 2, 4, §15 7가지 | `client/ollama_client.py` + `prompts/*.md` |
| 7 | Immich API (assets/albums/exif) | Layer 5, 6, 마이그레이션 | `client/immich_client.py` |
| 8 | DB CRUD (photo_classification 등) | 모든 Layer | `repository/*.py` |
| 9 | Outbox pattern | Layer 5 | `repository/outbox_repo.py` |
| 10 | Redis Streams 큐 | Layer 0.5, 5, 7 | `infra/queue.py` |
| 11 | Postgres advisory lock | shared_event, ♥ vs cleanup | `infra/lock.py` |
| 12 | Retry + Circuit breaker | 외부 호출 모두 | `infra/retry.py` |
| 13 | JSON 표준 로그 + trace_id | 모두 | `infra/logger.py` |
| 14 | 에러 분류·알림 | 모두 | `infra/error_handler.py` + `client/notifier.py` |
| 15 | 헬스체크 | 컨테이너별 | `infra/healthcheck.py` |
| 16 | Idempotency UPSERT 헬퍼 | Repository 레이어 | `repository/base.py` |

→ **16개 공용 로직 추출** 시 비즈니스 로직 중복 80% 이상 제거.

---

### 9.7 변경 영향 매트릭스 (유지보수성 검증)

리팩토링 후 가상 변경 시나리오의 영향 범위 시뮬레이션:

| 변경 | 영향 파일 (리팩토링 전) | 영향 파일 (리팩토링 후) |
|---|---|---|
| 새 등급 추가 (예: VIP) | n8n 7개 + DB schema + Telegram | `domain/grade.py` (1) + DB migration |
| 가족 멤버 1명 추가 | n8n 7개 + .env + 폴더 구조 + iOS Shortcut | `domain/user.py` (1) + .env.gpg |
| LLM 모델 교체 (Qwen → InternVL3) | n8n 2개 + 프롬프트 분산 | `client/ollama_client.py` (1) + tag pinning |
| 프롬프트 개선 (§15.1.A 앨범명) | n8n 1개 워크플로우 JSON | `prompts/ext_album_name.md` (1) |
| 새 Layer 추가 (예: Layer 8 자동 캡션) | n8n 1개 + DB | `pipeline/layer8_*.py` (1) + service |
| Immich API 버전업 | n8n 4~5개 분산 호출 | `client/immich_client.py` (1) |
| 변환 비트레이트 변경 | n8n 1개 | `service/conversion_service.py` (1) |

→ **변경 영향 범위 평균 5~10배 축소**. 유지보수성 9점+ 달성.

---

### 9.8 테스트 전략 — 모듈별 테스트 가능성

| 모듈 | 테스트 종류 | 도구 |
|---|---|---|
| `domain/*` | 순수 단위 테스트 (mock 0) | pytest |
| `service/*` | mock repository/client 단위 테스트 | pytest + unittest.mock |
| `repository/*` | DB 통합 테스트 (testcontainers) | pytest + testcontainers-postgres |
| `client/*` | mock HTTP (responses 라이브러리) | pytest + responses |
| `pipeline/*` | 통합 테스트 (mock service) | pytest |
| `workflows/*.json` | E2E 시나리오 | Playwright (Immich UI) + curl |
| Golden dataset | 회귀 테스트 야간 cron | pytest --golden |

→ **§8.5 테스트 9점 도달의 실질적 기반** = 이 모듈 구조.

---

### 9.9 마이그레이션 vs 상시 코드 재사용 (구체 예)

```python
# core/pipeline/layer05_convert.py — 단일 구현, 두 시나리오 모두 사용

from core.service.conversion_service import ConversionService
from core.service.metadata_service import MetadataService

class Layer05Convert:
    def __init__(self, conversion: ConversionService, metadata: MetadataService):
        self.conversion = conversion
        self.metadata = metadata

    def process(self, asset: Asset) -> ConversionResult:
        # 단일 자산 변환 — 마이그레이션도, 상시도 동일하게 호출
        ...

# 마이그레이션 (Phase 3)
# scripts/migrate_phase3.py
for asset in load_phase3_assets():  # 5만장 일괄
    layer05.process(asset)

# 상시 (Phase 4 이후, n8n Webhook 트리거)
# workflows/photo-2-convert.json → HTTP → Python:
def webhook_handler(asset_id):
    asset = repo.get(asset_id)
    layer05.process(asset)  # 같은 메서드
```

→ **두 시나리오가 동일 코드 재사용**, 분기는 데이터 레벨에서만.

---

### 9.10 §8 9.0/10 로드맵에 추가 액션 (코드 구조)

§8 로드맵에 추가:

```
Phase 0/0-LLM 시작 전 (1주, 추가)
  [구조] core/ 디렉토리 구조 생성 (16개 모듈 stub)
  [구조] domain/ 작성 (User, Asset, Grade, Classification)
  [구조] infra/logger.py + error_handler.py 작성
  [구조] pyproject.toml + 의존성 정의
  [구조] CI/CD (GitHub Actions) 기본 셋업

Phase 1 (인프라 1~2일, 추가)
  [구조] repository/* 작성 (5~6개)
  [구조] client/immich_client.py + ollama_client.py + notifier.py
  [구조] infra/queue.py (Redis Streams) + lock.py + retry.py
  [테스트] domain·repository 단위 테스트 (pytest)

Phase 2 (Immich 1일, 추가)
  [구조] service/* 작성 (8개)
  [테스트] service 단위 테스트 (mock repository/client)

Phase 3 (원본 수집) 전, 추가
  [구조] pipeline/* 작성 (9개 Layer)
  [구조] prompts/* 작성 (9개 프롬프트 템플릿)
  [구조] workflows/*.json 작성 (얇게, Python 호출만)
  [테스트] integration test (testcontainers)

Phase 4 dry-run, 추가
  [테스트] golden dataset 100장 라벨링 + CI 회귀
  [테스트] E2E 시나리오 1개 (촬영→삭제)
```

---

### 9.11 코드 구조 평가 종합 점수 (리팩토링 후 예상)

| 항목 | 현재 (v3.5) | **리팩토링 후 (v3.6)** |
|---|---|---|
| A. 데이터 파이프라인 | 8/10 | **9/10** (스키마 명세 + 인터페이스 통일) |
| B. 코드 재사용성 | 5/10 | **9/10** (16개 공용 로직 추출) |
| C. 유지보수성 | 5/10 | **9/10** (변경 영향 범위 5~10배 축소) |
| D. 리팩토링 준비도 | 3/10 | **9/10** (모듈 구조 명확) |
| **종합** | **5.25/10** | **9.0/10** |

---

### 9.12 결론·권고

**현재 상태 (v3.5)**: 5.25/10 — 데이터 파이프라인은 양호하나 코드 재사용·리팩토링 준비도 미흡.

**권고**: **Phase 1 시작 전 §9.4 모듈 구조 확정**. 이를 시스템 성숙도 9.0/10 로드맵 (§8) 의 사전 작업으로 포함.

**위험**: 모듈 구조 없이 Phase 1~4 진행 시 6개월 후 비즈니스 로직 중복 누적 → 등급 추가·LLM 교체·프롬프트 개선 등 변경 비용 5~10배 증가.

**추가 의사결정 필요**:

| # | 항목 | 옵션 | 권장 |
|---|---|---|---|
| 9 | 코드 모듈 구조 | §9.4 채택 / 단순 디렉토리 / 미정 | **§9.4 채택** |
| 10 | Python 패키지 도구 | poetry / pip-tools / hatch | **poetry** (의존성 lock + venv 통합) |
| 11 | 코드 스타일 | black / ruff / 미정 | **ruff** (lint + format 통합, 빠름) |
| 12 | 프롬프트 외부화 | `prompts/*.md` / DB / 코드 hardcode | **`prompts/*.md`** (git diff 가능) |
| 13 | n8n 워크플로우 두께 | 얇게 (Python 호출) / 두껍게 (로직 포함) | **얇게** (orchestration only) |
| 14 | CI/CD 도구 | GitHub Actions / 자체 cron / 미정 | **GitHub Actions** (외부 의존 최소, free tier) |

---

*이 보고서는 v1.4 FINAL. Phase 1 시작 후 실제 구현 review로 v1.5 또는 v2.0 갱신 예정.*
*평가 기준 출처: 설계 문서 v3.7, LLM 평가 v1.3*
