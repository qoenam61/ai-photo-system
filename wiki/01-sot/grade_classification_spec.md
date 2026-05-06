# 사진·영상 등급 분류 상세 기준 (SSoT)

> **사용자 명시 정정 (2026-05-06)**: 분류 정확도 향상을 위한 세부 기준 + 경계 케이스 명세.
> 이 문서가 LLM PROMPT, classifier.py, CLAUDE.md의 single source of truth.

---

## 0. 분류 결정 우선순위 (최상위 룰)

```
입력 자산 → ↓ 위에서 아래로 평가
─────────────────────────────────────────────
1. 영상이며 duration < 3초          → TRASH (auto_short_video)
2. 영상이며 duration ≥ 3초          → EVENT-L (auto_video) — Long
3. 이미지 LLM 호출 (Groq → Qwen fallback)
   ├─ LLM=TRASH                     → TRASH
   ├─ LLM=FOOD                      → FOOD
   ├─ LLM=EVENT (얼굴 명확 + 행사)   → EVENT
   ├─ LLM=BEST                      → BEST
   └─ LLM 실패 → ↓ auto signals fallback
4. is_screenshot (face=0+camera=∅+종횡비) → TRASH
5. face_count > 0
   ├─ laplacian < 100               → MEMORY-
   └─ laplacian ≥ 100               → MEMORY+
6. face_count = 0
   ├─ camera_make 있음               → NORMAL
   └─ camera_make 없음               → TRASH
```

**절대 룰 (모든 등급 진입 전 적용)**:
- 사람 등장 시 **얼굴이 명확히 식별 가능**해야 EVENT/BEST/MEMORY+ 진입 (사용자 명시 2026-05-05)
- 부분 신체(다리/뒷모습/잘림) → 행사 컨텍스트여도 TRASH
- 단순 흐림(약간 초점 안 맞음)은 TRASH 아님 → MEMORY-/BEST/EVENT 보존

---

## 1. BEST — 보존 가치 높은 일반 컷

### 진입 조건 (모두 만족)
- LLM=BEST 응답 OR 풍경/사물/동물 단독 좋은 컷
- 노출·초점·구도 적정
- (사람 등장 시) 얼굴 1명 이상 명확히 식별 가능

### 세분화
| 서브 카테고리 | 기준 |
|---|---|
| 인물 BEST | 얼굴 명확 1-2명, 자연스러운 일상 (행사 키워드 X) |
| 풍경 BEST | 자연 풍경·도시·여행지, 사람 비중 < 20% |
| 사물 BEST | 의미 있는 사물 클로즈업 (꽃·작품·기념품 등) |
| 동물 BEST | 반려동물·야생동물 명확한 컷 |

### 제외 (BEST 아님)
- 사람 있지만 얼굴 보임 X → TRASH
- 음식 50%+ → FOOD
- 행사 컨텍스트(웨딩·돌잔치) → EVENT
- 흐림 심함(lap<30) → TRASH
- 약간 흐림(30≤lap<100) + 사람 → MEMORY-

### iCloud 정책
- ✅ Mac 앨범 → iCloud → iPhone 동기

---

## 2. EVENT — 행사·이벤트 사진 (얼굴 명확 필수)

### 진입 조건 (둘 중 하나)
- **A. 얼굴 명확한 사람 3명 이상** (단체 사진)
- **B. 얼굴 명확한 사람 + 행사 키워드** (1인 행사 사진도 가능)

### 행사 키워드 (LLM 인식 대상)
- 결혼/웨딩: 드레스·턱시도·한복·웨딩홀·꽃다발·신부 부케·웨딩 케이크
- 돌잔치: 돌상·돌띠·한복·돌잡이 도구
- 생일: 생일 케이크·고깔모자·풍선·"HAPPY BIRTHDAY" 장식
- 졸업: 학사모·가운·졸업장
- 기념일: 100일·돌·만삭·신생아·칠순·제사상
- 가족 행사: 가족스튜디오·가족 모임·명절 한복

### 세분화
| 서브 카테고리 | 기준 |
|---|---|
| 단체 EVENT | 얼굴 명확 3+ |
| 행사 1인 EVENT | 얼굴 명확 1-2명 + 행사 키워드 명백 |
| 가족 EVENT | 가족 단위 + 행사 컨텍스트 |

### 제외 (EVENT 아님)
- 행사장이지만 얼굴 안 보임 (다리·뒷모습·먼 거리 군중) → **TRASH**
- 음식 사진 (행사 음식 포함) → FOOD
- 행사 영상 ≥ 3초 → EVENT-L
- 사람 1-2명 + 행사 키워드 X → BEST 또는 MEMORY+

### iCloud 정책
- ✅ Mac 앨범 → iCloud → iPhone

---

## 3. EVENT-L — Long (행사 영상·dedup 강등)

### 진입 조건 (둘 중 하나)
- **A. 영상 ≥ 3초** (`auto_video`) — 모든 영상 자산
- **B. dedup 강등** (`dedup_demoted_5s`) — 5초 burst에서 베스트컷 외 사본
  - BEST/EVENT 계열 burst의 quality 1위 외 자산이 EVENT-L로 강등

### 명칭 주의
- **L = Long** (영상 길이 / dedup 보관용 long-form)
- L ≠ Low (저품질 아님 — iCloud 백업 가치 있음)

### 세분화
| 서브 카테고리 | 기준 |
|---|---|
| EVENT-L 영상 | 영상 ≥ 3초 (`auto_video`) |
| EVENT-L dedup | EVENT/BEST burst 강등 (`dedup_demoted_5s`) |
| EVENT-L 환원 | 사용자 환원 자산 (`restored_from_dedup`) |

### 제외 (EVENT-L 아님)
- 영상 < 3초 → TRASH (`auto_short_video`)

### iCloud 정책
- ✅ Mac 앨범 → iCloud → iPhone (결혼식 본식 영상 등 보존 가치)

---

## 4. FOOD — 음식 사진

### 진입 조건
- **음식이 화면 50% 이상**

### 세분화 (food_categorizer.py 활용)
| 서브 | 기준 |
|---|---|
| 한식 | 한식 카테고리 |
| 양식 | 양식·이탈리안·디저트 |
| 일식·중식 | 동아시아 |
| 음료/디저트 | 커피·케이크·과일 |

### 제외 (FOOD 아님)
- 음식 < 50% (인물 비중 큼) → 인물 우선 (BEST/EVENT/MEMORY+)
- 식당 분위기 사진 (음식 X) → BEST 또는 NORMAL
- 행사 케이크 컷 + 사람 얼굴 명확 → EVENT (행사 키워드 우선)

### iCloud 정책
- ❌ HDD 보존 only (사용자 명시 — iCloud 50GB 한도 절감)

---

## 5. MEMORY+ — 추억 (사람 + 화질 OK)

### 진입 조건 (자동 신호 fallback — LLM 미응답 시)
- `face_count > 0` (OpenCV haarcascade frontal face)
- `laplacian_variance ≥ 100` (선명)
- 행사 키워드 X (있으면 EVENT)
- 사람 3+ X (있으면 EVENT)

### 5초 burst 강등 진입
- BEST → MEMORY+ (베스트컷 외 secondary)
- EVENT-L → MEMORY+ (long-form secondary)

### 세분화
| 서브 | 기준 |
|---|---|
| 일상 인물 | 얼굴 1-2명 + 자연스러운 일상 |
| 가족 셀카 | 가족 모임 + 행사 키워드 X |
| 친구·연인 | 인물 위주 일상 |

### 제외 (MEMORY+ 아님)
- 흐림 심함 (lap<100) → MEMORY-
- 행사 키워드 + 얼굴 명확 → EVENT
- 사람 없음 → NORMAL

### iCloud 정책
- ✅ Mac 앨범 → iCloud → iPhone

---

## 6. MEMORY- — 추억 (사람 + 흐림)

### 진입 조건
- `face_count > 0`
- `laplacian_variance < 100` (흐림 — 약간 초점 안 맞음 포함)
- **단순 흐림 보존 — TRASH 아님**

### 5초 burst 강등 진입
- MEMORY+ → MEMORY- (베스트컷 외 secondary)
- FOOD → MEMORY- (음식 burst 강등)

### 제외 (MEMORY- 아님)
- 완전 흐림 (lap < 30) + 피사체 식별 불가 → TRASH
- 선명 (lap ≥ 100) → MEMORY+

### iCloud 정책
- ❌ HDD 보존 only

---

## 7. NORMAL — 사람 없는 카메라 사진

### 진입 조건
- `face_count = 0`
- `camera_make` 있음 (EXIF 카메라 메타데이터 존재)
- 풍경·사물·동물 (BEST 수준은 아님)
- LLM=BEST 미해당

### 5초 burst 강등 진입
- MEMORY- → NORMAL (흐림 burst 강등)

### 제외 (NORMAL 아님)
- 사람 있음 (face>0) → MEMORY+/MEMORY-
- LLM이 BEST 판정 → BEST
- 카메라 메타 없음 + 사람 없음 → TRASH (스크린샷 후보)

### iCloud 정책
- ❌ HDD 보존 only

---

## 8. TRASH — 의미 없는 사진 + 중복 + 얼굴 미가시

### 진입 조건 (셋 중 하나)

#### 8.1 의미 없는 사진
- UI 스크린샷 (메신저·웹·앱 화면 캡처)
- 완전 흑백/단색 화면
- 초점 완전 나감 (laplacian < 30, 피사체 식별 불가)
- 바닥·벽·천장만 (피사체 없음)
- 잘못 촬영 (손가락 가림, 심한 흔들림, 노출 완전 실패)
- 매우 짧거나 잘못 찍힌 영상 (< 3초)

#### 8.2 중복 사진 (dedup) — 별도 처리
- 같은 5초·같은 카메라 burst의 quality rank 2+ → **하위등급 강등 (TRASH 아님)**
- TRASH 직접 강등은 1초 정책 시절 잔재 (현재 미사용)

#### 8.3 얼굴 안 보이는 사람 사진 (사용자 명시 2026-05-05)
- 다리만/발만/손만 보이는 부분 신체 컷
- 뒷모습만 (얼굴 측면도 안 보임)
- 얼굴이 잘리거나 가려져서 인물 식별 불가
- 멀리 있어서 얼굴이 픽셀 단위로 작아 식별 불가
- **행사 컨텍스트(웨딩·돌잔치 등)여도 얼굴 안 보이면 TRASH**

### 보존선 (TRASH 아님)
- 단순 흐림 (lap 30~99) → MEMORY-/BEST/EVENT
- 정상 노출·구도 + 얼굴 보임 → MEMORY+/EVENT/BEST
- dedup_demoted_* 자산 → 하위등급 보관 (HDD 영구 보존)

### iCloud 정책
- ❌ Mac 정리 대상 (`cleanup_photos_mac.py` 별도 처리)
- HDD 7일 grace 후 영구 삭제 (사용자 자동 승인 시 즉시)

---

## 9. 경계 케이스 (Edge Cases)

| 케이스 | 결정 |
|---|---|
| 웨딩 사진 + 신부 뒷모습만 | **TRASH** (얼굴 미가시 우선) |
| 웨딩 사진 + 손가락 가림 | **TRASH** (잘못 촬영) |
| 웨딩 사진 + 신부 멀리, 얼굴 작음 | **TRASH** (식별 불가) |
| 웨딩 사진 + 신부+신랑 얼굴 명확 | **EVENT** |
| 음식 + 사람 얼굴 큰 비중 | **MEMORY+/EVENT** (인물 우선) |
| 음식 + 행사 케이크 + 가족 얼굴 | **EVENT** (행사 키워드 우선) |
| 풍경 + 행사 키워드 X + 사람 X | **NORMAL** (또는 BEST if 좋은 컷) |
| 풍경 + LLM=BEST 명시 | **BEST** |
| 단색 모니터 사진 | **TRASH** (UI 스크린샷) |
| 흑백 필터 사진 + 인물 명확 | **MEMORY+/BEST** (필터는 의미 있는 사진) |
| 영상 2초 결혼식 본식 | **TRASH** (auto_short_video — 사용자 명시 3초 임계) |
| 영상 5초 결혼식 본식 | **EVENT-L** (auto_video) |
| 비디오 (mov/mp4) duration NULL | classify_video이 ffprobe 실패 — 재측정 필요 |
| 햄버거 사진 + 손에 들고 셀카 | **MEMORY+/EVENT** (얼굴 우선 if 명확) |
| 프로필 셀카 + 정면 | **BEST** (LLM 판정) |
| 단체 사진에서 1명만 얼굴 안 보임 | **EVENT** (다수 얼굴 명확하면 OK) |

---

## 10. LLM 응답 검증 (sanity check)

LLM이 응답해도 다음 검증 추가 (사용자 명시 정정 강화):

| LLM 응답 | 검증 룰 | 액션 |
|---|---|---|
| BEST | face_count=0 + camera_make=∅ + lap<30 | TRASH로 재판정 (LLM 환각 의심) |
| EVENT | face_count=0 명백 (단순 풍경) | LLM 응답 신뢰 (face=0이라도 LLM이 사람 봤으면 OK) |
| FOOD | face_count > 5 | EVENT/MEMORY+ 재판정 (사람 다수면 인물 우선) |
| TRASH | face_count > 0 명백 + lap ≥ 100 | MEMORY+ 재판정 (LLM 오판 의심) |

(이 검증은 v2 PROMPT 강화에 포함 — classifier.py `_auto_grade` 후처리 로직)

---

## 11. 운영 추천

### 신규 자산
- 신규 분류 시 위 기준 자동 적용 (PROMPT 강화 기반)
- face_count + laplacian + camera_make + duration 4종 신호 모두 측정·저장 (commit 41be6e5 후 정상)

### 기존 자산
- EVENT face_count=0 + lap<30 자산 2300+ 건은 메타 누락 의심 → 일괄 재측정 권장
- 사용자가 Mac Photos에서 잘못 분류된 사진 발견 시 → 직접 등급 앨범에서 빼면 다음 sync에서 자동 정리됨 (혹은 cleanup 트리거)

### 정확도 모니터링
- weekly_kpi.py: LLM 모델 불일치율 / face=0+EVENT 비율 / lap=0 비율 알림
- 사용자 피드백(`photo.feedback` table) 기반 fine-tuning 후보

---

## 부록: 신호 임계값 표

| 신호 | 임계 | 의미 |
|---|---|---|
| `laplacian_variance` < 30 | 완전 흐림 | 피사체 식별 불가 → TRASH 후보 |
| `laplacian_variance` 30~99 | 흐림 | MEMORY- (단순 흐림은 보존) |
| `laplacian_variance` 100~299 | 선명 | MEMORY+/BEST 가능 |
| `laplacian_variance` ≥ 300 | 매우 선명 | BEST 강한 신호 |
| `face_count` = 0 (haarcascade) | 정면 얼굴 미검출 | 풍경 가능, 또는 측면·뒷모습 |
| `face_count` ≥ 1 | 정면 얼굴 검출 | 인물 사진 — MEMORY+/EVENT/BEST |
| `face_count` ≥ 3 | 단체 | EVENT 강한 신호 |
| `is_screenshot` | aspect_ratio 1.7~2.3 + face=0 + camera=∅ | 스크린샷 → TRASH |
| `duration_seconds` < 3 | 매우 짧은 영상 | TRASH |
| `duration_seconds` ≥ 3 | 일반 영상 | EVENT-L |
| `confidence` < 5 | LLM 낮은 신뢰 | 자동 신호 보강 또는 BEST 보수적 강등 |
| `confidence` ≥ 8 | LLM 높은 신뢰 | 그대로 사용 |
