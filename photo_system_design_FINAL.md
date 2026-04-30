# M4 맥미니 사진 자동화 시스템
### 설계 의도 및 전체 흐름 정의서
> v2.0 FINAL | 2026년 4월

---

## 1. 핵심 의도

이 시스템의 목적은 하나다. 사진을 찍으면 사람이 아무것도 하지 않아도 아침에 일어났을 때 정리가 완료되어 있는 것.

**구체적으로 원하는 최종 상태**

- jw.son (iPhone) · eunju (Galaxy) 각자의 사진을 독립된 폴더로 관리
- 각 기기의 사진첩에는 EVENT + BEST + 즐겨찾기만 남아있음
- 같은 행사에서 찍은 사진은 공유 EVENT 앨범으로 자동 통합
- 나머지 원본은 모두 HDD 서버에 보관되어 Immich 앱으로 언제든 열람 가능
- 사람이 개입하지 않아도 분류·정리·삭제가 자동으로 완료됨
- 트레이딩 시스템과 완전히 분리되어 리소스 충돌 없음

**핵심 원칙**

- 원본은 절대 버리지 않는다 — 판단이 틀려도 HDD에서 꺼내면 됨
- TRASH도 30일간 HDD 보관 후 삭제
- iPhone에서 삭제해도 Immich 앱에서 원본 스트리밍으로 열람 가능
- Claude Vision API는 최소화 — 월 $1 미만 목표

---

## 2. 하드웨어 구성

> M4 Mac mini 512GB SSD + External HDD 1TB (USB3) + iCloud 50GB

| 위치 | 역할 |
|------|------|
| **SSD 512GB** (맥미니 내장) | macOS + 앱 · Docker 엔진 전체 · PostgreSQL (트레이딩 + Immich) · Redis · Immich 썸네일·캐시 · Ollama 모델 파일 (Moondream2, Whisper) |
| **HDD 1TB** (External USB3) | `/immich-media/jw.son/` → jw.son 원본 사진·영상 · `/immich-media/eunju/` → eunju 원본 · `/immich-media/shared/` → 공유 EVENT 원본 |
| **iCloud 50GB** | EVENT + BEST + 즐겨찾기 등급만 선택 보관 · jw.son · eunju 각자 iCloud 계정 유지 |

---

## 3. 사용자 구성 및 폴더 구조

두 사용자가 동일한 Immich 서버를 사용하되 완전히 독립된 공간으로 관리된다. 로직·파이프라인은 공유하고 저장 경로만 분기한다.

| 항목 | jw.son | eunju | 공유 |
|------|--------|-------|------|
| 기기 | iPhone | Galaxy | — |
| HDD 폴더 | `/immich-media/jw.son/` | `/immich-media/eunju/` | `/immich-media/shared/` |
| Immich 계정 | jw.son 계정 | eunju 계정 | 공유 앨범 (두 계정 모두 접근) |
| 앨범 구성 | EVENT / EVENT-L / BEST / FOOD / MEMORY+ / MEMORY- / NORMAL / ♥ 즐겨찾기 | 동일 | 공유 EVENT 앨범 |
| iCloud 백업 | jw.son iCloud · EVENT+BEST+즐겨찾기 | eunju iCloud/Google · EVENT+BEST+즐겨찾기 | — |
| 기기 정리 | iOS Shortcut 자동 실행 | Android 자동화 앱 실행 | — |

### 공유 EVENT 앨범 자동 생성 조건

두 사용자의 사진이 아래 조건을 모두 충족하면 공유 EVENT 앨범을 자동 생성한다.

- 촬영 시간 차이 2시간 이내
- GPS 위치 반경 500m 이내
- 두 사진 모두 EVENT 등급 판정
- 앨범명: 날짜 + 장소 자동 생성 (예: `2026-04-29 강남구 행사`)
- 두 Immich 계정 모두에서 접근 가능

---

## 4. 분류 등급 (8단계) + 즐겨찾기

모든 사진·영상은 아래 8개 등급 중 하나로 자동 분류된다. 음식은 별도 파이프라인으로 분기되며, 즐겨찾기는 등급과 독립적인 레이어다.

| 등급 | 기준 | 백업 위치 | iPhone 보관 | 즐겨찾기 |
|------|------|-----------|-------------|----------|
| ⭐ **EVENT** | 행사·기념일 + 다양성 기준 선발 고품질 | iCloud + HDD | ✅ 유지 | ♥ 가능 |
| ⭐ **EVENT-L** | 행사·기념일 + 유사컷 내 상대적 저품질 | HDD | ❌ 삭제 | ♥ 가능 |
| ✦ **BEST** | 일반 장면 다양성 기준 선발 (MEMORY+·MEMORY-·NORMAL 전체 최고컷) | iCloud + HDD | ✅ 유지 | ♥ 가능 |
| 🍽 **FOOD** | 음식 베스트컷 (유사도 80% 기준 중복 제거 후 선발) | HDD | ❌ 삭제 | ♥ 가능 |
| ◆ **MEMORY+** | 사람·장면 있음 + 품질 양호 (BEST 탈락) | HDD | ❌ 삭제 | ♥ 가능 |
| ◇ **MEMORY-** | 사람·장면 있음 + 품질 낮음 (BEST 탈락) | HDD | ❌ 삭제 | ♥ 가능 |
| ○ **NORMAL** | 사람 없음·풍경·사물 (BEST 탈락) | HDD | ❌ 삭제 | ♥ 가능 |
| 🗑 **TRASH** | 흐림 심함·스크린샷·중복 탈락·음식 중복 | 30일 후 삭제 | ❌ 삭제 | — |

### EVENT · BEST 유사컷 처리 원칙 (동일 알고리즘, 임계값만 다름)

EVENT와 BEST는 동일한 다양성 기준을 적용하되, EVENT는 임계값을 더 여유있게 설정해 행사 사진을 더 많이 보관한다.

**공통 알고리즘**
- 구도·표정·배경이 다르면 각각 별도 보관 (상한 없음)
- 유사도가 임계값 이상 → 품질 낮은 쪽 강등 (중복 제거)
- 원본은 모두 HDD에 보관

**임계값 차이**
- `EVENT` — 유사도 **95%** 이상일 때만 강등 → 조금만 달라도 보관 (여유)
- `BEST`  — 유사도 **90%** 이상이면 강등 → 더 엄격하게 중복 제거

**예시**
- 행사에서 거의 같은 구도 5연사 (유사도 92%) → EVENT는 모두 보관, BEST는 1장만
- 행사에서 표정만 조금 다른 2컷 (유사도 97%) → EVENT·BEST 모두 1장만
- 배경·구도 다른 3컷 (유사도 70%) → EVENT·BEST 모두 3장 보관

### EVENT 자동 판정 기준

아래 조건 중 2개 이상 충족 시 자동으로 EVENT 등급 배정 (사용자 승인 불필요)

- 얼굴 3명 이상 감지
- 공식 복장 (정장·드레스·한복) 감지
- 행사 오브젝트 (케이크·꽃다발·무대) 감지
- 흐림 점수 상위 20% (고품질)
- 음성 키워드 감지: 생일 축하·건배·박수·사랑해 (영상)

### 🍽 FOOD 등급 처리 원칙

음식은 Layer 2에서 감지 즉시 일반 파이프라인과 분리되어 별도 로직으로 처리된다.

- 음식 감지 → 유사도 80% 이상 → TRASH (같은 음식 여러 컷 적극 제거)
- 음식 감지 → 유사도 80% 미만 → FOOD 등급, HDD 전용 보관
- iCloud 백업 없음, iPhone 삭제
- Immich 내 FOOD 앨범 자동 생성 — 날짜별로 열람 가능
- 즐겨찾기 지정 시 iCloud로 승격 가능

### ♥ 즐겨찾기 동작 방식

즐겨찾기는 8단계 자동 분류와 완전히 독립적인 수동 큐레이션 레이어다.

- Immich 앱에서 사진·영상을 꾹 누르면 ♥ 즐겨찾기 지정 가능
- 어떤 등급이든 즐겨찾기 지정 시 → iCloud + HDD로 자동 승격
- iPhone 사진첩에서 삭제된 사진도 즐겨찾기하면 iCloud에 다시 백업됨
- iPhone·Galaxy·맥·웹 전체 실시간 동기화

**백업 우선순위**

```
EVENT / BEST         → 자동으로 iCloud + HDD
즐겨찾기 지정         → 등급 무관하게 iCloud + HDD 승격
FOOD / MEMORY / NORMAL → HDD만
TRASH                → 30일 후 삭제
```

---

## 5. 전체 파이프라인 (7레이어)

로직·파이프라인은 두 사용자 공유. 저장 경로만 마지막에 분기.

| 레이어 | 단계 | 처리 내용 | 기술 스택 |
|--------|------|-----------|-----------|
| **Layer 0** | 업로드 | jw.son · eunju → Immich 자동 백업 (Wi-Fi) · 공유 파이프라인 처리 · 저장 경로만 분기 | Immich 앱 |
| **Layer 1** | 전처리 | 흐림·노출 점수 측정 · 스크린샷 판별 · 유사컷 그룹핑 · 영상: 길이·흔들림·무음 판별 · 동일 시간대·위치로 공유 행사 감지 | OpenCV · Python · ffprobe |
| **Layer 2** | 콘텐츠 분석 | 사람 수·얼굴 여부 · 장면 유형 (행사/일상/풍경/음식) · 음식 감지 시 FOOD 파이프라인 분기 · 공식 복장·행사 오브젝트 감지 · 영상: 대표 프레임 추출 후 분석 · 음성→텍스트 변환 후 키워드 감지 | Moondream2 · Ollama · Whisper |
| **Layer 3** | 등급 자동 판정 | [음식] 유사도 80% 이상 → TRASH / 미만 → FOOD · [행사] 다양성 선발 고품질 → EVENT · 저품질 탈락 → EVENT-L · 유사도 95% 이상 강등 · [일반] 다양성 선발 → BEST · 유사도 90% 이상 강등 · 탈락 → MEMORY+/MEMORY-/NORMAL · 공유 행사 감지 → 공유 EVENT 앨범 생성 | n8n 워크플로우 |
| **Layer 4** | 보조 판단 | 하루 1회 새벽 배치 · 애매한 이미지·영상만 묶어서 1회 호출 · 예상 비용: 월 $0.2~0.8 | Claude Vision API |
| **Layer 5** | 앨범 자동 배정 | 판정 결과 → 사용자별 Immich 앨범 배정 · 공유 행사 → 공유 EVENT 앨범 생성 · 분류 로그 → PostgreSQL (user 컬럼 포함) · TRASH → 30일 후 삭제 · 기기 삭제 대상 목록 DB 저장 | Immich API · PostgreSQL |
| **Layer 6** | 기기 정리 | jw.son: 새벽 충전 중 iOS Shortcut 자동 실행 · eunju: Android 자동화 앱 실행 · n8n API → 사용자별 삭제 목록 수신 · EVENT + BEST + 즐겨찾기 외 기기에서 제거 | iOS Shortcuts · Android 자동화 · n8n Webhook |

### 영상 분석 특이사항

- 3초 미만 영상 → 즉시 TRASH (실수로 찍은 것)
- 5초마다 대표 프레임 추출 → 이미지처럼 Moondream2 분석 (전체 분석 불필요)
- Whisper로 음성→텍스트 변환 후 키워드 감지 → EVENT 판정 정확도 향상
- 30초 영상 1개 기준 처리 시간: ~9초 (야간 배치로 충분)

---

## 6. 실행 스케줄

| 시간 | 작업 |
|------|------|
| 상시 | iPhone/Galaxy → Immich 업로드 (Layer 0) |
| 16:00~ | 이미지·영상 분류 파이프라인 실행 (Layer 1~3) · 트레이딩 장 마감 후 실행으로 리소스 충돌 없음 |
| 새벽 03:00 | Claude Vision 배치 호출 (Layer 4, 애매한 것만) |
| 새벽 03:30 | Immich 앨범 배정 · DB 기록 완료 (Layer 5) |
| 새벽 충전 중 | iOS Shortcut / Android 자동화 실행 → EVENT+BEST+즐겨찾기 외 삭제 (Layer 6) |
| 아침 기상 시 | Telegram: `jw.son 45장·eunju 38장 → 각각 유지 N장 / HDD 보관 K장` 요약 수신 |

**사용자 최종 경험**

아무것도 안 해도 아침에 일어나면:
- jw.son iPhone 사진첩: EVENT + BEST + 즐겨찾기만 남아있음
- eunju Galaxy 갤러리: EVENT + BEST + 즐겨찾기만 남아있음
- Immich 앱: 각자 폴더에 전체 원본 8등급으로 정리됨
- 공유 행사가 있으면 공유 EVENT 앨범 자동 생성됨

---

## 7. Docker 서비스 구성

| 컨테이너 | 역할 | 비고 |
|----------|------|------|
| n8n | 트레이딩 워크플로우 13개 + 이미지 분류 워크플로우 | 기존 유지 + 확장 |
| PostgreSQL | 트레이딩 DB + 분류 로그 테이블 | 기존 유지 + 확장 |
| Redis | 캐시 | 기존 유지 |
| immich-server | 사진 서버 · iPhone/Galaxy 자동 백업 수신 | 신규 |
| immich-ml | 얼굴 인식 · CLIP 임베딩 · 유사도 | 신규 |
| immich-postgres | Immich 전용 DB | 신규 |
| immich-redis | Immich 전용 캐시 | 신규 |
| Ollama | Moondream2 + Whisper 로컬 모델 서빙 | 신규 (~2.3GB) |
| Python | OpenCV 품질 분석 · ffprobe 영상 분석 · 분류 로직 | 신규 (~0.5GB) |

**메모리 예상 (야간 분류 실행 기준)**

```
macOS                         3~4 GB
트레이딩 시스템 (유휴)          1~2 GB
Immich                        2~3 GB
Ollama (Moondream2 + Whisper)  ~2.3 GB
Python 컨테이너                ~0.5 GB
─────────────────────────────────────
합계                          9~12 GB  ✅ 16GB 이내
```

---

## 8. Immich 앱 접근 및 즐겨찾기 동기화

iPhone에서 삭제된 사진도 Immich 앱에서 원본 스트리밍으로 열람 가능하다. 넷플릭스처럼 서버에서 불러오는 구조이므로 iPhone 저장공간을 사용하지 않는다.

- **집 안** (같은 Wi-Fi): 맥미니 직접 연결 → 빠름
- **집 밖** (외부망): Tailscale VPN → 맥미니 → HDD 원본 스트리밍
- 각자 계정으로 로그인 → 본인 폴더만 기본 보기, 공유 앨범은 두 계정 모두 접근
- 앨범별 보기: EVENT / EVENT-L / BEST / FOOD / MEMORY+ / MEMORY- / NORMAL / ♥ 즐겨찾기 / 공유 EVENT
- 즐겨찾기 지정 즉시 iCloud 백업 트리거 → n8n Webhook으로 처리
- 지도뷰 · 얼굴 인식 · 자연어 검색 ("바다에서 찍은 사진"): 기본 제공

---

## 9. 구축 순서

| 단계 | 이름 | 주요 작업 |
|------|------|-----------|
| **Phase 1** | 기반 인프라 | HDD APFS 포맷·마운트 고정 · Docker File Sharing 경로 추가 · Mac 슬립 방지·자동시작 설정 |
| **Phase 2** | Immich 설치 | docker-compose에 Immich 4개 서비스 추가 · UPLOAD_LOCATION → HDD 경로 지정 · iPhone/Galaxy 자동 백업 연결 · Tailscale 외부 접근 설정 |
| **Phase 3** | iCloud 전환 | 원본 전체 다운로드 → HDD 이동 · iCloud 사진 동기화 OFF · 요금제 50GB 다운그레이드 |
| **Phase 4** | 분류 자동화 | Ollama·Python 컨테이너 추가 · OpenCV 품질 분석·ffprobe 영상 분석 구현 · Moondream2·Whisper 연동 · n8n 분류 워크플로우 구성 · Immich API 앨범 자동 배정 · iOS Shortcut / Android 자동화 구성 |

---

## 10. 기존 트레이딩 시스템 영향

이미지 분류 시스템은 트레이딩 시스템과 완전히 독립적으로 운영된다.

- ✅ 유지: 트레이딩 n8n 워크플로우 13개 전체
- ✅ 유지: PostgreSQL·Redis 기존 구성 및 트레이딩 DB 스키마
- ✅ 유지: 트레이딩 Telegram 봇 및 승인 구조
- ➕ 추가: docker-compose에 Immich 4개 서비스
- ➕ 추가: Ollama·Python 컨테이너 (Phase 4)
- ➕ 추가: n8n 이미지 분류 워크플로우 (트레이딩 워크플로우와 별개)
- ➕ 추가: 분류 로그 테이블 (기존 PostgreSQL에 테이블만 추가)

> 트레이딩 장중 시간 (09:00~15:30)에는 분류 파이프라인을 실행하지 않아 리소스 충돌이 없다.

---

*이 문서는 Phase 4 세부 설계의 기준 문서입니다. v2.0 FINAL*
