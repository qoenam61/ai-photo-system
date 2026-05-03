# 사용자 셋업 가이드 (Phase 0/0-LLM)

이 문서는 사용자가 직접 수행해야 하는 셋업 작업을 단계별로 안내합니다.
VS Code 껐다 켜도 이 파일을 다시 보면 진행 상황을 이어갈 수 있습니다.

> 💡 **현재 상태 빠른 확인**: 채팅에서 "지금 어디까지 됐어?"라고 물어보세요.

---

## 진행 체크리스트

```
[x] 작업 1: VS Code Full Disk Access 권한 부여     ✅ 2026-04-30 완료
[ ] 작업 2: 사진 100장 분류·라벨링                  ⬜ 사용자 진행 필요
[ ] 작업 3: Phase 0 인벤토리 측정 (자동)           ⬜ 작업 1 완료로 진행 가능
[ ] 작업 4: 100장 벤치마크 (자동)                  ⬜ 작업 2 완료 후
[ ] 작업 5: Tier 1/2 게이트 판정 (자동)            ⬜ 작업 4 완료 후
[ ] Phase 1 진입 결정                              ⬜
```

---

## 작업 1 — VS Code Full Disk Access 권한 부여 ✅ 완료

`Photos.app` 라이브러리는 macOS TCC (Transparency Consent Control)로 보호되어 있어
Full Disk Access 권한이 없으면 어떤 도구로도 접근 불가합니다.

### 부여 방법 (이미 완료)

```
1. System Settings → Privacy & Security → Full Disk Access
2. [+] 클릭 → Visual Studio Code.app 추가
3. 토글 ON
4. ⌘ + Q (완전 종료) → VS Code 재시작
```

### 검증 명령
```bash
ls "$HOME/Pictures/Photos Library.photoslibrary/" | head -5
# 예상 출력: database/ external/ internal/ originals/ private/
```

> ⚠️ 향후 macOS 업데이트 후 재부여가 필요할 수 있습니다.

---

## 작업 2 — 사진 100장 분류·라벨링 (⬜ 진행 필요)

### 폴더 (이미 생성됨, v3.8 단일 구조)

> 단일 파이프라인 원칙(§3.7) — 사용자별 분리 없이 통합 측정.
> jw.son·eunju 사진을 같은 등급 폴더에 함께 넣으면 됨.

```
/Users/Shared/PhotoVault/_benchmark/
├── EVENT/        행사·기념일 (생일·결혼식·돌잔치·여행 첫날)
├── BEST/         일상 잘 나온 사진 (인생샷·풍경 절경)
├── FOOD/         음식 사진
├── MEMORY+/      사람 있고 양호 (BEST보다 평범)
├── MEMORY-/      사람 있지만 살짝 흐림
├── NORMAL/       풍경·사물·일상 (사람 없음)
└── TRASH/        스크린샷·심한 흐림·실수 촬영
```

> **EVENT-L 폴더가 없는 이유**: EVENT-L(이벤트 마이너)은 **AI가 유사컷 그룹 내에서 자동 강등**하는 등급입니다. 사용자가 단일 사진만 보고 라벨링하기 어렵기 때문에 벤치마크 폴더에서 제외했습니다. 행사 사진은 흐림·중복 무관하게 모두 `EVENT/`에 넣으세요. 벤치마크 채점 시 EVENT/EVENT-L 계열을 통합 인정합니다.

Finder에서 열기:
```bash
open /Users/Shared/PhotoVault/_benchmark
```

### 사진 가져오기 — 3가지 방법

#### 방법 A: macOS 사진 앱에서 드래그 (권장, jw.son)

```
1. Photos.app 열기 (이미 iCloud 동기화되어 있음)
2. 50장 선택 (⌘ + 클릭으로 다중)
3. 8등급 폴더 중 해당 폴더로 드래그
   → 사진 앱이 원본 또는 .jpg 추출본으로 export
```

#### 방법 B: AirDrop (iPhone 직접)

```
1. iPhone 사진 앱 → 다중 선택 → 공유 → AirDrop → Mac
2. Mac 다운로드 폴더에서 해당 등급 폴더로 이동
```

#### 방법 C: Galaxy USB (eunju)

```
1. brew install --cask openmtp (한 번만)
2. Galaxy USB-C 연결 → "파일 전송" 모드
3. OpenMTP 열기 → DCIM/Camera
4. 50장 선택 → Mac으로 드래그
5. 8등급 폴더로 분배
```

### 등급 결정 트리 (헷갈릴 때 사용)

사진 한 장 받고 위에서부터 첫 번째 YES에서 멈추기:

```
Q1. 음식이 화면의 절반 이상?      YES → FOOD
Q2. 스크린샷·심한 흐림·실수컷?    YES → TRASH
Q3. 사람 3+ OR 행사 오브젝트       YES → EVENT
    (케이크·꽃다발·드레스·한복)?
Q4. 사진의 주인공이 사람?
    NO → NORMAL  (풍경·사물·반려동물)
    YES ↓
Q5. 자랑하고 싶은 인생샷?          YES → BEST
Q6. 화질 양호 (흐림 거의 없음)?
    YES → MEMORY+
    NO  → MEMORY-
```

### 헷갈리는 등급 — BEST vs MEMORY+

> 핵심: "1년 후에도 다시 보고 싶을까?"

| | BEST | MEMORY+ |
|---|---|---|
| 한 줄 | "예쁘게 잘 나왔다" | "그날 그렇게 찍었다" |
| 용도 | SNS 피드/배경화면/액자 | 보관용 (자주 안 봄) |
| 표정·포즈 | 자연스럽고 좋음 | 평범 |
| 배경·구도 | 잘 어울림 | 신경 안 쓰임 |

### 헷갈리는 등급 — MEMORY- vs NORMAL

> 핵심: "사진의 주인공이 누구?"

| | MEMORY- | NORMAL |
|---|---|---|
| 주인공 | **사람** | **사물·풍경** |
| 사람 유무 | 사람이 메인 (얼굴·몸 주제) | 사람 없거나 작게 우연 |
| 화질 | 살짝 흐림/평범 | 무관 |
| 예시 | 흔들린 인물 사진 | 노을·반려동물·메뉴판 |

### 권장 분포 (총 100장, 사용자 통합)

| 등급 | 권장 | 최소 | 기준 |
|---|---|---|---|
| EVENT | 16 | 5 | 사람 3+ AND/OR 케이크·꽃·드레스·특별한 장소 |
| BEST | 16 | 5 | 흐리지 않고 EVENT 아닌 잘 나온 사진 |
| FOOD | 16 | 5 | 음식 사진 |
| MEMORY+ | 12 | 5 | 사람 있고 양호 |
| MEMORY- | 12 | 5 | 사람 있지만 약간 흐림·평범 |
| NORMAL | 16 | 5 | 풍경·사물·일상 (사람 없음) |
| TRASH | 12 | 5 | 스크린샷·심한 흐림·중복컷 |
| **합계** | **100** | **35** | jw.son·eunju 통합 |

> jw.son·eunju 사진 비율 자유 (예: jw.son만 70장 + eunju 30장도 OK).
> 가용한 만큼만 진행 가능 (35장 ~ 100장).

### 진행 상황 확인 (언제든)
```bash
find /Users/Shared/PhotoVault/_benchmark -type f \
  \( -iname "*.jpg" -o -iname "*.heic" -o -iname "*.png" -o -iname "*.jpeg" \) \
  | awk -F/ '{print $(NF-1)"/"$(NF-2)}' | sort | uniq -c
```

### 완료 신호
채팅에 **"사진 준비 완료"** 입력 → 벤치마크 자동 진행

---

## 작업 3~5 — 자동 진행 (사용자 작업 없음)

### 작업 3: Phase 0 인벤토리 측정
- 권한 부여 완료로 가능
- osxphotos 활용 — Photos 라이브러리 정확 측정
- 결과: `scripts/_inventory/inventory.json`

### 작업 4: 100장 벤치마크
- 사진 준비 완료 후 진행
- 스크립트: `scripts/phase0_llm_benchmark.py` (작성 예정)
- 측정: 정확도·속도·메모리·트레이딩 충돌

### 작업 5: Tier 1/2 게이트 판정
- 합격 기준:
  - 8등급 분류 정확도 ≥ 80%
  - 사진 1장 처리 ≤ 6초
  - 트레이딩 동시 가동 시 스왑 ≤ 100MB
- 합격 → Phase 1 진입
- Tier 1 미달 → Tier 2 (Qwen2.5-VL 3B) 재시도

---

## 부록 — 자주 묻는 질문

### Q. VS Code 껐다 다시 켜면 어디부터?
A. 이 파일 (`SETUP.md`) 보고 체크리스트 확인. 채팅에 "지금 어디?"라고 물으면 자동 답변.

### Q. 권한 부여 안 하면 안 되나?
A. Photos Library 정확 측정 불가 → 작업 3 (인벤토리) skip 가능. 다만 변환 후 예상 용량 산출 어려움. 작업 4 (벤치마크)는 사진 100장만 있으면 권한 무관.

### Q. 사진 100장 못 모으면?
A. 30~50장만으로도 벤치마크 가능. 다만 정확도 측정 신뢰 구간이 넓어짐.

### Q. 사진 등급 판단 헷갈려요
A. 직관 기반 OK. AI가 사용자 직관을 학습하는 거라, 사용자 판단이 곧 groundtruth.

### Q. 등급 폴더에 나중에 추가/이동 가능?
A. 가능. 벤치마크 실행 시점의 파일 구조가 라벨로 사용됨. 언제든 변경 후 재실행.

### Q. macOS 업데이트 후 권한 사라지면?
A. System Settings → Full Disk Access에서 토글 다시 ON. VS Code 재시작.

---

## 관련 문서

- `photo_system_design_v3.md` (v3.7) — 메인 설계, 8-Phase 로드맵
- `architecture_review.md` (v1.4) — 아키텍처 평가, 24건 의사결정
- `local_llm_evaluation.md` (v1.3) — LLM 모델 평가
- `CLAUDE.md` — Claude Code 프로젝트 컨텍스트
- `CHANGELOG.md` — 변경 이력
