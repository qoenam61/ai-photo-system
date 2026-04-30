# M4 맥미니 사진 자동화 시스템
### 설계 의도 및 전체 흐름 정의서
> v3.6 FINAL | 2026-04-30
> v2.0 FINAL 검토 → 우려점 33건 도출 → 사용자 결정 반영 통합본
> v3.1 → v3.2: 미해결 의사결정 4건 확정 + 기기 삭제 시점 플로우 다이어그램 추가
> v3.2 → v3.3: **로컬 LLM 완전 대체** (Moondream2 + Claude Haiku → Qwen2.5-VL 7B 단일) + Vision API 폐기 ($0/월)
> v3.3 → v3.4: **마이그레이션·상시 파이프라인 상세화** (§19, §20) + **영상 특화 처리** (§21) + 아키텍처 평가 보고서 분리 (`architecture_review.md`)
> v3.4 → v3.5: **아키텍처 8건 의사결정 확정** + **시스템 성숙도 9.0/10 도달 로드맵** (`architecture_review.md` v1.1)
> v3.5 → v3.6: **코드 구조 6건 의사결정 확정** (§9.4 Clean Architecture 채택, poetry, ruff, prompts/*.md, n8n 얇게, GitHub Actions) — 14건 전체 확정
> v3.6 → v3.7: **HDD 옵션 D 하이브리드 폴더 구조** (등급별 1차 + 행사/♥ 뷰 심볼릭) + **모든 동기화 03:00 일괄** + Layer 5에 storage_service 단계 추가

---

## 0. 버전별 변경 요약

### v3.1 변경 (v2.0 → v3.1)

| 영역 | v2.0 | v3.1 |
|---|---|---|
| Phase 구조 | 4단계 | **7단계** (HDD 미연결 상태에서 Phase 0~5 진행) |
| 원본 저장 | HDD 직행 | **SSD 임시 vault → HDD 마이그레이션 분리** |
| 자동 삭제 | 즉시 | **3단계 grace** (Day 0~7 dry-run → 8~14 알림 → 15~ 자동) |
| 백업 | HDD + 클라우드 | **HDD + iCloud(50GB)/Galaxy Cloud(15GB)** ※ 외부 cold storage 미도입 |
| 미디어 형식 | 원본 보존 | **JPEG/H.264 통일** (HEIC/HEVC 변환 후 7일 보관 후 폐기) |
| 분류 임계값 | "유사도 95%/90%" | **CLIP cosine 0.92/0.88** + Laplacian variance 절대값 |
| Vision API | "애매한 것만" | **로컬 신뢰도 < 0.6 + 일일 50건 + 주간 $0.5 상한** |
| 영상 처리 | 원본 코덱 | **H.264/AAC/mp4 통일** (VideoToolbox 하드웨어 가속) |

### v3.2 변경 (v3.1 → v3.2)

| 영역 | v3.1 | v3.2 |
|---|---|---|
| 미해결 의사결정 | 4건 보류 | **모두 확정 + 상세계획** (§17) |
| 파이프라인 명세 | 8레이어 표 | **레이어별 입출력·처리·실패·시간 상세화** (§5) |
| 기기 삭제 시점 | 산문 설명 | **타임라인 + 플로우 다이어그램** (§18) |
| 백필 전략 | 미정 | **4단계 점진 다운로드 + 즉시 분류** |
| iCloud 다운그레이드 | 미정 | **Phase 4 검증 후, EVENT+BEST ≤ 30GB 게이트** |
| Whisper 모델 | 미정 | **small 시작, KPI 기반 medium 승격** |
| Vision API 모델 | 미정 | Haiku 4.5 only |

### v3.3 변경 (v3.2 → v3.3) ⭐ 로컬 LLM 완전 전환

| 영역 | v3.2 | v3.3 |
|---|---|---|
| Layer 2 모델 | Moondream2 1.8B | **Qwen2.5-VL 7B Q4_K_M** (한국어·영상·JSON 우위) |
| Layer 4 모델 | Claude Haiku 4.5 (유료) | **Qwen2.5-VL 7B (로컬, 동일 모델 재사용)** |
| Vision API 비용 | $0.6/월 | **$0/월** ⭐ |
| 프라이버시 | 사진 일부 외부 API 전송 | **사진 100% 로컬 처리** |
| LLM 메모리 | ~2.3GB (Moondream + Whisper) | ~5GB (Qwen-VL 7B + Whisper-small) |
| AI 확장 활용 | 미정 | **§15 7가지 신규 영역** (앨범명·캡션·KPI 등) |
| 코딩 도구 | 미정 | **Claude Code 사용** (로컬 코딩 모델 미도입) |
| 추론 백엔드 | Ollama | **Ollama 메인 + LM Studio MLX 선택** (영상 자막용) |
| Phase 구조 | 7-Phase | **8-Phase** (Phase 0-LLM 신설, 사진 작업 전 모델 벤치마크) |

자세한 모델 평가·벤치마크는 별도 문서 `local_llm_evaluation.md` 참조.

### v3.4 변경 (v3.3 → v3.4) ⭐ 파이프라인 구체화 + 아키텍처 평가

| 영역 | v3.3 | v3.4 |
|---|---|---|
| 마이그레이션 흐름 | Phase 3 표 단순 | **§19 단계별 상세** (osxphotos·OpenMTP·체크섬·메타·검증) |
| 상시 흐름 | Layer별 분산 명세 | **§20 트리거 매트릭스 + T+0 타임라인 + idempotency** |
| 영상 처리 | 산문 특이사항 | **§21 코덱 매트릭스 + Live Photo + 샘플링 + 음성** |
| 아키텍처 평가 | 우려점 33건 (산문) | **별도 보고서** `architecture_review.md` (전문가 관점) |
| 동시성·idempotency | 묵시적 | **명시적 처리 표** (§20.3) |

### v3.5 변경 (v3.4 → v3.5) ⭐ 아키텍처 의사결정 + 9.0/10 도달 로드맵

| 영역 | v3.4 | v3.5 |
|---|---|---|
| 시스템 성숙도 | 5.6/10 | **9.0/10 목표** (모든 차원 9점+) |
| HDD 암호화 | 도입 권고 | ⚠️ **영구 미도입** (사용자 결정, 가정용 보관 + I/O 영향) |
| HDD 용량 | 2TB 검토 | **1TB 유지**, 80% 도달 시 확장 |
| Postgres 분리 | 옵션 미정 | **photo schema** (trading_postgres 내) |
| Redis Streams | Phase 1 권장 | **Phase 1 확정** |
| Loki 로그 통합 | Phase 7 후 | **Phase 1부터 도입** (관측성 9점 위해) |
| Outbox pattern | 옵션 미정 | **단순 폴링 (1초)** 확정 |
| Golden dataset | 미정 | **100장 확정** (jw.son 50 + eunju 50) |
| 시크릿 관리 | 미정 | **`.env.gpg`** 확정 |

### v3.6 변경 (v3.5 → v3.6) ⭐ 코드 구조 의사결정 (전체 14건 확정)

| 영역 | v3.5 | v3.6 |
|---|---|---|
| 코드 모듈 구조 | 미정 | **§9.4 Clean Architecture** (core/domain/repo/client/service/pipeline/infra) |
| Python 패키지 | 미정 | **poetry** (pyproject.toml + lock) |
| 린트·포맷 | 미정 | **ruff** (단일 도구) |
| 프롬프트 위치 | 워크플로우 내부 | **`prompts/*.md`** 외부 파일 (9개) |
| n8n 워크플로우 | 두꺼움 (로직 포함) | **얇게** (cron + HTTP만, Python 호출) |
| CI/CD | 미정 | **GitHub Actions** |
| 코드 재사용성 | 5/10 | **9/10** (16개 공용 로직 추출) |
| 유지보수성 | 5/10 | **9/10** (변경 영향 5~10배 축소) |

### v3.7 변경 (v3.6 → v3.7) ⭐ HDD 폴더 구조 + 03:00 동기화 일괄

| 영역 | v3.6 | v3.7 |
|---|---|---|
| HDD 폴더 구조 | 사용자별 평면 (UUID) | **옵션 D 하이브리드** (등급별 1차 + `views/` 심볼릭 다층) |
| 등급 폴더 | (없음) | EVENT/EVENT-L/BEST/FOOD/MEMORY+/MEMORY-/NORMAL/TRASH (8개) |
| 뷰 폴더 | (없음) | `行事별/月별/♥/음식/` 심볼릭 링크 |
| 동기화 시작 시각 | 03:30~06:00 분산 | **03:00 일괄** (~13분) |
| Layer 5 처리 단계 | 앨범 + 큐 등록 | **앨범 + 등급 폴더 이동 + 뷰 갱신** |
| 코드 모듈 | 6 layer | **+ storage_service.py** (등급 폴더·뷰 관리) |
| Immich 죽음 fallback | Immich 의존 | **Finder만으로 EVENT/BEST 식별 가능** |
| 다중 분류 (♥+EVENT) | Immich 메타만 | **뷰 폴더에서 동시 노출** (심볼릭) |

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

- **원본은 절대 버리지 않는다** — 단, "원본"의 정의는 변환본(JPEG/H.264). HEIC/HEVC 입력은 변환 후 7일 보관 후 자동 폐기.
- TRASH는 30일간 HDD 보관 후 삭제 (사용자 ♥ 시 복구 가능)
- iPhone에서 삭제해도 Immich 앱에서 원본 스트리밍으로 열람 가능
- **사진은 절대 외부 API로 나가지 않는다** — 모든 LLM 추론은 로컬 (Qwen2.5-VL 7B), Vision API 미사용 ($0/월)
- 자동 삭제는 3단계 grace로 점진 활성화 (신뢰 검증 후)

---

## 2. 하드웨어 구성

> M4 Mac mini 512GB SSD + External HDD 1TB (USB3, **Phase 6에서 도착**) + iCloud 50GB + Galaxy Cloud 15GB

| 위치 | 역할 | 가용 시점 |
|------|------|-----------|
| **SSD 512GB** (맥미니 내장) | macOS + 앱 · Docker 엔진 전체 · PostgreSQL · Redis · Immich 썸네일·캐시 · Ollama 모델 · **Phase 0~5: 사진 임시 vault** | 즉시 |
| **SSD 임시 vault** | `/Users/Shared/PhotoVault/{jw.son,eunju,shared}/` · 가용 상한 ~150GB · 변환 작업 폴더 `_convert/` 포함 | Phase 1~5 |
| **HDD 1TB** (External USB3) | `/Volumes/PhotoHDD/immich-media/{jw.son,eunju,shared}/` · 모든 분류된 자산의 영구 저장소 | **Phase 6 이후** |
| **iCloud 50GB** (jw.son) | EVENT + BEST + ♥ 자동 동기화 | 즉시 |
| **Galaxy Cloud 15GB** (eunju) | EVENT + BEST + ♥ 단방향 푸시 (Immich → DCIM/Camera → Galaxy Cloud) | 즉시 |

**SSD 가용공간 산정 (Phase 0 인벤토리에서 정량화)**

```
SSD 512GB
- macOS + 앱             ~80 GB
- Docker 엔진 + 이미지     ~30 GB
- PostgreSQL (트레이딩+Immich) ~20 GB
- Redis · Ollama 모델     ~10 GB
- 시스템 여유             ~50 GB
─────────────────────────────────
임시 vault 가용           ~320 GB (이론) / ~150 GB (안전선 70% 여유)
```

> Phase 0에서 사용자 사진 총량 측정 후 SSD 임시 운영 가능 여부 판단. 초과 시 Phase 6까지 점진 다운로드 전략.

---

## 3. 사용자 구성 및 폴더 구조

두 사용자가 동일한 Immich 서버를 사용하되 완전히 독립된 공간으로 관리된다. 로직·파이프라인은 공유하고 저장 경로만 분기한다.

| 항목 | jw.son | eunju | 공유 |
|------|--------|-------|------|
| 기기 | iPhone | Galaxy | — |
| **임시 vault (Phase 1~5)** | `/Users/Shared/PhotoVault/jw.son/` | `/Users/Shared/PhotoVault/eunju/` | `/Users/Shared/PhotoVault/shared/` |
| **HDD 경로 (Phase 6~)** | `/Volumes/PhotoHDD/immich-media/jw.son/library/{등급8개}/` + `/immich-views/jw.son/` | 동일 (eunju) | 동일 (shared) |
| Immich 계정 | jw.son 계정 | eunju 계정 | 공유 앨범 (두 계정 모두 접근) |
| 앨범 구성 | EVENT / EVENT-L / BEST / FOOD / MEMORY+ / MEMORY- / NORMAL / ♥ | 동일 | 공유 EVENT 앨범 |
| 클라우드 백업 | iCloud 50GB · EVENT+BEST+♥ | Galaxy Cloud 15GB · EVENT+BEST+♥ | — |
| 클라우드 동기화 방향 | iPhone ↔ iCloud (양방향, Apple 기본) | **Immich → DCIM/Camera 단방향 푸시 → Galaxy Cloud** | — |
| 기기 정리 | iOS Shortcut 자동 실행 | **MacroDroid 무료 버전** | — |

### Galaxy Cloud 단방향 워크플로우 (eunju 전용)

Galaxy Cloud는 "DCIM/Camera" 폴더만 자동 동기화하므로, Immich가 분류 후 EVENT+BEST+♥ 자산을 다시 갤럭시 DCIM/Camera에 푸시해야 클라우드 백업이 완성된다.

```
[갤럭시 촬영] → DCIM/Camera → Galaxy Cloud 즉시 동기화 (원본)
                            ↓
                       Immich 자동 백업 (Wi-Fi)
                            ↓
                       파이프라인 분류
                            ↓
                       EVENT+BEST+♥ 판정
                            ↓
                  [n8n] Immich API → 자산 다운로드 → SMB/HTTP 서버
                            ↓
                  [MacroDroid #4] 폴링 → 미수신 자산 다운로드 → DCIM/PhotoSystemBackup/
                            ↓
                       Galaxy Cloud 자동 동기화 (백업 완성)
```

**중요**: 매크로 #4는 EVENT+BEST+♥만 받아 별도 폴더(`DCIM/PhotoSystemBackup/`)에 저장. 갤럭시 갤러리에서는 보이지만 Galaxy Cloud는 DCIM 하위라 자동 동기화함.

### 공유 EVENT 앨범 자동 생성 조건

두 사용자의 사진이 아래 조건을 모두 충족하면 공유 EVENT 앨범을 자동 생성한다.

- 촬영 시간 차이 2시간 이내
- GPS 위치 반경 500m 이내
- 두 사진 모두 EVENT 등급 판정
- 앨범명: 날짜 + 장소 자동 생성 (예: `2026-04-29 강남구 행사`)
- 두 Immich 계정 모두에서 접근 가능
- **Race condition 방지**: 두 사용자 분류가 완료된 후 새벽 03:30에 공유 EVENT 매칭 워크플로우 1회만 실행

---

## 3.5 HDD 폴더 구조 상세 — 옵션 D 하이브리드 (v3.7 신규)

원본은 등급별 1차 폴더에 평면 저장(UUID 파일명), 행사·♥·월 등 다층 분류는 별도 `immich-views/` 디렉토리에 심볼릭 링크로 노출.

### 3.5.1 디렉토리 구조

```
/Volumes/PhotoHDD/
├── immich-media/                       ← Immich External Library (원본)
│   ├── jw.son/library/
│   │   ├── EVENT/<UUID>.jpg            ← 평면 (UUID 파일명, 행사 sub-폴더 없음)
│   │   ├── EVENT-L/<UUID>.jpg
│   │   ├── BEST/<UUID>.jpg
│   │   ├── FOOD/<UUID>.jpg
│   │   ├── MEMORY+/<UUID>.jpg
│   │   ├── MEMORY-/<UUID>.jpg
│   │   ├── NORMAL/<UUID>.jpg
│   │   └── TRASH/<UUID>.jpg            (30일 후 폴더째 cleanup)
│   ├── eunju/library/                  (동일 8개 등급 폴더)
│   └── shared/library/                 (공유 EVENT 자산)
│
├── immich-views/                       ← 뷰 폴더 (심볼릭 링크 다층)
│   ├── jw.son/
│   │   ├── 행사별/
│   │   │   ├── 2026-04-29 강남 결혼식/
│   │   │   │   ├── 14-32-15.jpg → ../../../../immich-media/jw.son/library/EVENT/<UUID>.jpg
│   │   │   │   └── 14-32-22.jpg → ...
│   │   │   └── 2026-04-15 어버이날/
│   │   ├── 월별/
│   │   │   └── 2026-04/
│   │   ├── ♥ 즐겨찾기/                 (등급과 독립, 다중 분류)
│   │   ├── 음식/
│   │   │   ├── 한식/
│   │   │   ├── 양식/
│   │   │   ├── 일식/
│   │   │   └── 디저트/
│   │   └── (선택) 유사그룹/
│   ├── eunju/                          (동일 구조)
│   └── 공유/
│       └── 행사별/
│           └── 2026-04-29 강남 결혼식/  → shared/ 자산 링크 (양 사용자 모두 접근)
│
└── _backup/                            ← Postgres dump, 시스템 백업
    ├── immich/
    └── trading/
```

### 3.5.2 옵션 D 핵심 설계 원칙

| 원칙 | 적용 |
|---|---|
| 원본은 등급 폴더에만 (한 곳) | EVENT 사진은 `EVENT/`에만, 다른 폴더에 복사 X |
| 뷰는 심볼릭 링크만 (디스크 추가 0) | inode 수십 바이트, 데이터 복사 없음 |
| 다중 분류 자연스러움 | EVENT + ♥ → 원본 `EVENT/`, 뷰 `행사별/` + `♥ 즐겨찾기/`에 동시 링크 |
| 분류 변경 시 원본만 mv | 등급 폴더 간 이동 (mv는 메타만 변경, I/O 0) |
| 뷰 갱신은 unlink + symlink | 디스크 부담 없음 |

### 3.5.3 옵션 D 효과

```
✅ Immich 죽어도 Finder만으로 EVENT/BEST 즉시 식별
✅ TRASH/ 폴더째 30일 후 cleanup (단순한 cron)
✅ 백업 선별 가능 — EVENT/ BEST/만 외장 USB 추가 백업 (선택)
✅ 다중 분류 충돌 없음 (♥ + EVENT 동시)
✅ Phase 6 마이그레이션 단순 (등급 8개 × 사용자 3명 = 24 폴더 rsync)
✅ 분류 변경 시 mv 단순 (메타만, 데이터 복사 0)
```

### 3.5.4 행사·장소명 자동 생성 (뷰 폴더용)

§15.A 앨범명 자동 생성 로직 활용:
- Qwen2.5-VL 7B 호출 (사진 5장 + GPS 메타 입력)
- 출력 예: "강남 결혼식", "한라산 등반", "어버이날"
- GPS 역지오코딩 → "강남구"
- 결합 → 폴더명: `2026-04-29 강남 결혼식`

행사명 변경 시 (사용자 수동 또는 LLM 재생성):
- 원본은 `EVENT/<UUID>.jpg`에 그대로 (이동 없음)
- 뷰만 unlink + 새 폴더에 symlink
- **운영 부담 매우 작음**

### 3.5.5 분류 변경 시 처리 정책

| 시나리오 | 빈도 | 원본 처리 | 뷰 처리 |
|---|---|---|---|
| 신규 분류 (Layer 5 첫 배정) | 일 100~500장 | 등급 폴더에 직접 저장 | 심볼릭 링크 생성 |
| 사용자 ♥ 추가 | 사용자 행위 | **이동 없음** | `♥ 즐겨찾기/`에 추가 |
| Layer 4 재분류 (NORMAL→BEST) | 일 ~50장 | `mv NORMAL/<UUID>.jpg BEST/<UUID>.jpg` | unlink + 새 위치 |
| 사용자 수동 등급 변경 | 드물게 | 동일 (mv) | unlink + 갱신 |
| TRASH → ♥ 복구 | 드물게 | mv TRASH/ → 원래 등급 | 갱신 |
| 행사명 변경 | 드물게 | **변경 없음** | 뷰 폴더만 재구성 |

→ **HDD I/O 부담**: 일일 mv 100건 미만 (메타만, 데이터 복사 0). 뷰 갱신은 inode 작업만.

---

## 4. 분류 등급 (8단계) + 즐겨찾기

| 등급 | 기준 | 백업 위치 | 기기 보관 | 즐겨찾기 |
|------|------|-----------|-------------|----------|
| ⭐ **EVENT** | 행사·기념일 + 다양성 기준 선발 고품질 | iCloud/Galaxy Cloud + HDD | ✅ 유지 | ♥ 가능 |
| ⭐ **EVENT-L** | 행사·기념일 + 유사컷 내 상대적 저품질 | HDD | ❌ 삭제 | ♥ 가능 |
| ✦ **BEST** | 일반 장면 다양성 기준 선발 | iCloud/Galaxy Cloud + HDD | ✅ 유지 | ♥ 가능 |
| 🍽 **FOOD** | 음식 베스트컷 (유사도 80% 기준 중복 제거) | HDD | ❌ 삭제 | ♥ 가능 |
| ◆ **MEMORY+** | 사람·장면 있음 + 품질 양호 (BEST 탈락) | HDD | ❌ 삭제 | ♥ 가능 |
| ◇ **MEMORY-** | 사람·장면 있음 + 품질 낮음 (BEST 탈락) | HDD | ❌ 삭제 | ♥ 가능 |
| ○ **NORMAL** | 사람 없음·풍경·사물 (BEST 탈락) | HDD | ❌ 삭제 | ♥ 가능 |
| 🗑 **TRASH** | 흐림 심함·스크린샷·중복 탈락 | 30일 후 삭제 | ❌ 삭제 | — |

### 알고리즘 임계값 명세 (v3.1 정량화)

| 항목 | 알고리즘 | 임계값 |
|---|---|---|
| 유사컷 그룹핑 | **CLIP ViT-B/32 cosine similarity** (Immich 내장 임베딩 활용) | EVENT: ≥ 0.92 시 강등 / BEST: ≥ 0.88 시 강등 |
| 흐림 판정 | **Laplacian variance** | < 100: 흐림 / 100~300: 보통 / > 300: 선명 |
| EVENT 자동판정 | **점수 가산제** | ≥ 4점 시 EVENT |
| Vision API 호출 | **로컬 신뢰도** (Moondream2 confidence) | < 0.6 AND 일일 ≤ 50건 AND 주간 ≤ $0.5 |
| 음식 유사도 | pHash (8x8 DCT) | Hamming distance ≤ 6/64 → 중복 |

**EVENT 점수 가산제**

| 조건 | 점수 |
|---|---|
| 얼굴 ≥ 3명 감지 | 2 |
| 공식 복장 (정장/드레스/한복) 감지 | 1 |
| 행사 오브젝트 (케이크/꽃다발/무대) 감지 | 2 |
| Laplacian variance > 300 (선명도 상위) | 1 |
| 음성 키워드 감지 (생일/건배/박수/사랑해) — 영상만 | 2 |
| **합계 ≥ 4점** | → **EVENT 자동 배정** |

### EVENT · BEST 유사컷 처리 원칙

EVENT와 BEST는 동일한 다양성 기준을 적용하되, EVENT는 임계값을 더 여유있게 설정해 행사 사진을 더 많이 보관한다.

- 구도·표정·배경이 다르면 각각 별도 보관 (상한 없음)
- 유사도가 임계값 이상 → 품질 낮은 쪽 강등
- 원본은 모두 HDD에 보관

**예시 (CLIP cosine 기준)**
- 행사 5연사 (cosine 0.91) → EVENT는 모두 보관 (0.92 미만), BEST는 1장 (0.88 이상)
- 행사 표정 차이 2컷 (cosine 0.95) → EVENT·BEST 모두 1장만
- 배경·구도 다른 3컷 (cosine 0.70) → EVENT·BEST 모두 3장 보관

### 🍽 FOOD 등급 처리 원칙

음식은 Layer 2에서 감지 즉시 일반 파이프라인과 분리되어 별도 로직으로 처리된다.

- 음식 감지 → pHash Hamming ≤ 6 → TRASH (같은 음식 적극 제거)
- 음식 감지 → pHash Hamming > 6 → FOOD 등급, HDD 전용 보관
- 클라우드 백업 없음, 기기 삭제
- Immich 내 FOOD 앨범 자동 생성 — 날짜별 열람
- ♥ 지정 시 클라우드로 승격

### ♥ 즐겨찾기 동작

- Immich 앱에서 사진·영상을 꾹 누르면 ♥ 지정 가능
- 어떤 등급이든 ♥ 지정 시 → iCloud/Galaxy Cloud + HDD로 자동 승격
- iPhone/Galaxy 사진첩에서 삭제된 사진도 ♥하면 클라우드 재백업
- ♥ 자산은 **24시간 내 클라우드 동기화 검증 큐**에 등록 (실패 시 알림)

**백업 우선순위**

```
EVENT / BEST          → 자동으로 클라우드 + HDD
♥ 지정                → 등급 무관 클라우드 + HDD 승격
FOOD / MEMORY / NORMAL → HDD만
TRASH                 → 30일 후 삭제 (♥ 시 복구)
```

---

## 5. 전체 파이프라인 (8레이어)

v2.0 7레이어에 **Layer 0.5 미디어 변환** 추가.

| 레이어 | 단계 | 처리 내용 | 기술 스택 |
|--------|------|-----------|-----------|
| **Layer 0** | 업로드 | jw.son · eunju → Immich 자동 백업 (Wi-Fi, 충전 중) · 사용자별 폴더 분기 | Immich 앱 |
| **Layer 0.5** | 미디어 변환 ⭐신규 | HEIC → JPEG (q=95) · HEVC/MOV → H.264 mp4 (VideoToolbox 가속) · Live Photo 분리 (정지 JPEG + motion mp4, parent_asset_id 연결) · 메타(EXIF/GPS) 보존 검증 · 원본 7일 격리 보관 | ffmpeg (h264_videotoolbox) · ImageMagick · Python |
| **Layer 1** | 전처리 | Laplacian variance · 노출 점수 · 스크린샷 판별 · 유사컷 그룹핑 (CLIP cosine) · 영상: 길이·흔들림·무음 판별 · 동일 시간대·위치 공유 행사 감지 | OpenCV · Python · ffprobe |
| **Layer 2** | 콘텐츠 분석 | 사람 수·얼굴 · 장면 유형 · 음식 감지 → FOOD 분기 · 공식 복장·행사 오브젝트 · 영상 대표 프레임 추출 · 음성→텍스트 키워드 | **Qwen2.5-VL 7B Q4_K_M** · Ollama · Whisper-small (한국어) |
| **Layer 3** | 등급 자동 판정 | 점수 가산제로 EVENT 판정 · CLIP cosine 임계값으로 유사컷 강등 · 공유 행사 감지 → 공유 EVENT 앨범 큐 | n8n |
| **Layer 4** | 보조 판단 (로컬 LLM) | 새벽 03:00 배치 · Layer 2 신뢰도 < 0.6 자산을 더 정교한 프롬프트로 재분류 · **유료 API 미사용 ($0/월)** | **Qwen2.5-VL 7B (로컬, Layer 2와 동일 모델 재사용)** |
| **Layer 5** | 앨범 자동 배정 | 결과 → 사용자별 Immich 앨범 · 공유 EVENT 매칭 (양 사용자 분류 완료 후 03:30) · 분류 로그 → PostgreSQL · TRASH 30일 카운터 시작 · 기기 삭제 큐 등록 | Immich API · PostgreSQL |
| **Layer 6** | 기기 정리 | jw.son: iOS Shortcut · eunju: MacroDroid 매크로 #1~#3 · **24h grace period 후 삭제** · 매크로 #4가 EVENT+BEST+♥ 갤럭시로 푸시 | iOS Shortcuts · MacroDroid · n8n Webhook |
| **Layer 7** | 검증·피드백 ⭐신규 | ♥ 변경·등급 수동수정 → `feedback` 테이블 기록 · 주간 KPI 리포트 (false positive/negative 통계) · 클라우드 동기화 검증 (♥ 자산 24h 내 확인) | n8n · PostgreSQL |

### Layer 0.5 변환 상세

**HEIC → JPEG**

```bash
# ImageMagick 또는 sips (macOS 네이티브) 사용
sips -s format jpeg -s formatOptions 95 input.heic --out output.jpg
exiftool -overwrite_original -tagsFromFile input.heic -all:all output.jpg
```

**HEVC/MOV → H.264 mp4 (VideoToolbox 가속)**

```bash
ffmpeg -i input.mov \
  -c:v h264_videotoolbox -b:v 8M -profile:v high \
  -c:a aac -b:a 192k \
  -map_metadata 0 \
  -movflags +faststart \
  output.mp4
```

**Live Photo 분리**

- Apple Live Photo는 .HEIC + .MOV 페어로 들어옴
- 정지 .HEIC → .JPG 변환 (asset_id = N)
- 모션 .MOV → .mp4 변환 (asset_id = N+1, parent_asset_id = N)
- Immich `assets` 테이블에 parent 관계 기록 → UI에서 함께 표시

**원본 7일 격리 보관**

```
/Users/Shared/PhotoVault/_convert/quarantine/
├── 2026-04-30/
│   ├── jw.son/
│   │   ├── IMG_1234.HEIC          ← 변환 후 7일 보관
│   │   └── IMG_1234.HEIC.meta.json ← 변환 검증 결과
│   └── eunju/
└── 2026-04-23/                     ← 7일 경과 → 자동 삭제 대상
```

**변환 검증 항목** (`.meta.json`)
- SHA256 (입력 / 출력)
- EXIF 핵심 필드 일치 (DateTimeOriginal, GPSLatitude/Longitude, Make, Model)
- 디코딩 OK (출력 파일 정상 열림)
- 검증 실패 시 → quarantine 무기한 보관 + 알림

### 영상 분석 특이사항

- 3초 미만 영상 → 즉시 TRASH (실수로 찍은 것)
- 5초마다 대표 프레임 추출 → Moondream2 분석
- Whisper-small 한국어로 음성→텍스트 변환
- 30초 영상 1개 기준 처리 시간: ~9초 (1080p H.264) / ~15초 (4K H.264) — 야간 배치로 충분
- VideoToolbox 디코딩 가속 활용

---

### Layer별 상세 명세 (v3.2 신규)

#### 데이터 흐름 다이어그램 (전체)

```
┌──────────┐                                        [iPhone/Galaxy]
│  촬영    │
└────┬─────┘
     │ Wi-Fi + 충전 (사용자 조건)
     ▼
┌─────────────────────────────────────────────────┐
│ Layer 0   Immich 자동 백업                       │  Immich 앱
│  IN:  기기 사진앱 신규 자산 (HEIC/HEVC/JPG/MP4)   │
│  OUT: SSD vault upload/ + Immich DB asset row    │
└────┬─────────────────────────────────────────────┘
     │ Webhook: AssetUploaded
     ▼
┌─────────────────────────────────────────────────┐
│ Layer 0.5  미디어 변환                          │  media-converter
│  IN:  upload/*.heic, upload/*.mov, upload/*.mp4  │  컨테이너
│  OUT: library/*.jpg, library/*.mp4               │  (ffmpeg+sips)
│  SIDE: _convert/quarantine/YYYY-MM-DD/          │
│  DB:  photo_conversion_log (PASS/FAIL)          │
└────┬─────────────────────────────────────────────┘
     │ 일배치 (16:00 트리거)
     ▼
┌─────────────────────────────────────────────────┐
│ Layer 1   전처리                                │  Python+OpenCV
│  IN:  당일 신규 library/ asset                   │
│  OUT: photo_classification (사전 점수 컬럼)      │
│       similarity_group_id 부여                  │
└────┬─────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────┐
│ Layer 2   콘텐츠 분석                           │  Ollama
│  IN:  Layer 1 출력 + similarity_group_id         │  (Moondream2,
│  OUT: photo_classification.scene_tags JSONB      │   Whisper-small)
│       face_count, food_detected, object_tags     │
└────┬─────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────┐
│ Layer 3   등급 자동 판정                        │  n8n
│  IN:  Layer 1+2 통합 데이터                      │  워크플로우
│  OUT: photo_classification.grade (8등급 중 하나) │  #PHOTO-3
│       confidence_score (0~1)                    │
└────┬─────────────────────────────────────────────┘
     │ 03:00 배치
     ▼
┌─────────────────────────────────────────────────┐
│ Layer 4   Vision API 보조 판단 (애매한 것만)    │  Claude Haiku
│  IN:  confidence < 0.6 자산 (일일 ≤ 50건)        │  4.5
│  OUT: photo_classification.grade 갱신 (재판정)   │  #PHOTO-4
│       vision_api_used = TRUE                    │
└────┬─────────────────────────────────────────────┘
     │ 03:30 배치
     ▼
┌─────────────────────────────────────────────────┐
│ Layer 5   앨범 자동 배정                        │  Immich API
│  IN:  Layer 3+4 최종 등급                        │  + n8n
│  OUT: Immich Album 멤버십                        │  #PHOTO-5
│       cleanup_queue (24h grace 시작)            │
│       shared_event_album (양 사용자 EVENT 매칭) │
└────┬─────────────────────────────────────────────┘
     │ 24h grace 후, 04:30 충전+Wi-Fi 시
     ▼
┌─────────────────────────────────────────────────┐
│ Layer 6   기기 정리                             │  iOS Shortcut
│  IN:  cleanup-list API 응답                      │  MacroDroid
│  OUT: 기기 사진앱에서 삭제                       │  #1~#4
│       galaxy: DCIM/PhotoSystemBackup/ 푸시      │
└────┬─────────────────────────────────────────────┘
     │ 04:00 일배치
     ▼
┌─────────────────────────────────────────────────┐
│ Layer 7   검증·피드백                           │  n8n
│  IN:  photo_feedback, ♥ 이벤트, cloud sync 상태  │  #PHOTO-6
│  OUT: KPI 리포트, 임계값 권장값                  │
│       cloud sync 미완료 알림                    │
└─────────────────────────────────────────────────┘
```

---

#### Layer 0 — Immich 자동 백업

| 항목 | 내용 |
|---|---|
| **트리거** | iPhone/Galaxy Immich 앱 (Wi-Fi 연결 + 충전 중) |
| **입력** | 기기 사진앱 신규 자산 (HEIC/HEVC/JPG/MOV/MP4) |
| **출력** | SSD `/Users/Shared/PhotoVault/{user}/upload/` + Immich DB asset row |
| **처리 단계** | 1. Immich 앱 백그라운드 동기화 감지<br>2. 메타(EXIF, 촬영시각, GPS) 추출 후 헤더로 전송<br>3. 청크 업로드 (재시도 5회)<br>4. 서버 측 SHA256 검증 → DB 등록 |
| **도구** | Immich 앱 (iOS 1.130+, Android 1.130+) · Immich Server v1.130+ |
| **DB 변경** | `assets` insert · `exif` insert · `users` 사용자별 owner_id |
| **실패 처리** | 네트워크 단절 → 큐 보존 → 다음 동기화 시 재시도 |
| **평균 시간** | 사진 1장 1~3초, 4K 영상 1분당 30~60초 (Wi-Fi 속도 의존) |
| **의존성** | Tailscale 연결 (집 밖) · 충전+Wi-Fi (사용자 설정) |
| **모니터링** | Immich Server 로그 + 일일 업로드 카운트 KPI |

---

#### Layer 0.5 — 미디어 변환

| 항목 | 내용 |
|---|---|
| **트리거** | Immich `AssetUploaded` Webhook → n8n #PHOTO-2 |
| **입력** | `upload/*.heic`, `upload/*.mov`, `upload/*.mp4` (HEVC 코덱) |
| **출력** | `library/*.jpg` (q=95) · `library/*.mp4` (H.264/AAC) |
| **부수효과** | `_convert/quarantine/YYYY-MM-DD/{user}/` 7일 격리 |
| **처리 단계** | 1. 입력 파일 SHA256 계산 → `photo_conversion_log` insert<br>2. 코덱 판별 (`ffprobe -show_streams`)<br>3. **이미지 분기**: `sips -s format jpeg -s formatOptions 95` + `exiftool -tagsFromFile`<br>4. **영상 분기**: `ffmpeg -c:v h264_videotoolbox -b:v 8M -c:a aac -b:a 192k -map_metadata 0 -movflags +faststart`<br>5. **Live Photo 분기**: HEIC + MOV 페어 → JPG + 별도 mp4, `parent_asset_id` 연결<br>6. 출력 SHA256 + EXIF 검증 (DateTimeOriginal, GPSLatLon, Make, Model 일치)<br>7. 디코딩 검증 (`ffmpeg -v error -i out -f null -`)<br>8. PASS → library/ 이동, 입력은 quarantine 이동 (7일 카운터)<br>9. FAIL → 출력 폐기, 입력 library/ 그대로, Telegram 알림 |
| **도구** | ffmpeg 6.x (h264_videotoolbox) · ImageMagick 7 · sips (macOS) · exiftool 12.x · ffprobe |
| **DB 변경** | `photo_conversion_log` (original_path, converted_path, sha256s, metadata_match, decoded_ok, quarantine_until=오늘+7) |
| **실패 처리** | 변환 실패 → 입력 보존, FAIL row 알림 / EXIF 불일치 → quarantine 무기한 보관 |
| **평균 시간** | HEIC→JPEG 50ms · 1분 1080p HEVC→H.264 30s · 1분 4K HEVC→H.264 60s |
| **의존성** | macOS 호스트의 VideoToolbox (GPU 가속) — Docker 네이티브 불가 시 호스트 launchd로 위임 |
| **하드웨어** | M4 GPU 활용 (h264_videotoolbox), CPU fallback 시 ×3~5 시간 |
| **퍼지 정책** | 매일 06:00 `quarantine_until < CURRENT_DATE AND purged_at IS NULL` 영구 삭제 (단 사용자 ♥ 또는 등급 수정 자산은 +7일 연장) |

---

#### Layer 1 — 전처리

| 항목 | 내용 |
|---|---|
| **트리거** | 매일 16:00 cron → n8n #PHOTO-3 시작 |
| **입력** | 당일 library/ 신규 자산 (Layer 0.5 PASS 통과한 것만) |
| **출력** | `photo_classification` 사전 점수 + `similarity_group_id` |
| **처리 단계** | 1. **이미지 품질 점수** (Python+OpenCV)<br>   - Laplacian variance (`cv2.Laplacian(gray, cv2.CV_64F).var()`)<br>   - 노출 분포 (히스토그램 0~10/240~255 비율)<br>   - 스크린샷 판별 (해상도·종횡비·UI 색상 패턴)<br>2. **유사컷 그룹핑** (Immich 내장 CLIP 임베딩 활용)<br>   - 촬영 시각 ±10분 + GPS 반경 50m 내 자산을 후보군으로 묶음<br>   - 후보군 내 CLIP cosine pairwise 계산<br>   - cosine ≥ 0.85 그룹은 동일 `similarity_group_id` 부여<br>3. **영상 사전 판별**<br>   - `ffprobe`로 길이·해상도·평균 비트레이트 추출<br>   - 3초 미만 → 즉시 TRASH 후보 마킹<br>   - 흔들림 점수 (대표 5프레임 Laplacian variance 평균)<br>   - 무음 판별 (RMS dB) — 조건부 Whisper skip<br>4. **공유 행사 사전 감지**<br>   - jw.son·eunju 자산 중 시각 ±2h + GPS ≤ 500m 페어를 `shared_candidate` 테이블에 등록 (실제 공유 EVENT 생성은 Layer 5에서) |
| **도구** | Python 3.12 + OpenCV 4.10 + ffprobe 6 + numpy |
| **DB 변경** | `photo_classification` 사전 컬럼 update (laplacian_variance, exposure_score, is_screenshot, similarity_group_id) |
| **실패 처리** | 자산 디코딩 실패 → `processing_status='ERROR_DECODE'` 마킹, 이후 레이어 skip, 알림 |
| **평균 시간** | 사진 1장 0.2초, 영상 30초 1.5초 (CPU 단일 코어 기준) |
| **병렬화** | Python multiprocessing 4 workers (M4 8코어 중 4개 점유, 트레이딩 영향 최소화) |
| **의존성** | Layer 0.5 PASS 자산만 처리 (FAIL 자산은 grade='PROCESSING_FAILED' 직행) |

---

#### Layer 2 — 콘텐츠 분석

| 항목 | 내용 |
|---|---|
| **트리거** | Layer 1 완료 후 즉시 (n8n 순차 실행) |
| **입력** | `photo_classification` Layer 1 통과 자산 + similarity_group 그룹별 대표 1장 |
| **출력** | `scene_tags` JSONB · `face_count` · `food_detected` · `formal_dress` · `event_objects` · 영상 `voice_keywords` |
| **처리 단계** | 1. **유사컷 그룹 대표선택**: 그룹 내 Laplacian variance 최고 자산만 분석 (Vision 부하 감소)<br>2. **얼굴 감지** (Immich-ml 내장)<br>   - face_count, face_quality_avg<br>3. **장면·객체 분석** (Moondream2 via Ollama)<br>   - 프롬프트: "List the scene type (event/daily/scenery/food/object), people count, formal_dress (yes/no), notable objects (cake/flowers/stage/table/etc.). Respond in JSON."<br>   - 응답 파싱 → scene_tags JSONB<br>4. **음식 분기 결정**<br>   - food_detected = true → similarity_group을 FOOD 분류 큐로 이동 (이후 일반 파이프라인 skip)<br>5. **영상 추가 처리**<br>   - 5초 간격 대표 프레임 추출 → Moondream2 일괄 (배치)<br>   - 음성 추출 (`ffmpeg -vn -ac 1 -ar 16000`) → Whisper-small<br>   - 키워드 매칭: ["생일", "축하", "건배", "박수", "사랑해", "결혼", "케이크", "박수쳐"]<br>6. **로컬 신뢰도 산출** (Layer 4 입력용)<br>   - confidence = min(face_quality, scene_clarity, object_clarity)<br>   - < 0.6 → Layer 4 큐에 등록 |
| **도구** | Ollama 0.4+ (Moondream2 1.8B Q4_K_M, Whisper-small Q5_K_M) · Python 클라이언트 |
| **DB 변경** | `photo_classification.scene_tags`, `face_count`, `food_detected`, `voice_keywords`, `local_confidence` |
| **실패 처리** | Ollama 타임아웃 (30s) → 재시도 1회 → 실패 시 grade='UNCLASSIFIED' 마킹, Layer 4 강제 큐 |
| **평균 시간** | 사진 1장 1.5~2.5초 (Moondream2) · 영상 30초 9~15초 (대표 프레임 6장 + Whisper) |
| **메모리** | Ollama 풀 ~2.3GB 상주, 모델 동시 로드 가능 |
| **의존성** | Layer 1 완료 + 대표 자산 선별 |

---

#### Layer 3 — 등급 자동 판정

| 항목 | 내용 |
|---|---|
| **트리거** | Layer 2 완료 후 즉시 (n8n 순차) |
| **입력** | photo_classification 전체 컬럼 + similarity_group 정보 |
| **출력** | grade (8등급 중 하나) · confidence_score (0~1) |
| **처리 단계** | 1. **음식 분기 처리** (food_detected = true 그룹)<br>   - 그룹 내 pHash Hamming distance ≤ 6 → TRASH (중복 음식)<br>   - > 6 → FOOD<br>   - 그룹 내 가장 선명한 1장만 FOOD, 나머지 TRASH<br>2. **EVENT 점수 가산제** (일반 분기)<br>   - face_count ≥ 3 → +2<br>   - formal_dress = true → +1<br>   - event_objects ∩ {cake, flowers, stage, balloon, banner} 1개 이상 → +2<br>   - laplacian_variance > 300 → +1<br>   - voice_keywords 1개 이상 → +2 (영상만)<br>   - **합계 ≥ 4점 → EVENT 후보**<br>3. **유사컷 강등 (similarity_group 내)**<br>   - EVENT 후보 그룹: CLIP cosine ≥ 0.92 페어 발견 시 품질 낮은 쪽 → EVENT-L<br>   - BEST 후보 그룹: CLIP cosine ≥ 0.88 페어 발견 시 품질 낮은 쪽 → MEMORY+/MEMORY-<br>4. **BEST 선발** (EVENT 아닌 일반 자산)<br>   - similarity_group 내 가장 높은 (laplacian_variance × face_quality × exposure_score) → BEST<br>   - 나머지 → face_count ≥ 1 + quality ≥ 200 → MEMORY+<br>             face_count ≥ 1 + quality < 200 → MEMORY-<br>             face_count = 0 → NORMAL<br>5. **TRASH 판정**<br>   - laplacian_variance < 50 → TRASH<br>   - is_screenshot = true → TRASH (단 사용자 화이트리스트 예외)<br>   - 영상 길이 < 3초 → TRASH<br>   - 음식 중복 → TRASH (1번에서 처리)<br>6. **공유 EVENT 매칭**<br>   - `shared_candidate` 테이블에서 양 사용자 모두 EVENT 등급인 페어 추출<br>   - shared_event_album_queue 등록 (실제 앨범 생성은 Layer 5)<br>7. **confidence_score 산출**<br>   - 모든 신호의 일관성 점수 (예: face_count + scene_tags가 모두 행사 가리키면 0.9+) |
| **도구** | n8n Function 노드 (JS) + PostgreSQL CTE 쿼리 |
| **DB 변경** | `photo_classification.grade`, `confidence_score`, `is_event_candidate`, `shared_event_match_id` |
| **실패 처리** | 점수 계산 NULL → grade='UNCLASSIFIED', Layer 4 강제 큐 |
| **평균 시간** | 사진 1장 50ms (DB 쿼리 위주) |
| **idempotency** | 같은 자산 재실행 시 동일 결과 (입력 컬럼이 동일하면) |

---

#### Layer 4 — Vision API 보조 판단 (애매한 것만)

| 항목 | 내용 |
|---|---|
| **트리거** | 매일 03:00 cron → n8n #PHOTO-4 |
| **입력** | `photo_classification WHERE confidence_score < 0.6 OR grade = 'UNCLASSIFIED'` |
| **호출 한도** | 일일 ≤ 50건 AND 주간 ≤ $0.5 AND 자산 크기 ≤ 5MB (초과 시 skip 또는 다음날) |
| **모델** | Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) |
| **처리 단계** | 1. 호출 큐에서 confidence ASC 정렬, 일일 한도 만큼 추출<br>2. 자산 크기 > 5MB → ImageMagick 리사이징 (최장변 1920px)<br>3. **프롬프트 캐시** 활용<br>   - system: 8등급 정의 + few-shot 예시 (cache_control=ephemeral, 5분 TTL)<br>   - user: image + "이 사진의 등급은? EVENT/EVENT-L/BEST/FOOD/MEMORY+/MEMORY-/NORMAL/TRASH 중 정확히 하나로 답하시오. 신뢰도(1~10) 함께 출력. JSON 형식."<br>4. 응답 파싱 → grade + api_confidence (1~10)<br>5. **승인 조건**<br>   - api_confidence ≥ 7 → grade 갱신, vision_api_used=TRUE<br>   - < 7 → grade 유지 (Layer 3 결과), 사용자 검토 큐 등록<br>6. 비용 누적 (input/output token × 단가) → 주간 한도 모니터링 |
| **도구** | n8n HTTP Request 노드 + Anthropic API (anthropic-version: 2023-06-01) |
| **DB 변경** | `photo_classification.grade` 갱신, `vision_api_used=TRUE`, `api_confidence`, `api_cost_cents` |
| **실패 처리** | 5xx → 지수 백오프 3회 / 4xx → grade 유지 + 알림 / 한도 초과 → 다음날 큐 보존 |
| **평균 시간** | 호출 1건 ~3초 (네트워크), 일 50건 batch 약 5분 |
| **비용** | 1건 약 $0.0004, 일 50건 = $0.02, 월 ~$0.6 |
| **에스컬레이션 게이트** (KPI) | 사용자 수동수정률 ≥ 5% → Sonnet 4.6 escalation 도입 검토 (§17d) |

---

#### Layer 5 — 앨범 자동 배정

| 항목 | 내용 |
|---|---|
| **트리거** | 매일 **03:03** cron → n8n #PHOTO-5 (Layer 4 완료 직후, v3.7 03:00 일괄) |
| **입력** | photo_classification 당일 분류 결과 (grade != 'UNCLASSIFIED') |
| **출력** | Immich Album 멤버십 + **HDD 등급 폴더 이동** + cleanup_queue + shared_event_album |
| **처리 단계 (v3.7)** | 1. **사용자별 등급 앨범 배정** (Immich API)<br>   - 앨범 매핑: EVENT→"⭐EVENT", EVENT-L→"⭐EVENT-L", BEST→"✦BEST", FOOD→"🍽FOOD", MEMORY+→"◆MEMORY+", MEMORY-→"◇MEMORY-", NORMAL→"○NORMAL", TRASH→"🗑TRASH"<br>2. **★ HDD 등급 폴더 이동 (v3.7 신규, storage_service)**<br>   - 신규 자산: `library/<UUID>.jpg` → `library/{등급}/<UUID>.jpg`<br>   - 등급 변경 자산: `library/{old_grade}/<UUID>.jpg` → `library/{new_grade}/<UUID>.jpg`<br>   - mv 명령 (메타만 변경, 데이터 복사 0)<br>   - Immich originalPath UPDATE (트리거)<br>3. **공유 EVENT 앨범 매칭**<br>   - shared_event_album_queue에서 양 사용자 EVENT 페어 처리<br>   - 신규 공유 앨범 생성 (이름: §15.A LLM 자동 생성 "YYYY-MM-DD {장소·행사명}")<br>4. **cleanup_queue 등록** (기기 삭제 대상)<br>   - WHERE grade NOT IN ('EVENT', 'BEST') AND grade != 'UNCLASSIFIED' AND favorite = FALSE<br>   - cleanup_queue insert: asset_id, user, grace_until = NOW() + 24h<br>5. **TRASH 30일 카운터 시작**<br>   - photo_classification.trash_until = CURRENT_DATE + 30<br>6. **♥ cloud sync 큐 등록** (Layer 7 검증용)<br>   - grade IN ('EVENT', 'BEST') OR favorite = TRUE → cloud_sync_queue insert<br>7. **★ 뷰 갱신 트리거 (v3.7 신규, 03:08)**<br>   - storage_service.refresh_views() 호출<br>   - `행사별/`, `월별/`, `♥ 즐겨찾기/`, `음식/` 심볼릭 링크 재생성<br>   - 변경된 자산만 갱신 (incremental)<br>8. **Telegram 요약 발송** |
| **도구** | n8n HTTP Request + Immich API v1 + PostgreSQL |
| **DB 변경** | `cleanup_queue` insert, `cloud_sync_queue` insert, `shared_event_album` insert, `photo_classification.album_assigned_at` |
| **실패 처리** | Immich API 5xx → 재시도 5회 / 4xx → 알림 + 자산 ID skip |
| **평균 시간** | 일 분류 100~500장 처리 5~10분 |
| **race condition** | 양 사용자 분류 동시 진행 시 lock — `shared_event_album_queue` 처리는 03:30 단일 트랜잭션 |

---

#### Layer 6 — 기기 정리

| 항목 | 내용 |
|---|---|
| **트리거** | jw.son: iOS Shortcut Personal Automation (충전 시작 + Wi-Fi(home) + 03:30~05:30)<br>eunju: MacroDroid 매크로 #1 동일 조건 |
| **입력** | `cleanup-list API` 응답 = cleanup_queue WHERE grace_until < NOW() AND processed_at IS NULL |
| **출력** | 기기 사진앱에서 삭제 + cleanup_queue.processed_at 갱신 |
| **처리 단계** | **iOS (jw.son)**<br>1. Shortcut 트리거 → GET cleanup-list?user=jw.son<br>2. 응답 JSON 파싱 → asset_ids<br>3. Photos.framework `PHAssetChangeRequest.deleteAssets()`<br>4. → "최근 삭제된 항목" 이동<br>5. POST cleanup-result {deleted_count, failed_ids}<br><br>**Galaxy (eunju)** — MacroDroid 4 매크로<br>1. **#1**: cleanup-list GET → 변수 저장 → #2 트리거<br>2. **#2**: Loop → MediaStore 조회 → File Delete → MEDIA_SCANNER broadcast → #3 트리거<br>3. **#3**: cleanup-result POST → 알림 → #4 트리거<br>4. **#4**: backup-list GET → DCIM/PhotoSystemBackup/ 다운로드 → MEDIA_SCANNER (Galaxy Cloud 자동 동기화) |
| **도구** | iOS Shortcuts 17+ · MacroDroid 5.x 무료 · n8n Webhook |
| **DB 변경** | `cleanup_queue.processed_at`, `cleanup_queue.deleted_at_device`, `photo_classification.deleted_from_device_at` |
| **실패 처리** | iOS Shortcut 실패 → 푸시 알림으로 수동 트리거 / MacroDroid 매크로 실패 → 푸시 + 다음날 재시도 (3회) |
| **평균 시간** | 일 100장 삭제 약 1분 (네트워크 + 파일 시스템) |
| **단계적 활성화** | Phase 5 첫 주 일일 20장 → 둘째 주 100장 → 셋째 주 무제한 |
| **24h grace** | Layer 5 등록 후 24시간 내 ♥ → cleanup_queue.cancelled=TRUE → 처리 skip |

---

#### Layer 7 — 검증·피드백

| 항목 | 내용 |
|---|---|
| **트리거** | 매일 04:00 cron → n8n #PHOTO-6, 추가로 ♥ Webhook 실시간 |
| **입력** | photo_feedback, cloud_sync_queue, photo_classification |
| **출력** | KPI 리포트, 알림, 임계값 권장값 |
| **처리 단계** | 1. **♥ cloud sync 검증**<br>   - cloud_sync_queue WHERE created_at < NOW() - 24h AND verified = FALSE<br>   - iCloud (jw.son): Apple Photos API로 자산 존재 확인<br>   - Galaxy (eunju): MacroDroid #4 결과 로그 + Galaxy Cloud API 확인<br>   - 미동기화 → Telegram 알림 + 큐 재푸시<br>2. **사용자 피드백 집계**<br>   - photo_feedback 당일 row 분석<br>   - feedback_type별 카운트 (♥ 추가, 등급 수동변경, 휴지통 복구)<br>   - false positive 추정 = 등급 수동변경 / 전체 분류<br>3. **임계값 권장값 산출**<br>   - EVENT 점수 기준 4점 → false positive ≥ 5%면 5점 권장<br>   - CLIP cosine 0.92 → BEST 수동변경 패턴 분석<br>4. **KPI 리포트 작성** (주간 일요일 09:00)<br>   - 처리량, 변환 PASS/FAIL, 분류 분포, ♥ 추가율, 비용 |
| **도구** | n8n + PostgreSQL + Telegram Bot API |
| **DB 변경** | `cloud_sync_queue.verified`, `kpi_weekly` 테이블 |
| **실패 처리** | iCloud API 인증 실패 → 알림, 다음 시도 |
| **평균 시간** | 일배치 1~2분, 주간 리포트 5분 |
| **재학습 루프** | v3.2까지는 권장값 제시만, 자동 임계값 조정은 v3.3 이후 |

---

### 레이어 간 의존성 매트릭스

| Layer | 의존 (선행 필수) | 비동기 가능 | 동시실행 가능한 다른 자산 |
|---|---|---|---|
| Layer 0 | — | ✅ | ✅ (사용자별 병렬) |
| Layer 0.5 | Layer 0 PASS | ✅ | ✅ (자산별 병렬, 4 worker) |
| Layer 1 | Layer 0.5 PASS | ❌ (배치) | ✅ (자산별 병렬) |
| Layer 2 | Layer 1 완료 (similarity_group 확정) | ❌ | ⚠️ (Ollama 직렬, 1 worker) |
| Layer 3 | Layer 2 완료 (대표 분석) | ❌ | ✅ (DB 쿼리) |
| Layer 4 | Layer 3 완료 (UNCLASSIFIED 식별) | ❌ | ⚠️ (API rate limit) |
| Layer 5 | Layer 4 완료 (양 사용자 모두) | ❌ | ❌ (단일 트랜잭션) |
| Layer 6 | Layer 5 + 24h grace | ❌ | ✅ (사용자별 병렬) |
| Layer 7 | Layer 6 완료 + ♥ Webhook | ✅ | ✅ |

---

### 야간 배치 총 소요시간 추정 (일 500장 기준)

```
16:00  Layer 1 (전처리)      500장 × 0.2s × 1/4 worker = ~25s
       Layer 2 (콘텐츠)      대표 100장 × 2s + 영상 50개 × 12s = ~10m
       Layer 3 (등급)        500장 × 0.05s = ~25s
─────────────────────────────────────────────────────────
       소계                                              ~11m

03:00  Layer 4 (Vision)      50장 × 3s = ~2.5m
03:30  Layer 5 (앨범)        500장 → API + DB = ~5~10m
04:00  Layer 7 (검증)        ~2m
04:30  Layer 6 (정리)        100장 삭제 + 다운로드 = ~3m
─────────────────────────────────────────────────────────
       전체 새벽 배치                                    ~20m

총합: 야간 16:00 + 새벽 03:00~04:30 분산 ≈ 안전 (트레이딩 충돌 0)
```

---

## 6. 실행 스케줄 (v3.7 갱신 — 03:00 동기화 일괄)

> 사용자 정책: 모든 동기화 작업은 새벽 3시에 일괄 실행 (분석은 16:00 분리 유지)

### 6.1 분석 시간대 (16:00~)

| 시간 | 작업 | 소요 |
|---|---|---|
| 상시 | Layer 0 — Immich 업로드 (Wi-Fi+충전) | 사진 1장 1~3초 |
| 상시 | Layer 0.5 — 변환 (Webhook 트리거) | 이미지 50ms / 영상 30s~1m |
| 16:00~ | Layer 1~3 — 전처리·콘텐츠 분석·등급 판정 | 일 500장 ~30분 |

### 6.2 동기화 시간대 (03:00 일괄, ~13분) ⭐

| 시간 | 작업 | 소요 |
|---|---|---|
| **03:00** | Layer 4 — LLM 재분류 (애매한 것만, Qwen2.5-VL) | ~3분 |
| **03:03** | Layer 5 — Immich 앨범 + **HDD 등급 폴더 이동** + 큐 등록 | ~5분 |
| **03:08** | 뷰 갱신 — 행사별/♥/월별/음식 심볼릭 링크 재생성 | ~2분 |
| **03:10** | Layer 7 — ♥ 자산 클라우드 동기화 검증 | ~2분 |
| **03:12** | quarantine 7일 경과 자산 폐기 | ~1분 |
| 03:13 (일요일만) | 주간 reconciliation — FS↔DB 일치 검증 | ~5분 |

**03:00 윈도 종료**: 03:13 (일반) / 03:18 (주간)

### 6.3 기기 정리 윈도 (03:30~05:30)

| 시간 | 작업 | 트리거 |
|---|---|---|
| 03:30~05:30 | Layer 6 기기 정리 (iOS Shortcut / MacroDroid) | 충전+Wi-Fi(home) 조건 충족 시 |

기기 정리는 사용자 기기에서 트리거되므로 정확한 시간 제어 불가 → 윈도 시간대로 운영.

### 6.4 보고·리포트

| 시간 | 작업 |
|---|---|
| 매주 일요일 09:00 | 주간 KPI 리포트 Telegram (Qwen2.5-VL 자연어 요약) |
| 아침 기상 시 | 분류 요약: `jw.son 45장·eunju 38장 → 유지 N / HDD 보관 K` |

### 6.5 의존성·병렬화

```
Layer 4 → Layer 5 → 뷰 갱신 (등급 폴더 결정 후 심볼릭 링크 가능)
                   → Layer 7 (병렬 가능, 단 03:00 윈도 내 순차도 OK)
                   → quarantine 폐기 (독립, 백그라운드 가능)
```

전체 순차 ~13분. 병렬화는 **불필요** (단일 윈도 내 충분히 짧음).

### 6.6 트레이딩 시스템 충돌 회피

| 시간대 | 사진 시스템 | 트레이딩 시스템 |
|---|---|---|
| 09:00~15:30 | 비활성 (Layer 0 업로드만 패시브 수신) | 활성 (장중) |
| 16:00~23:00 | Layer 1~3 분석 | 비활성 |
| 23:00~03:00 | 휴면 | 비활성 |
| 03:00~03:13 | **동기화 일괄** | 비활성 |
| 03:30~05:30 | 기기 정리 (조건부) | 비활성 |
| 05:30~09:00 | 휴면 | 준비 |

**메모리 충돌 0**, **CPU 충돌 0** — 시간대 분리로 안전.

**사용자 최종 경험**

아무것도 안 해도 아침에 일어나면:
- jw.son iPhone: EVENT + BEST + ♥만 남음
- eunju Galaxy: EVENT + BEST + ♥만 남음 (DCIM/PhotoSystemBackup/에 클라우드 백업본)
- Immich 앱: 각자 폴더 + 공유 EVENT 앨범

---

## 7. Docker 서비스 구성

| 컨테이너 | 역할 | 비고 |
|----------|------|------|
| n8n | 트레이딩 13개 + 이미지 분류 + 변환 워크플로우 | 기존 + 확장 |
| PostgreSQL | 트레이딩 DB + 분류 로그 + feedback 테이블 | 기존 + 스키마 추가 |
| Redis | 캐시 | 기존 |
| immich-server | 사진 서버 · iPhone/Galaxy 자동 백업 | 신규 |
| immich-ml | 얼굴 인식 · CLIP 임베딩 · 유사도 | 신규 (CLIP cosine 임계값 활용) |
| immich-postgres | Immich 전용 DB | 신규 |
| immich-redis | Immich 전용 캐시 | 신규 |
| Ollama | **Qwen2.5-VL 7B Q4_K_M** + Whisper-small | 신규 (~5.0GB) |
| **media-converter** ⭐ | ffmpeg + ImageMagick + 변환 검증 스크립트 | 신규 (~0.4GB) — Layer 0.5 |
| Python | OpenCV · ffprobe · 분류 로직 · KPI 리포터 | 신규 (~0.5GB) |

**메모리 예상 (야간 분류 + 변환 동시 실행 기준)**

```
macOS                          3~4 GB
트레이딩 시스템 (유휴)           1~2 GB
Immich (4 컨테이너)             2~3 GB
Ollama (Qwen2.5-VL 7B + Whisper) ~5.0 GB
media-converter (ffmpeg 가동)   ~1.0 GB
Python                          ~0.5 GB
─────────────────────────────────────
합계                           10~13 GB ✅ 16GB 이내
```

**VideoToolbox**: macOS 컨테이너 GPU 가속은 Docker for Mac에서 제한적. → Python 컨테이너에서 호스트 ffmpeg 호출하는 방식으로 우회 (`docker run --rm -v ... ffmpeg-host`) 또는 호스트 launchd 작업으로 변환만 분리.

---

## 8. Immich 앱 접근 및 동기화

iPhone/Galaxy에서 삭제된 사진도 Immich 앱에서 원본 스트리밍으로 열람 가능하다.

- **집 안** (Wi-Fi): 맥미니 직접 연결
- **집 밖**: Tailscale VPN → 맥미니 → SSD/HDD 원본 스트리밍
- 각자 계정으로 로그인 → 본인 폴더만 기본 보기, 공유 앨범은 두 계정 모두 접근
- 앨범별 보기: EVENT / EVENT-L / BEST / FOOD / MEMORY+ / MEMORY- / NORMAL / ♥ / 공유 EVENT
- ♥ 지정 즉시 n8n Webhook → 클라우드 동기화 큐 등록
- **Tailscale ACL**: jw.son·eunju 디바이스만 화이트리스트 (수동 승인)

---

## 9. 구축 순서 (8-Phase, v3.3 갱신)

> v3.3에서 **Phase 0-LLM 신설** — 로컬 LLM 평가·설치를 사진 작업 진입 전 별도 검증

| Phase | 기간 | HDD | 핵심 |
|---|---|---|---|
| **0** 인벤토리 | 1일 | ❌ | 사진 총량·HEIC비율·SSD 가용량 측정 |
| **0-LLM** ⭐ 로컬 LLM | 2~3일 | ❌ | Ollama + Qwen2.5-VL 7B 설치 + 100장 벤치마크 |
| **1** 인프라 | 1~2일 | ❌ | SSD vault + Docker 슬립방지 |
| **2** Immich | 1일 | ❌ | 4컨테이너 설치, Phase 6 SQL dry-run |
| **3** 원본 수집 | 2~3일 | ❌ | iCloud/Galaxy 다운로드 → Layer 0.5 일괄 변환 |
| **4** 분류 자동화 | 1~2주 | ❌ | n8n 7워크플로우 + 14일 dry-run + 피드백 |
| **5** 실삭제 활성화 | 1주 | ❌ | iOS Shortcut + MacroDroid 4매크로 단계적 |
| **6** ⭐ HDD 마이그레이션 | 1일 | ✅ | rsync 2단계 + Postgres path 일괄치환 |
| **7** 운영·DR | 지속 | ✅ | SMART/용량 모니터, 주간 KPI, 재해복구 |


### Phase 0 — 사전 자산 인벤토리 (1일, HDD 불필요)

**목적**: 마이그레이션 가능 여부 정량 판단

| 작업 | 산출물 |
|---|---|
| iPhone/Galaxy 사진·영상 총 용량·개수 측정 | `inventory.json` |
| HEIC/HEVC/JPEG/MP4 비율 측정 | 변환 후 예상용량 산출 |
| iCloud 잔여 용량·다운로드 예상 시간 | 다운로드 plan |
| Galaxy Cloud 잔여 용량 | 백업 quota plan |
| SSD 가용공간 측정 | **임시 vault 상한 결정** |
| 트레이딩 시스템 메모리·디스크 baseline | 충돌 모니터링 기준선 |

**Gate**: 변환 후 예상용량 ≤ SSD 가용공간 70%. 초과 시 점진 다운로드 전략.

---

### Phase 0-LLM — 로컬 LLM 평가·설치 (2~3일, HDD 불필요, v3.3 신규)

**목적**: 사진 시스템 Layer 2/4 핵심 모델인 Qwen2.5-VL 7B의 M4 16GB 환경 실측 검증.

**Day 1 — 모델 다운로드·설치**
- Docker에 Ollama 컨테이너 추가 (사진 시스템 docker-compose에 통합)
- `ollama pull qwen2.5vl:7b-q4_K_M` (4.5GB, ~5~10분)
- `ollama pull whisper:small` (0.5GB)
- 메모리 사용량 측정 (idle / 추론 중 / 트레이딩 동시 가동 시)

**Day 2 — 정확도 벤치마크**
- 사용자 자체 사진 100장 샘플 (jw.son 50장 + eunju 50장)
- 8등급 분류 → CSV 저장
- 사용자 수동 라벨링 (groundtruth)
- 정확도·F1 score·confusion matrix 산출

**Day 3 — 속도·메모리·트레이딩 충돌 테스트**
- 100장 연속 처리 속도 측정
- 트레이딩 시스템 동시 가동 시 메모리 압박 측정 (`vm_stat` 모니터링)
- 스왑 발생 여부 (목표: ≤ 100MB)
- Ollama keep_alive 정책 결정 (기본 5분 유지)
- 트레이딩 응답 시간 영향 측정 (목표: ≤ 5%)

**합격 기준 (Go/No-Go)**

```
Tier 1 (Qwen2.5-VL 7B) Go 조건
- 8등급 분류 정확도 ≥ 80% (사용자 라벨 대비)
- 사진 1장 처리 시간 ≤ 6초
- 트레이딩 동시 가동 시 스왑 ≤ 100MB
- 트레이딩 응답 시간 영향 ≤ 5%

→ 모두 통과: Phase 1 진입
→ 일부 미달: Tier 2 (Qwen2.5-VL 3B Q4_K_M, 2.3GB) 재시도
→ Tier 2도 미달: Phase 0-LLM 보고서 작성, 사용자 결정 (Phase 진입 보류 또는 트레이딩 분리)
```

**산출물**
- `wiki/03-pdca/active/report/phase0-llm-benchmark.md` (또는 프로젝트 루트)
- 사진 100장 분류 결과 CSV + 정확도 통계
- 메모리·속도 그래프
- 최종 모델 선정 (Tier 1 또는 Tier 2)

자세한 모델 비교는 `local_llm_evaluation.md` 참조.

---

### Phase 1 — 기반 인프라 (1~2일, HDD 불필요)

**SSD 임시 vault 구조**

```
/Users/Shared/PhotoVault/
├── jw.son/
│   ├── library/           ← Immich 라이브러리 루트
│   └── upload/            ← Immich 업로드 임시
├── eunju/
│   ├── library/
│   └── upload/
├── shared/library/
├── _convert/
│   ├── work/              ← 변환 작업 중
│   └── quarantine/        ← 변환 후 7일 보관
│       └── YYYY-MM-DD/
└── _meta/
    ├── checksums/         ← Phase 6 마이그레이션 검증용 SHA256
    └── path-map.json      ← Phase 6 경로 변환 표
```

| 작업 | 검증 |
|---|---|
| `/Users/Shared/PhotoVault` 생성 + 권한 설정 | `df -h`, `ls -la` |
| Docker Desktop **File Sharing** 추가 | `docker run --rm -v` 마운트 테스트 |
| **Mac 슬립 방지** (`pmset` + `caffeinate` daemon) | `pmset -g` |
| **자동시작** (`launchd` 사용자 agent) | 재부팅 후 컨테이너 기동 |
| HDD 마운트 고정 경로 사전 정의 (`/Volumes/PhotoHDD`) | path-map.json에 기록 |
| **HDD 미연결 알림** — Phase 6 트리거 monitor 등록 | HDD 도착 시 자동 알림 |

---

### Phase 2 — Immich 설치 (1일, SSD 운영)

| 작업 | 핵심 옵션 |
|---|---|
| docker-compose에 Immich 4서비스 추가 | `UPLOAD_LOCATION=/Users/Shared/PhotoVault` |
| Immich Library Path = SSD 임시 경로 | Phase 6에서 변경 예정 |
| iPhone/Galaxy Immich 앱 자동 백업 연결 | Wi-Fi only, 충전 중만 |
| Tailscale + ACL 설정 | jw.son·eunju 디바이스만 |
| 사용자 격리 정책 | External Library별 owner 분리 |
| **Phase 6 마이그레이션 SQL 사전 작성·dry-run** | originalPath 일괄 치환 스크립트 |

**Phase 6용 SQL 사전 작성** (이 시점에 검증)

```sql
-- 마이그레이션 시 실행 (Phase 6 Step 4)
BEGIN;
UPDATE assets
SET "originalPath" = REPLACE("originalPath",
    '/Users/Shared/PhotoVault',
    '/Volumes/PhotoHDD/immich-media')
WHERE "originalPath" LIKE '/Users/Shared/PhotoVault%';

UPDATE assets
SET "encodedVideoPath" = REPLACE("encodedVideoPath",
    '/Users/Shared/PhotoVault',
    '/Volumes/PhotoHDD/immich-media')
WHERE "encodedVideoPath" LIKE '/Users/Shared/PhotoVault%';

-- sidecar, livePhoto 관련 path도 동시 처리
COMMIT;
```

---

### Phase 3 — iCloud/Galaxy 전환 + 원본 수집 (2~3일)

| 단계 | 작업 |
|---|---|
| 3a | iCloud "원본 다운로드" 모드 → 자동 다운로드 |
| 3b | Galaxy 원본 다운로드 (Smart Switch 또는 직접 USB) |
| 3c | SHA256 체크섬 기록 (`_meta/checksums/original/`) |
| 3d | 원본 → SSD 임시 vault로 사용자별 분기 이동 |
| 3e | **Layer 0.5 일괄 변환** (HEIC→JPEG, HEVC→H.264) — VideoToolbox 가속 |
| 3f | 변환 검증 (메타 일치, 디코딩 OK) → quarantine 7일 카운터 시작 |
| 3g | iCloud 사진 동기화 OFF |
| 3h | iCloud 요금제 다운그레이드 (50GB) — **EVENT+BEST 추정용량 ≤ 40GB 확인 후** |

**Gate**: SSD 사용률 ≥ 75% 도달 시 Phase 4로 강제 진행 (분류 후 일부 NORMAL은 외부 USB로 임시 백업).

---

### Phase 4 — 분류 자동화 + Dry-Run (1~2주)

**4a. n8n 워크플로우 구성**

- 워크플로우 #PHOTO-1: Layer 0 업로드 트리거 → Layer 0.5 변환 큐 등록
- 워크플로우 #PHOTO-2: Layer 0.5 변환 (변환 검증 포함)
- 워크플로우 #PHOTO-3: 야간 16:00 Layer 1~3 분류
- 워크플로우 #PHOTO-4: 03:00 Layer 4 Vision API 배치
- 워크플로우 #PHOTO-5: 03:30 Layer 5 앨범 배정 + 공유 EVENT 매칭
- 워크플로우 #PHOTO-6: 04:00 Layer 7 ♥ 클라우드 동기화 검증
- 워크플로우 #PHOTO-7: 06:00 quarantine 7일 경과 자동 삭제

**4b. PostgreSQL 스키마 추가**

```sql
CREATE TABLE photo_classification (
    id BIGSERIAL PRIMARY KEY,
    asset_id UUID NOT NULL,        -- Immich asset id
    user_account VARCHAR(20) NOT NULL,  -- 'jw.son' | 'eunju'
    grade VARCHAR(20) NOT NULL,    -- EVENT/EVENT-L/BEST/FOOD/...
    grade_score JSONB,             -- {face_count, formal_dress, ...}
    similarity_group_id BIGINT,
    clip_cosine_max NUMERIC(4,3),
    laplacian_variance NUMERIC(8,2),
    vision_api_used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_from_device_at TIMESTAMPTZ,
    cloud_synced_at TIMESTAMPTZ
);

CREATE TABLE photo_feedback (
    id BIGSERIAL PRIMARY KEY,
    asset_id UUID NOT NULL,
    feedback_type VARCHAR(20),  -- 'favorite_added' | 'grade_changed_manual' | 'restored_from_trash'
    old_grade VARCHAR(20),
    new_grade VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE photo_conversion_log (
    id BIGSERIAL PRIMARY KEY,
    original_path TEXT,
    converted_path TEXT,
    original_sha256 CHAR(64),
    converted_sha256 CHAR(64),
    metadata_match BOOLEAN,
    decoded_ok BOOLEAN,
    quarantine_until DATE,  -- 변환일 + 7일
    purged_at TIMESTAMPTZ
);
```

**4c. Dry-Run 단계** (사용자 신뢰 확보)

| 기간 | 동작 |
|---|---|
| Day 1~3 | 분류 결과 Telegram 요약만, 앨범 배정·삭제 없음 |
| Day 4~7 | Immich 앨범 배정 시작, 기기 삭제 보류 |
| Day 8~14 | "삭제 예정" 라벨만 부착, 사용자 검토 후 ♥/제외 가능 |
| Day 15~ | 실삭제 활성화 (Phase 5) |

**4d. 사용자 피드백 학습 루프**

- ♥ 추가, 등급 수동 변경 → `photo_feedback` 기록
- 주간 리포트: false positive/negative 비율, 임계값 권장값 제시
- 모델 재학습 v3.2로 이연 (수동 임계값 조정 충분)

---

### Phase 5 — 실삭제 단계적 활성화 (1주)

| 단계 | 동작 |
|---|---|
| 5a | iOS Shortcut + MacroDroid 매크로 4개 dry-run 1주 실행 |
| 5b | 24h grace period 적용 (분류 후 24h 내 ♥ 누르면 살림) |
| 5c | 첫 주 일일 삭제 상한 **20장** → 둘째 주 100장 → 무제한 |
| 5d | MacroDroid 실패율 ≥ 10% 시 게이팅 (재시도·수동 트리거) |

**iOS Shortcut 구성** (jw.son)

```
트리거: 충전 시작 + Wi-Fi(home SSID) + 03:30~05:30 시간대 (Personal Automation)

액션:
1. [Get Contents of URL] GET https://photo.tailscale-ip/api/cleanup-list?user=jw.son
   → Authorization: Bearer <token>
2. [Get Dictionary from Input] JSON 파싱 → cleanup_ids 배열
3. [Repeat with Each] cleanup_ids:
   3-1. [Find Photos] where ID matches Repeat Item
   3-2. [Delete Photos] (Recently Deleted로 이동)
4. [Get Contents of URL] POST .../api/cleanup-result
   {deleted_count, failed_ids}
5. [Show Notification] "사진 정리 완료 N장"
```

---

## 10. MacroDroid 매크로 상세 설계 (Galaxy / eunju)

**무료 버전 제약**: 매크로당 액션 5개 한도, 매크로 개수 5개 한도, Pro 트리거(정확한 시간 등) 불가.

**4개 매크로로 분할**. 모든 액션 무료 카테고리만 사용.

### 매크로 #1 — Cleanup List Fetch

**역할**: n8n에서 삭제 대상 사진 ID 목록 받아오기

**트리거** (모두 무료)
- "전원 / Power Connected" (충전 시작)
- AND "Wi-Fi 상태 / 특정 SSID에 연결됨" (home_wifi)
- AND "시간대 / Time of day Between 03:00~05:30"
  ※ "Time of Day Between"은 무료 카테고리 (Pro는 "Exact Time"만)

**액션** (5개 한도 준수, 4개 사용)
1. **HTTP Request (GET)**
   - URL: `https://photo.tailscale-ts/api/galaxy/cleanup-list?user=eunju`
   - Header: `Authorization: Bearer {{galaxy_token}}`
   - 응답을 변수 `cleanup_response`에 저장
2. **변수 설정** — `cleanup_status = "fetched"`, `cleanup_count` = JSON 배열 길이
3. **Trigger Macro** — 매크로 #2 호출
4. **Notification** — "정리 시작: {{cleanup_count}}장 대기"

### 매크로 #2 — File Delete Loop

**역할**: 사진 파일 삭제 + 미디어스캐너 broadcast

**트리거** (무료)
- "Macro Triggered" — 매크로 #1로부터 호출

**액션** (5개)
1. **변수 파싱** — `cleanup_response`(JSON 배열) → `cleanup_ids` 리스트
2. **Loop / While** — `cleanup_ids` 각 ID에 대해
3. **File Operation (Delete)** — MediaStore에서 ID로 path 조회 → 파일 삭제
4. **Send Broadcast** — `android.intent.action.MEDIA_SCANNER_SCAN_FILE` (갤러리 즉시 갱신)
5. **Trigger Macro** — 매크로 #3 호출 (deleted_count 변수 전달)

> **참고**: MacroDroid 무료 Loop는 "Loop Repeat N Times" 가능, 변수 기반 동적 루프도 무료. "While" 조건 루프는 일부 Pro 제한 있어 검증 필요 → Phase 5 dry-run에서 확인.

### 매크로 #3 — Result Report

**역할**: 결과를 n8n에 보고 + 매크로 #4 트리거

**트리거**
- "Macro Triggered" — 매크로 #2로부터 호출

**액션** (5개)
1. **HTTP Request (POST)**
   - URL: `https://photo.tailscale-ts/api/galaxy/cleanup-result`
   - Body (JSON): `{user: "eunju", deleted_count: {{deleted_count}}, failed_ids: {{failed_ids}}}`
2. **Notification** — "정리 완료: {{deleted_count}}장"
3. **로그 파일 추가** — `/sdcard/PhotoSystem/log.txt`에 timestamp + 결과 추가
4. **Trigger Macro** — 매크로 #4 호출 (백업 푸시 트리거)
5. (예비)

### 매크로 #4 — Cloud Backup Push (EVENT+BEST+♥ 갤럭시 푸시)

**역할**: Immich에서 EVENT+BEST+♥ 자산을 받아 DCIM/PhotoSystemBackup/에 저장 → Galaxy Cloud 자동 동기화

**트리거**
- "Macro Triggered" — 매크로 #3으로부터 호출

**액션** (5개)
1. **HTTP Request (GET)**
   - URL: `https://photo.tailscale-ts/api/galaxy/backup-list?user=eunju&since={{last_sync}}`
   - 응답 변수 `backup_list` (URL 배열)
2. **Loop** — `backup_list` 각 URL에 대해
3. **HTTP Request (Download)** — 파일을 `/sdcard/DCIM/PhotoSystemBackup/`에 저장
4. **Send Broadcast** — `MEDIA_SCANNER_SCAN_FILE` (갤러리 + Galaxy Cloud 자동 인식)
5. **변수 저장** — `last_sync` = 현재 timestamp (다음 실행 시 incremental)

### MacroDroid 시스템 설정 (필수)

- **삼성 절전모드 예외**: `설정 → 배터리 → 백그라운드 사용 제한 → MacroDroid 제외`
- **자동 시작 허용**: `설정 → 앱 → MacroDroid → 권한 → 자동 시작`
- **저장소 권한**: 모든 파일 액세스 (Android 11+ MANAGE_EXTERNAL_STORAGE)
- **알림 권한**: 매크로 실행 알림

### MacroDroid 검증 절차 (Phase 5)

| Day | 동작 | 합격 기준 |
|---|---|---|
| 1~3 | 매크로 #1~#3 dry-run (실삭제 비활성, 로그만) | 일일 1회 트리거 성공 ≥ 90% |
| 4~7 | 실삭제 활성 (일일 20장 한도) | 삭제 성공 ≥ 95%, 갤러리 즉시 반영 |
| 8~14 | 매크로 #4 백업 푸시 활성 | Galaxy Cloud 동기화 24h 내 100% |

실패율 ≥ 10% 시 → 푸시 알림으로 수동 트리거 요청 + Phase 5 종료 후 재검토.

---

## 11. 데이터 변환·보존 정책

### 변환 트랜잭션 (Layer 0.5)

```
[1] 입력 파일 SHA256 계산 → photo_conversion_log 기록
[2] /Users/Shared/PhotoVault/_convert/work/ 에서 변환
[3] 변환 출력 파일 SHA256 계산
[4] 메타데이터 검증 (EXIF/GPS 일치)
[5] 디코딩 검증 (출력 파일 정상 열림)
[6] 검증 PASS:
    - 출력 파일을 library/ 로 이동
    - 입력 파일을 quarantine/YYYY-MM-DD/ 로 이동
    - quarantine_until = 변환일 + 7일
    - photo_conversion_log 업데이트
[7] 검증 FAIL:
    - 출력 파일 폐기
    - 입력 파일은 library/ 에 그대로 (변환 없이 사용)
    - Telegram 알림: "{{filename}} 변환 실패 — 원본 유지"
```

### 7일 격리 자동 폐기 (매일 06:00)

```
SELECT * FROM photo_conversion_log
WHERE quarantine_until < CURRENT_DATE
  AND purged_at IS NULL;

→ 각 row의 quarantine 파일 삭제
→ purged_at = NOW() 업데이트
```

**예외**: 사용자가 7일 이내에 ♥를 눌렀거나 등급 수정한 자산의 원본은 추가 7일 연장.

### TRASH 30일 카운터

- Layer 5에서 TRASH 판정 시 `trash_until = 분류일 + 30일`
- 매일 06:00 배치: `trash_until < CURRENT_DATE` 항목 영구 삭제
- 사용자가 ♥ 누르면 trash_until = NULL + 등급 재분류 큐 등록

---

## 12. Phase 6 — HDD 마이그레이션 (HDD 도착 후, 무중단 1일)

**사용자 핵심 요청**: SSD 임시 vault → 외장 HDD로 무중단 이동, 모든 참조 링크 함께 이전.

### 6a. HDD 사전 준비

| 작업 | 검증 |
|---|---|
| HDD APFS 포맷 | `diskutil info /dev/diskX` |
| Spotlight 인덱싱 비활성 | `mdutil -i off /Volumes/PhotoHDD` |
| **마운트 고정 경로** `/Volumes/PhotoHDD` (UUID 기반) | 재부팅 후 동일 경로 |
| **자동 keepalive 데몬** — 5분마다 빈 파일 touch (USB3 슬립 방지) | `iostat`로 disk active 확인 |
| **SMART 모니터링** 등록 (smartctl daily) | 일일 검사 PASS |
| Docker File Sharing에 `/Volumes/PhotoHDD` 추가 | bind mount 테스트 |
| Phase 1에서 작성한 `path-map.json` 검증 | SSD/HDD 양쪽 경로 매핑 확인 |

### 6b. 무중단 마이그레이션 절차

```
Step 1  HDD 폴더 구조 생성
        /Volumes/PhotoHDD/immich-media/{jw.son,eunju,shared}/
        /Volumes/PhotoHDD/_convert/quarantine/
        /Volumes/PhotoHDD/_backup/  (DB 백업용)

Step 2  rsync 1차 (Immich 운영 중)
        rsync -aH --checksum --progress \
          /Users/Shared/PhotoVault/ \
          /Volumes/PhotoHDD/immich-media/
        → 수 시간 소요 (HDD 쓰기 속도 ~100MB/s 기준)

Step 3  Immich 일시 정지 (1차 완료 직후)
        docker compose stop immich-server immich-ml
        + n8n 야간 워크플로우 비활성

Step 4  rsync 2차 (delta만)
        같은 명령 재실행 → 5분 이내

Step 5  Immich Postgres originalPath 일괄 치환 (Phase 2에서 작성·dry-run한 SQL)
        → assets, exif, sidecar, livePhoto 모두 처리

Step 6  docker-compose UPLOAD_LOCATION + 볼륨 mount 변경
        - UPLOAD_LOCATION=/Volumes/PhotoHDD/immich-media
        - 볼륨: /Volumes/PhotoHDD/immich-media:/usr/src/app/upload

Step 7  n8n 워크플로우의 path 참조 일괄 치환
        migrate-paths.sh → path-map.json 기반 sed

Step 8  Immich 재시작 + 검증
        docker compose up -d
        - 무작위 50장 썸네일·원본 열람 OK
        - SHA256 체크섬 매치 (Phase 1 _meta/checksums)
        - n8n 분류 워크플로우 1건 end-to-end PASS

Step 9  SSD 임시 vault 보존 (7일 grace)
        검증 완료 후 /Users/Shared/PhotoVault 삭제
```

### 6c. 참조 링크 일괄 치환

`migrate-paths.sh` (Phase 2에서 사전 작성)

대상:
- macOS Finder 즐겨찾기 (`~/Library/Application Support/com.apple.sidebarlists.plist`)
- n8n 워크플로우 JSON (`docker exec` 후 SQL UPDATE)
- 사용자 작성 스크립트의 path 상수
- iOS Shortcut / MacroDroid은 서버 URL만 보므로 변경 불필요

---

## 13. Phase 7 — 운영·모니터링·재해복구

### 13a. 백업 체계

| 대상 | 1차 | 2차 | 빈도 |
|---|---|---|---|
| 원본 사진·영상 (전체) | HDD | **(없음)** | — |
| EVENT+BEST+♥ (jw.son) | HDD | iCloud 50GB | 자동 |
| EVENT+BEST+♥ (eunju) | HDD | Galaxy Cloud 15GB | 매크로 #4 일일 |
| Immich Postgres | SSD | HDD `_backup/immich/` | 일일 pg_dump |
| 트레이딩 Postgres | (기존) | HDD `_backup/trading/` | 기존 유지 |
| n8n 워크플로우 | Docker volume | git repo | 변경 시 |
| `photo_conversion_log` | SSD | HDD `_backup/conversion/` | 주간 |

### 13b. 모니터링·KPI

**일일 체크**
- HDD SMART (Reallocated_Sector_Count, Current_Pending_Sector ≥ 1 → 알림)
- HDD 용량 (≥ 80%: 알림 / ≥ 90%: 신규 업로드 차단)
- SSD 용량 (Phase 1~5 동안: ≥ 70% 알림)
- Vision API 일일 비용 ($0.05/일 초과 시 자동 차단)
- ♥ 자산 클라우드 동기화 미완료 건 (24h 내 미완료 → 알림)

**주간 KPI 리포트** (Telegram, 일요일 09:00)

```
📊 사진 분류 주간 리포트 (2026-04-26 ~ 2026-05-02)

처리량:
- 신규 자산: jw.son 234장 / eunju 187장
- 변환: HEIC→JPEG 312건 / HEVC→H.264 41건 (모두 PASS)
- 분류 완료: 421/421 (100%)

품질 지표:
- ♥ 추가율 (분류 후 7일내): EVENT 8% / BEST 12% / MEMORY+ 3%
- 등급 수동변경: 6건 (false positive 추정 1.4%)
- TRASH → 복구: 2건

비용:
- Vision API: $0.18 / 주간 한도 $0.5 (36%)

저장:
- HDD 사용률: 23% (228GB / 1TB) — 안정
- iCloud: 31GB / 50GB (62%)
- Galaxy Cloud: 9GB / 15GB (60%)

권장:
- BEST 임계값 0.88 → 0.90 완화 검토 (수동변경 패턴 분석)
```

### 13c. 재해복구 런북

| 시나리오 | RTO | 절차 |
|---|---|---|
| HDD 고장 | **불가** | 복원 가능 자산: iCloud 내 jw.son EVENT+BEST+♥ + Galaxy Cloud 내 eunju EVENT+BEST+♥ ※ NORMAL/MEMORY±/FOOD/EVENT-L 영구 손실 (사용자 인지·수용) |
| SSD 고장 | 1일 | TimeMachine 복원 → docker-compose 재기동 → DB는 HDD `_backup/`에서 |
| Postgres 손상만 | 4시간 | HDD `_backup/immich/` 최신 dump 복원 → 분류 결과 재구성 |
| Immich 손상 | 6시간 | docker volume 재생성 → 라이브러리 재스캔 → 얼굴 인식 재학습 (수일 소요) |

### 13d. 보안 (v3.5 갱신)

**가정용 위협 모델 기반 보안 정책**

- **Tailscale ACL**: jw.son·eunju 등록된 디바이스만 접근 + 분기별 토큰 회전
- **Immich 인증**: 16자+ 강력 비밀번호 + 분기 변경
- **두 사용자 격리**: External Library owner 분리 + E2E 테스트 검증
- **시크릿 관리**: `.env.gpg` (gpg 암호화 git 추적, gpg-agent 부팅 자동 복호화)
- **Image tag pinning**: docker-compose 모든 이미지 명시 버전, 우발 업그레이드 방지
- **분기별 취약점 스캔**: docker scan + pip-audit
- **공식 이미지만 사용**: Docker Hub 공식 organization
- **사진은 100% 로컬 처리**: 외부 Vision API 미사용 (v3.3에서 결정)

**⚠️ HDD 암호화 영구 미도입 정책 (2026-04-30 사용자 결정)**

- **결정**: APFS Encrypted Volume 도입 안 함
- **사유**:
  1. HDD는 가정 내부 보관용 — 분실·도난 위험 매우 낮음
  2. 암호화 시 USB3 외장 HDD I/O 성능 저하 (~10~20% 영향) 회피
- **수용 리스크**: HDD 분실·도난 시 사진·DB 평문 노출
- **물리 보안 대체**: HDD를 집 내부에 보관, 외부 반출 금지
- **이 결정은 향후 다시 논의하지 않음** — 운영 중 보안 검토에서도 재검토 안 함

자세한 보안 평가·개선 액션은 `architecture_review.md` §2.I + §8.3 참조.

---

## 14. 우려점 추적표 (총 33건)

### Critical (즉시 대응)

| # | 영역 | 이슈 | v3.1 대응 위치 |
|---|---|---|---|
| 1 | 인프라 | HDD 미연결 상태 운영 | §2, §9 Phase 0~5 (SSD 임시 vault) |
| 2 | 인프라 | HDD 단일 SPOF | §13a (사용자 인지·수용 명시), §13b (SMART 일일 검사) |
| 13 | 기기정리 | 즉시 자동삭제 위험 | §9 Phase 4 Dry-Run, §9 Phase 5 (24h grace + 단계 활성화) |

### High

| # | 영역 | 이슈 | v3.1 대응 |
|---|---|---|---|
| 3 | 인프라 | USB3 HDD 슬립 시 손상 | §12 6a (keepalive 데몬) |
| 4 | 인프라 | HDD SMART 모니터링 부재 | §13b 일일 검사 |
| 6 | 인프라 | SSD 가용공간 한계 | §2, §9 Phase 0 정량 측정 |
| 7 | 알고리즘 | 유사도 임계값 모호 | §4 (CLIP cosine 0.92/0.88, Laplacian 절대값) |
| 11 | 알고리즘 | 영상 처리 시간 낙관 | §5 (VideoToolbox 가속), §6 야간 윈도 |
| 14 | 기기정리 | iOS Shortcut 신뢰성 | §9 Phase 5 (재시도 + 수동 트리거 fallback) |
| 17 | 백업 | Postgres 백업 부재 | §13a 일일 pg_dump |
| 18 | 백업 | Immich DB 백업 부재 | §13a 일일 pg_dump |
| 19 | 백업 | 재해복구 런북 부재 | §13c |
| 23 | 보안 | Vision API 외부 전송 | §13d (모자이크 v3.2 이연), §4 (호출 상한) |
| 26 | 운영 | 초기 백필 전략 부재 | §9 Phase 3 (점진 다운로드) |

### Medium

| # | 이슈 | v3.1 대응 |
|---|---|---|
| 5 | iCloud 50GB quota 관리 | §13b 클라우드 용량 모니터링 |
| 8 | EVENT 자동판정 false positive | §4 점수 가산제 + §4d 피드백 루프 |
| 9 | Vision API 비용 폭주 | §4 (일일 50건 + 주간 $0.5 상한) |
| 10 | Whisper 모델 미정 | §5 Whisper-small 한국어 명시 |
| 12 | HEIC/Live Photo 처리 | §5 Layer 0.5 명시 |
| 15 | dry-run 부재 | §9 Phase 4 14일 단계 |
| 16 | Galaxy 자동화 도구 미정 | §10 MacroDroid 4개 매크로 명시 |
| 20 | 분류 정확도 KPI 없음 | §13b 주간 리포트 |
| 21 | HDD 용량 알림 없음 | §13b |
| 22 | 알림 채널 명세 없음 | §13b Telegram |
| 24 | Tailscale 인증 | §8 ACL 화이트리스트 |
| 25 | 사용자 격리 | §3 External Library owner 분리 |
| 27 | 피드백 학습 부재 | §9 Phase 4d 수동 임계값 조정 |
| 28 | TRASH 30일 카운터·복구 | §11 TRASH 30일, ♥ 복구 |

### v3.1 신규 우려점

| # | 이슈 | v3.1 대응 |
|---|---|---|
| 29 | JPEG 변환으로 용량 증가 | §9 Phase 0 변환 후 예상용량 산출 |
| 30 | HEVC→H.264 변환 시간 | §5 VideoToolbox 가속 |
| 31 | Live Photo 분리 시 종속관계 | §5 parent_asset_id |
| 32 | 변환 실패 시 손실 | §11 변환 트랜잭션 (FAIL 시 원본 유지) |
| 33 | 변환 산출물 EXIF 누락 | §11 메타 일치 검증 |

---

## 15. 의사결정 로그 (사용자 확정)

| 일자 | 결정 | 근거 |
|---|---|---|
| 2026-04-30 | 외부 cold storage 미도입, iCloud + Galaxy Cloud만 | 비용 vs 리스크 trade-off 수용 |
| 2026-04-30 | MacroDroid 무료 버전만 사용 | 단순성·비용 |
| 2026-04-30 | JPEG/H.264 변환 후 원본 7일 보관 후 폐기 | 호환성 우선, 용량 절약 |
| 2026-04-30 | Galaxy Cloud 단방향 푸시 (Immich → DCIM/Camera) | Galaxy Cloud는 DCIM만 자동 동기화 |
| 2026-04-30 | Phase 0~5는 SSD 임시 vault, Phase 6에서 HDD 마이그레이션 | HDD 미보유 |
| 2026-04-30 | iCloud 다운그레이드 = Phase 4 검증 후 (1주 분류 데이터로 EVENT+BEST 실측) | false positive 위험, quota 초과 방지 |
| 2026-04-30 | 백필 전략 = 점진 다운로드 + 즉시 분류 (최근→과거 4단계) | SSD 부담 분산, Vision API 한도 분산 |
| 2026-04-30 | Whisper-small 시작, KPI 기반 medium 승격 게이트 | 메모리 480MB로 충분, 한국어 88% |
| 2026-04-30 | Vision API = Haiku 4.5 only, 1개월 KPI 후 Sonnet escalation 검토 | 월 $1 미만 목표 충족 |
| 2026-04-30 | 글로벌 vs 프로젝트 설정 분리 — 프로젝트 고유 규칙은 `./CLAUDE.md` + `./.claude/` 내부 | git 추적, 외부 의존 최소화 |
| 2026-04-30 | **로컬 LLM 우선 정책** — 유료 Vision API 폐기 ($0/월) | 비용·프라이버시·확장성 |
| 2026-04-30 | **Qwen2.5-VL 7B Q4_K_M** 메인 모델 채택 (Layer 2 + Layer 4 단일 모델) | M4 16GB 가용 모델 중 벤치마크 1위, 한국어·영상·JSON 우위 |
| 2026-04-30 | Llama 3.2 Vision 11B 도입 안 함 | Qwen2.5-VL 7B 대비 모든 면에서 열위 (MMMU -7.9, image-only) |
| 2026-04-30 | Qwen2.5-Coder 도입 안 함, Claude Code 사용 | 코딩은 외부 구독 도구로 |
| 2026-04-30 | LM Studio MLX는 영상 자막 정밀 작업 시 선택 도입 | Whisper-large-v3 가속용 |
| 2026-04-30 | 로컬 LLM 확장 활용 7가지 도입 (앨범명·캡션·KPI 등) | Qwen2.5-VL 단일 모델 재활용, 비용 0 |
| 2026-04-30 | **HDD 암호화 영구 미도입** ⚠️ | 가정용 보관 + I/O 성능 영향 회피, 향후 재논의 안 함 |
| 2026-04-30 | HDD 용량 1TB 유지 | 현재 충분, 80% 도달 시 확장 검토 |
| 2026-04-30 | Postgres 도메인 분리 = `photo` schema (trading_postgres 내) | 메모리 절약, 인스턴스 추가 불필요 |
| 2026-04-30 | Redis Streams 도입 = Phase 1부터 | 사진 변환 큐 처음부터 backpressure·idempotency |
| 2026-04-30 | Loki 로그 통합 = Phase 1부터 (변경) | 9점+ 관측성 도달 위해 초기 도입 |
| 2026-04-30 | Outbox pattern = 단순 폴링 (1초) | Debezium은 과도, 가정용 시스템 적정 |
| 2026-04-30 | Golden dataset = 100장 (jw.son 50 + eunju 50) | 사용자 라벨링 부담 적정 |
| 2026-04-30 | 시크릿 관리 = `.env.gpg` (gpg + git) | 단일 호스트, 표준 도구 |
| 2026-04-30 | **시스템 성숙도 9.0/10 목표** (모든 차원 9점+) | architecture_review.md §8 로드맵 적용 |
| 2026-04-30 | **코드 구조 = §9.4 Clean Architecture 채택** | 16개 공용 로직 추출, 변경 영향 5~10배 축소 |
| 2026-04-30 | Python 패키지 도구 = **poetry** | pyproject.toml + lock file 표준 |
| 2026-04-30 | 코드 스타일·린트 = **ruff** | lint+format 통합, 빠름 |
| 2026-04-30 | 프롬프트 외부화 = **`prompts/*.md`** | git diff 가능, 9개 템플릿 |
| 2026-04-30 | n8n 워크플로우 두께 = **얇게** (orchestration only) | 로직은 Python, n8n은 HTTP+cron |
| 2026-04-30 | CI/CD = **GitHub Actions** | free tier, repo 통합 |
| 2026-04-30 | HDD 폴더 구조 = **옵션 D 하이브리드** (등급 1차 + 뷰 심볼릭) | Immich 죽어도 Finder에서 EVENT/BEST 식별 |
| 2026-04-30 | 등급 폴더 = 8개 (EVENT/EVENT-L/BEST/FOOD/MEMORY+/MEMORY-/NORMAL/TRASH) | 분류 등급과 1:1 |
| 2026-04-30 | 뷰 폴더 1차 카테고리 = `행사별/月별/♥/음식/` 4개 | 사용자 시각 다양성 |
| 2026-04-30 | 뷰 갱신 시점 = Layer 5 직후 (03:08) | 등급 폴더 확정 후 심볼릭 링크 |
| 2026-04-30 | 등급 변경 시 Immich External Library scan = 자동 | originalPath 자동 갱신 |
| 2026-04-30 | TRASH 30일 cleanup = 폴더 mtime + DB trash_until 이중 | 단순한 cron + 안전망 |
| 2026-04-30 | **모든 동기화 작업 03:00 일괄** | 사용자 정책, 분석은 16:00 유지 |
| 2026-04-30 | 16:00 분석 단계 분리 유지 | 시간 소요 (수 시간), 동기화와 성격 다름 |
| 2026-04-30 | Layer 6 기기 정리 시각 = 03:30~05:30 윈도 | 기기 트리거 한계, 정시 보장 불가 |
| 2026-04-30 | 동기화 단계 병렬화 = 안 함 (순차) | 13분 내 충분히 짧음 |

---

## 16. 기존 트레이딩 시스템 영향

이미지 분류 시스템은 트레이딩 시스템과 완전히 독립적으로 운영된다.

- ✅ 유지: 트레이딩 n8n 워크플로우 13개 전체
- ✅ 유지: PostgreSQL·Redis 기존 구성 및 트레이딩 DB 스키마
- ✅ 유지: 트레이딩 Telegram 봇 및 승인 구조
- ➕ 추가: docker-compose에 Immich 4개 서비스
- ➕ 추가: Ollama·media-converter·Python 컨테이너
- ➕ 추가: n8n 이미지 분류 워크플로우 (#PHOTO-1 ~ #PHOTO-7)
- ➕ 추가: 분류 로그 / feedback / conversion_log 3개 테이블

> 트레이딩 장중 (09:00~15:30)에는 분류 파이프라인을 실행하지 않아 리소스 충돌 없음. 변환(Layer 0.5)은 업로드 즉시 트리거되므로 장중에도 가동될 수 있으나 CPU/RAM 영향 미미 (~1GB).

---

## 17. 확정 의사결정 상세계획 (v3.2 신규)

### 17a. iCloud 50GB 다운그레이드 시점

**결정**: Phase 4 분류 1주 후 EVENT+BEST 실측 → 검증 통과 시 다운그레이드

**근거**: Phase 3 즉시 다운그레이드 시 false positive로 EVENT가 과다하면 50GB 부족 위험. 1주 실측이 안전.

**상세 절차**

```
Phase 3e   iCloud 사진 동기화 OFF (요금제는 200GB 유지)
           원본 다운로드 완료 후 SSD vault 이전

Phase 4 Day 1~7    분류 1주 진행 (Layer 1~5)
                   → photo_classification 테이블에서 EVENT+BEST 용량 집계
                   → SQL: SUM(file_size) WHERE grade IN ('EVENT','BEST') AND user='jw.son'

Phase 4 Day 8      검증 게이트
                   ├ EVENT+BEST ≤ 30GB (50GB의 60%) → 다운그레이드 OK
                   ├ 30~40GB → 1주 추가 관찰 후 재평가
                   └ > 40GB → ♥ 우선순위 quota 정책 도입 후 재측정

Phase 4 Day 9      다운그레이드 실행 (Apple ID → 요금제 변경)

D+30  첫 한 달 누적 추세 확인
      월평균 EVENT+BEST 증가량 산출 (예: 1GB/월)

D+90  Quota 자동화 도입 (필요 시)
      → 가장 오래된 BEST 중 ♥ 없는 것부터 iCloud에서만 제거 (HDD는 유지)
```

**Quota 초과 방지 정책**
- iCloud 사용률 ≥ 80%: Telegram 알림
- ≥ 90%: Layer 7 워크플로우가 자동으로 BEST(♥ 없음, 1년 이상 경과) 우선 cloud-only 제거
- 사용자 수동 ♥ 시 즉시 cloud 재업로드

---

### 17b. 초기 백필 전략 — 점진 다운로드 + 즉시 분류

**결정**: 4단계 점진 다운로드, 각 단계마다 변환·분류 완료 후 다음 단계 진입

**근거**:
- 일괄 다운로드 시 SSD 가용공간 70% 초과 위험
- Vision API 일일 50건 한도를 분산 처리
- Phase 6 HDD 도착 전 일부 자산은 외부 USB 임시 백업 가능

**Throughput 추정** (M4 mini 기준)

| 작업 | 처리량 |
|---|---|
| iCloud 다운로드 | ~10MB/s (네트워크 의존) |
| HEIC → JPEG | ~50ms/장 (1만장 ≈ 8분) |
| HEVC → H.264 (1분 영상) | ~30s (VideoToolbox) |
| Moondream2 분석 | ~2s/장 (1만장 ≈ 5.5h, 야간 배치 충분) |

**4단계 백필 일정**

```
Stage 1 (Day 1~2)  최근 1년 (~50GB 가정)
                   → 다운로드 5h + 변환 30m + 분류 야간 1회
                   → Vision API: 일 50건 (가장 애매한 것만)

Stage 2 (Day 3~5)  1~3년 전 (~100GB)
                   → 다운로드 10h + 변환 1h + 분류 야간 1~2회
                   → Vision API: 일 50건 × 2일

Stage 3 (Day 6~8)  3~5년 전 (~80GB)
                   → 동일 패턴

Stage 4 (Day 9~)   5년 이전 (잔여)
                   → 동일 패턴

각 Stage 종료 시 검증
- SSD 사용률 ≤ 70% (초과 시 NORMAL 등급은 외부 USB 임시 백업)
- Vision API 누적 비용 ≤ $0.5 (월 한도)
- 분류 오류율 ≤ 5%
```

**SSD 부담 완화** (HDD 도착 전)
- 변환 quarantine 7일 보관 폴더는 외장 USB 256GB 임시 활용 가능
- Stage 종료 시점에 NORMAL/MEMORY-는 외장 USB로 이전 → Phase 6에서 HDD로 통합

---

### 17c. Whisper 모델 — small 시작 + KPI 기반 medium 승격

**결정**: Whisper-small (한국어) 시작, 1개월 운영 KPI 기반 medium 승격 여부 판단

**모델 비교**

| 모델 | 메모리 | 한국어 정확도 | M4 처리속도 |
|---|---|---|---|
| tiny | 75MB | ~70% | 매우 빠름 |
| base | 150MB | ~80% | 빠름 |
| **small** ⭐ | 480MB | ~88% | 보통 |
| medium | 1.5GB | ~93% | 느림 |
| large | 3GB | ~95% | 매우 느림 |

**근거**:
- 영상은 전체 자산의 ~10% 추정 → Whisper 부하 작음
- "생일 축하/건배/박수/사랑해" 같은 짧은 키워드는 small로도 충분
- EVENT 점수 가산제에서 음성 키워드는 2점 (총 4점 중) → 다른 신호로 보완 가능
- 메모리 480MB → 트레이딩 시스템 영향 미미

**승격 게이트** (Phase 4 종료 시 KPI 평가)

```
KPI: 영상 EVENT 자동판정 중 음성 키워드 감지율
- ≥ 30%: small 유지
- 15~30%: small 유지 + 키워드 사전 확장 (예: "케이크 자르자", "결혼 축하해")
- < 15%: medium 승격 검토
       → 메모리 +1GB 여유 확인
       → 트레이딩 시스템 동시 실행 시 충돌 테스트
       → 통과 시 medium 다운로드 + 1주 dry-run
```

---

### 17d. Vision API 모델 — 로컬 LLM 완전 대체 (v3.3 갱신)

**결정**: 유료 Vision API 사용 안 함. **Qwen2.5-VL 7B (로컬, Layer 2와 동일 모델 재사용)** 으로 Layer 4 처리.

**근거**:
- 사용자 정책 — 로컬 LLM 최대 활용, 비용 0, 프라이버시 100%
- Qwen2.5-VL 7B는 M4 16GB 가용 모델 중 벤치마크 1위 (MMMU 58.6, MMBench 83)
- 한국어·영상·JSON 모두 SOTA급
- Layer 2와 동일 모델 → 메모리 추가 0, 운영 단순

**호출 정책 (v3.3)**

```
조건:
- Layer 2 신뢰도 < 0.6 자산만 Layer 4 큐 등록
- Layer 2와 다른 정교한 프롬프트로 재분류
  · system: 8등급 상세 정의 + few-shot 예시 5건
  · user: 이미지 + "이 사진은 EVENT/EVENT-L/BEST/FOOD/MEMORY+/MEMORY-/NORMAL/TRASH 중 어느 등급인가?
          신뢰도 1-10과 함께 JSON으로 답하시오."
- 일일 호출 수 무제한 (로컬, 비용 0)
- 자산 크기 무제한 (로컬, 네트워크 무관)

응답 처리:
- 신뢰도 ≥ 7: grade 갱신
- 신뢰도 < 7: grade 유지 + 사용자 검토 큐 (Telegram 알림)
```

**비용 (v3.2 vs v3.3)**

| 항목 | v3.2 (Claude Haiku) | v3.3 (로컬 Qwen) |
|---|---|---|
| 월 비용 | $0.6 | **$0** ⭐ |
| 일일 한도 | 50건 | 무제한 |
| 프라이버시 | 사진 외부 전송 | 100% 로컬 |
| 정확도 (MMMU) | ~92% (Haiku) | ~88% (Qwen 7B) |

**정확도 부족 시 대응 (게이트)**

```
KPI: Layer 4 후 사용자 수동수정률 (= false positive 추정)
- < 5%: Qwen2.5-VL 7B 유지
- 5~10%: 프롬프트 개선 (few-shot 예시 확대) + 임계값 조정
- ≥ 10%: 더 큰 로컬 모델 (InternVL3 8B Q4 5GB) 검토
         → 트레이딩 메모리 감축 가능 시 도입
         → ⚠️ Claude API 도입은 영구 제외 (사용자 정책)
```

자세한 평가·벤치마크는 `local_llm_evaluation.md` 참조.

---

## 18. 기기 삭제 시점 플로우 (v3.2 신규)

> 사용자 질문: 아이폰/갤럭시에서 사진·영상이 정확히 언제 사라지는가?

### 18a. 타임라인 (단일 자산 기준)

```
T+0           [촬영]
              사용자가 iPhone/Galaxy로 사진·영상 촬영

T+1~10분      [Layer 0: Immich 자동 백업]
              조건: Wi-Fi 연결 + 충전 중 (Immich 앱 설정)
              → 원본이 SSD vault `upload/` 폴더로 들어옴
              → 이 시점 기기에는 아직 원본 그대로 존재

T+10~30분     [Layer 0.5: 미디어 변환]
              HEIC → JPEG / HEVC → H.264
              → library/ 폴더로 이동
              → 변환 원본은 _convert/quarantine/ 7일 보관
              → 기기에는 영향 없음

T = 16:00     [Layer 1~3: 분류 (당일 저녁)]
              트레이딩 장 마감 후 야간 배치
              → 흐림·유사도·콘텐츠 분석
              → 등급 자동 판정 (EVENT/BEST/MEMORY±/NORMAL/FOOD/TRASH)
              → 기기에는 영향 없음

T = 다음날 03:00  [Layer 4: Vision API (애매한 것만)]

T = 03:30     [Layer 5: 앨범 배정 + 삭제 큐 등록]
              → photo_classification.deleted_from_device_at = NULL
              → 24시간 grace period 시작 (★ 사용자 ♥ 누를 시간)
              → 기기에는 영향 없음

T = 03:30~03:30+24h  [24h Grace Period]
              사용자가 Immich 앱에서 ♥ 누르면:
              → 등급이 ♥로 승격
              → 삭제 큐에서 제거
              → 기기 보존 + 클라우드 자동 백업

T = 다음다음날 03:30  [Grace 종료]
              ♥ 없으면 삭제 대상 확정
              → cleanup-list API에 등록

T = 다음다음날 04:30  [Layer 6: 기기 정리 ★ 실제 삭제 시점]
              조건: 충전 시작 + Wi-Fi(home) + 03:00~05:30
              jw.son: iOS Shortcut 자동 트리거
              eunju: MacroDroid 매크로 #1 트리거
              → cleanup-list GET → grace 종료 자산 ID 응답
              → 기기에서 Photos 앱 / 갤러리에서 삭제
              → "최근 삭제된 항목" (Recently Deleted)으로 이동

T = 삭제 + 30일  [iOS/Galaxy 자체 영구삭제]
              iPhone/Galaxy의 Recently Deleted 휴지통 30일 정책
              → 기기에서 영구 제거
              → 단, Immich 서버에는 여전히 존재 (영구 보관 등급) 또는 TRASH 30일 후 삭제
```

### 18b. 플로우 다이어그램

```
                          ┌─────────────────┐
                          │   [촬영]        │  T+0
                          │  iPhone/Galaxy  │
                          └────────┬────────┘
                                   │ Wi-Fi+충전
                                   ▼
                          ┌─────────────────┐
                          │ Immich 자동백업 │  T+1~10m
                          │   (Layer 0)     │
                          └────────┬────────┘
                                   ▼
                          ┌─────────────────┐
                          │   미디어 변환   │  T+10~30m
                          │  (Layer 0.5)    │  HEIC→JPEG
                          └────────┬────────┘  HEVC→H.264
                                   ▼
                          ┌─────────────────┐
                          │ 원본 quarantine │  변환 후
                          │    7일 보관     │  (검증 PASS 시)
                          └────────┬────────┘
                                   │ 7일 후 자동 폐기
                                   ▼ (또는 ♥ 시 영구보관)
                                   X

         ─────────────  [당일 저녁 16:00]  ─────────────

                          ┌─────────────────┐
                          │  분류 파이프    │
                          │  (Layer 1~3)    │  품질·유사도·콘텐츠
                          └────────┬────────┘
                                   ▼
         ─────────────  [익일 새벽 03:00]  ─────────────
                          ┌─────────────────┐
                          │  Vision API     │  애매한 것만
                          │  (Layer 4)      │  Haiku 4.5
                          └────────┬────────┘
                                   ▼
         ─────────────  [익일 새벽 03:30]  ─────────────
                          ┌─────────────────┐
                          │ 앨범 배정 + 큐  │
                          │  (Layer 5)      │
                          └────────┬────────┘
                                   ▼
                          ┌─────────────────┐
                          │  ★ 24h GRACE   │  ← 사용자가 ♥ 누를 시간
                          │     PERIOD      │
                          └────────┬────────┘
                                   │
                       ┌───────────┴───────────┐
                       ▼                       ▼
              ┌─────────────────┐    ┌─────────────────┐
              │   사용자 ♥     │    │  Grace 종료     │
              │  (Immich 앱)    │    │  (♥ 없음)       │
              └────────┬────────┘    └────────┬────────┘
                       ▼                       ▼
              ┌─────────────────┐    ┌─────────────────┐
              │ 등급 ♥로 승격   │    │ 삭제 큐 확정    │
              │ 클라우드 백업   │    │ cleanup-list 등록│
              │ 기기 영구 보존  │    └────────┬────────┘
              └─────────────────┘             │
                                              │
         ─────────────  [익익일 새벽 04:30]  ─────────────
                                              ▼
                          ┌─────────────────────────────┐
                          │  ★★ 기기 정리 (Layer 6)    │
                          │  조건: 충전+Wi-Fi+03~05시  │
                          ├─────────────────────────────┤
                          │ jw.son: iOS Shortcut 트리거 │
                          │ eunju:  MacroDroid #1 트리거│
                          │   → GET cleanup-list        │
                          │   → 사진 앱에서 삭제        │
                          │   → Recently Deleted 이동   │
                          └────────────┬────────────────┘
                                       │
                          ┌────────────┴────────────┐
                          ▼                         ▼
                ┌─────────────────┐       ┌─────────────────┐
                │ Recently Deleted│       │ Immich 서버     │
                │  (기기 휴지통)  │       │ (HDD 영구보관)  │
                └────────┬────────┘       └─────────────────┘
                         │ 30일 후                  │
                         ▼                          │
                ┌─────────────────┐                 │
                │ iOS/Galaxy 영구 │                 │
                │   영구 삭제     │                 │
                └─────────────────┘                 │
                                                    │ TRASH 등급은
                                                    │ 30일 후 삭제
                                                    ▼
                                          ┌─────────────────┐
                                          │ HDD 영구 삭제   │
                                          │ (TRASH만)       │
                                          └─────────────────┘
```

### 18c. 삭제까지 최소·최대 시간

| 시나리오 | 촬영 → 기기에서 삭제까지 |
|---|---|
| **최단** (당일 16시 직전 촬영) | 약 **36~37시간** (16:00 분류 → 익일 03:30 큐 → 24h grace → 다음 04:30 삭제) |
| **최장** (16시 직후 촬영) | 약 **60시간** (다음날 16:00 분류 → 24h grace → 그다음 04:30 삭제) |
| **♥ 누른 경우** | **삭제 안 됨**, 영구 보존 + 클라우드 백업 |
| **충전+Wi-Fi 미충족** | 조건 충족 시까지 무기한 지연 (재시도) |

### 18d. 삭제 안 되는 케이스 (의도적)

1. **EVENT/BEST 등급** — 처음부터 cleanup-list에 등록되지 않음, 기기 영구 보존
2. **♥ 표시** — grace 기간 내 ♥ 누르면 등급 ♥로 승격, 삭제 큐 제거
3. **기기 충전 안 함 + Wi-Fi 안 잡힘** — Layer 6 트리거 미발화 → 다음날 재시도
4. **iOS Shortcut/MacroDroid 실패** — 3회 재시도 → 실패 시 사용자에게 푸시 알림으로 수동 트리거 요청
5. **Phase 4 dry-run 기간** — Day 1~14는 분류만, 삭제 큐 등록 안 함
6. **Phase 5 단계적 활성화** — 첫 주 일일 20장 한도, 둘째 주 100장, 셋째 주~ 무제한

### 18e. 사용자 안전망 (잘못 삭제 시 복구)

```
[기기에서 삭제 후 30일 이내]
  iPhone Recently Deleted / Galaxy 휴지통에서 복원 가능
  → 단, 분류 시스템은 다시 삭제 큐에 등록할 것이므로
    Immich 앱에서 ♥ 표시 필수

[기기 30일 경과 후]
  Immich 앱에서 원본 스트리밍 열람 가능 (저장공간 0)
  → ♥ 표시 시 클라우드 + 기기로 자동 재백업
  → iCloud/Galaxy Cloud quota 영향

[HDD에서 TRASH 30일 경과 후]
  영구 삭제 (복구 불가능)
  → 단, iCloud/Galaxy Cloud에 ♥ 또는 EVENT/BEST로 백업된 자산은 잔존
```

---

## 19. 마이그레이션 파이프라인 — 현재 보관 사진 (v3.4 신규)

> 5년치 기존 사진을 시스템에 진입시키는 일회성 흐름. Phase 3에서 실행.

### 19.1 전체 마이그레이션 흐름

```
┌──────────────────────────────────────────────────────────────┐
│  iPhone (jw.son)              Galaxy (eunju)                 │
│  ├─ Photos.app                ├─ DCIM/Camera                 │
│  ├─ iCloud (200GB)            ├─ Samsung Cloud (15GB)        │
│  └─ Live Photo · HEIC · HEVC  └─ Motion Photo · HEVC · DNG  │
└────────────┬─────────────────────────────┬──────────────────┘
             │ Step 1                      │ Step 1
             ▼                             ▼
   ┌─────────────────────┐       ┌─────────────────────┐
   │ A1. iCloud 다운로드  │       │ B1. USB 직접 추출   │
   │  Photos.app 원본 모드│       │  MTP 모드 + rsync   │
   │  ~10MB/s, 3~10시간  │       │  ~50MB/s, 1~3시간   │
   └──────────┬──────────┘       └──────────┬──────────┘
              ▼                              ▼
   ┌─────────────────────┐       ┌─────────────────────┐
   │ A2. osxphotos export│       │ B2. 갤럭시 메타 정리│
   │  메타 보존 + 검증    │       │  Bixby/Pro RAW 분리 │
   └──────────┬──────────┘       └──────────┬──────────┘
              ▼                              ▼
   ┌──────────────────────────────────────────────────┐
   │ Step 2 — SHA256 체크섬 기록                      │
   │ _meta/checksums/{user}/manifest.csv             │
   │ filename, size, sha256, exif_datetime, gps_lat/lon│
   └──────────────────┬───────────────────────────────┘
                      ▼
   ┌──────────────────────────────────────────────────┐
   │ Step 3 — SSD vault 사용자별 분기                 │
   │ /Users/Shared/PhotoVault/{user}/upload/          │
   └──────────────────┬───────────────────────────────┘
                      ▼
   ┌──────────────────────────────────────────────────┐
   │ Step 4 — Layer 0.5 일괄 변환 (병렬 4 worker)    │
   │  HEIC→JPEG (sips) + HEVC→H.264 (videotoolbox)   │
   │  Live Photo 분리 + parent_asset_id              │
   │  변환 검증 + quarantine 7일                     │
   └──────────────────┬───────────────────────────────┘
                      ▼
   ┌──────────────────────────────────────────────────┐
   │ Step 5 — Immich 라이브러리 import               │
   │ External Library 스캔 → DB 등록                 │
   └──────────────────┬───────────────────────────────┘
                      ▼
   ┌──────────────────────────────────────────────────┐
   │ Step 6 — 4단계 점진 분류 (§17b 백필 전략)        │
   │  Stage 1: 최근 1년 → Layer 1~7                  │
   │  Stage 2: 1~3년 전 → Layer 1~7                  │
   │  Stage 3: 3~5년 전 → Layer 1~7                  │
   │  Stage 4: 5년+ → Layer 1~7                      │
   └──────────────────────────────────────────────────┘
```

### 19.2 iPhone (jw.son) 추출 상세

**A1. iCloud 원본 다운로드 (Photos.app)**

```
[전제] iPhone에 macOS와 같은 Apple ID 로그인

설정 절차:
1. macOS → 사진 앱 → 환경설정 → iCloud
2. "iCloud 사진 보관함" 활성
3. "Mac에 원본 다운로드" 선택
   ※ "Mac 저장공간 최적화"가 아님!
4. 다운로드 자동 시작
5. 진행 상황: 사진 앱 하단 progress bar

체크 포인트:
- 사진 수 일치 확인 (iPhone 설정 → 사진 → 사진 N장)
- 디스크 사용량 모니터링 (df -h)
- 다운로드 완료 후 "최적화" 모드 OFF 확인
```

**A2. osxphotos export (메타 보존 추출)**

```bash
# 도구 설치
pip install osxphotos

# 사용자 라이브러리 → SSD vault로 export
osxphotos export /Users/Shared/PhotoVault/jw.son/upload/ \
  --library "~/Pictures/Photos Library.photoslibrary" \
  --download-missing \
  --use-photos-export \
  --exiftool \
  --convert-to-jpeg --jpeg-quality 0.95 \
  --live-photo \
  --sidecar XMP \
  --update \
  --report ~/PhotoVault/_meta/checksums/jw.son/export_report.csv

# 옵션 설명:
# --download-missing:      iCloud 미동기화 자산 강제 다운로드
# --use-photos-export:     Photos.app 공식 export API (메타 100% 보존)
# --exiftool:              EXIF/GPS/Make/Model 검증
# --convert-to-jpeg:       HEIC → JPEG 사전 변환 (q=95)
# --live-photo:            Live Photo .MOV 페어 별도 export
# --sidecar XMP:           XMP 사이드카 (편집 정보 보존)
# --update:                재실행 시 incremental
# --report:                CSV 리포트 (Step 2 입력)
```

**A3. iPhone 특화 메타 처리**

| 항목 | 처리 |
|---|---|
| Live Photo (.HEIC + .MOV 페어) | osxphotos가 자동 페어로 export, parent_asset_id로 연결 |
| HEIC depth map | 변환 시 무시 (JPEG는 depth 미지원) |
| ProRAW (.DNG) | DNG → JPEG 변환 (`sips -s format jpeg`) |
| ProRes (.MOV, 4K HDR) | H.264 변환 시 비트레이트 ≥ 12M 권장 (HDR→SDR 변환) |
| Burst (연사 묶음) | 모두 개별 export → similarity_group으로 묶임 |
| 편집 사진 | 원본 + 편집본 둘 다 export, 편집본만 분류 진입 |
| 스크린샷 | EXIF Make=Apple, Model=null로 식별 → Layer 1에서 자동 TRASH |

### 19.3 Galaxy (eunju) 추출 상세

**B1. USB 직접 연결 (권장)**

```
[전제] Galaxy 개발자 모드 OFF, 일반 사용자 모드

절차:
1. USB-C 케이블 연결 (Mac mini)
2. Galaxy: USB 사용 → "파일 전송 / Android Auto" 선택
3. macOS Finder에 Galaxy 디바이스 표시 안 됨 (MTP 한계)
4. Android File Transfer 또는 OpenMTP 설치
   brew install --cask openmtp
5. OpenMTP에서 DCIM/Camera 폴더 확인
6. SSD vault로 복사:
   - 5만장 기준 1~3시간
   - 진행 모니터링 (OpenMTP 자체)
7. 복사 완료 후 SHA256 검증
```

**B2. 갤럭시 특화 메타 처리**

| 항목 | 처리 |
|---|---|
| Single Take (.HEIC + 별도 .MP4) | 같은 prefix 파일명으로 페어 매칭, parent_asset_id |
| Motion Photo (.JPG with embedded MP4) | ffmpeg로 motion 부분 추출 (`-c:v copy -an output.mp4`) |
| Pro 모드 RAW (.DNG) | DNG → JPEG 변환 |
| Bixby Vision XMP 태그 | 무시 (사진 시스템과 충돌하지 않음) |
| HDR10+ 영상 | H.264 SDR 변환 (HDR 메타 손실, 시청 호환성 우선) |
| Slow Motion (240fps) | 30fps 표준 변환 (재생 속도 정상화) |
| Hyperlapse | 그대로 보존 (이미 압축됨) |

**B3. Samsung Cloud 다운로드 (보조 방법)**

```
USB 직접이 실패할 경우 fallback:
1. Samsung Cloud 웹 (cloud.samsung.com) 로그인
2. 갤러리 → 모두 선택 → 다운로드
3. ZIP 파일로 받음 (15GB 한도)
4. 압축 해제 후 SSD vault 이동
※ 메타데이터 일부 손실 가능 (Single Take 페어 분리)
```

### 19.4 Step 4 — Layer 0.5 일괄 변환

```
입력: SSD vault upload/ 폴더의 원본 자산
도구: media-converter Docker 컨테이너 + 호스트 ffmpeg (VideoToolbox)
병렬: 4 worker (M4 8코어 중 4 점유)

처리 큐 (FIFO):
1. 코덱 판별 (ffprobe)
2. 분기 처리:
   - 이미지 (HEIC/JPEG): sips + exiftool
   - 영상 (HEVC/MOV/MP4): ffmpeg + h264_videotoolbox
   - Live Photo (HEIC+MOV): 분리 후 각각 처리
   - DNG (RAW): sips DNG → JPEG
3. 변환 검증:
   - SHA256 출력
   - EXIF DateTimeOriginal/GPSLatitude/Longitude/Make/Model 일치
   - 디코딩 OK (ffmpeg null muxer)
4. PASS:
   - library/ 이동
   - 입력 quarantine/YYYY-MM-DD/{user}/ 이동
   - quarantine_until = 변환일+7
   - photo_conversion_log insert
5. FAIL:
   - 출력 폐기, 입력 library/에 그대로
   - Telegram 알림 (filename, error)

추정 시간 (5만장 기준):
- 이미지 4만장 × 50ms = 33분
- 영상 1만개 × 30s 평균 = 5시간 (4 worker 병렬 → 1.25시간)
- 합계: 약 2시간
```

### 19.5 Step 5 — Immich External Library Import

```
Immich Web UI:
1. Administration → External Libraries
2. "Add library" → owner 선택 (jw.son)
3. Import Path: /usr/src/app/external/jw.son/library
   (Docker volume: /Users/Shared/PhotoVault/jw.son/library)
4. Refresh → 자산 스캔 시작
5. 약 10분/만장 (메타 추출 + 썸네일 생성)
6. eunju도 동일 절차

검증:
- Immich 자산 수 = SSD library 폴더 파일 수
- 무작위 50장 썸네일·원본 열람 확인
```

### 19.6 Step 6 — 4단계 점진 분류 (Phase 4)

```
백필 전략 (§17b)

Stage 1: 최근 1년 (~10000장)
  Day 1-2: 16:00 야간 배치 가동 → Layer 1~5 처리
  Day 3:   Layer 6 dry-run (실삭제 X)
  Day 4-7: 사용자 검증 (♥ 추가, 등급 수동변경 패턴 확인)
  → KPI 합격 시 Stage 2 진입

Stage 2: 1~3년 전 (~15000장)
  Day 8-11: 야간 배치 4회로 분할 (일 5000장)
  Day 12:   사용자 검증

Stage 3: 3~5년 전 (~12000장)
  유사

Stage 4: 5년+ (잔여 ~13000장)
  유사

총 백필 기간: 약 4주 (Phase 4 dry-run 14일 포함)
```

---

## 20. 상시 파이프라인 — 촬영 이후 (v3.4 신규)

> Phase 4 안정화 후, 매일 신규 사진·영상에 적용되는 흐름.

### 20.1 트리거 조건 매트릭스

| 시점 | 조건 | 모니터링 |
|---|---|---|
| **촬영 직후** | 기기 사진앱에 저장 (즉시) | 없음 |
| **백업 트리거** | (Wi-Fi=home AND 충전중 AND Immich 앱 활성) | Immich Server 로그 |
| **변환 트리거** | Immich `AssetUploaded` Webhook | n8n queue depth |
| **분류 트리거** | 매일 16:00 cron (당일 신규 자산) | n8n executions |
| **Vision API (로컬) 트리거** | 매일 03:00 (UNCLASSIFIED 큐) | Ollama 큐 depth |
| **앨범 배정 트리거** | 매일 03:30 (Layer 4 완료 후) | n8n executions |
| **♥ 검증 트리거** | 매일 04:00 (cloud_sync_queue) | iCloud/Galaxy Cloud API |
| **기기 정리 트리거** | (충전 시작 AND Wi-Fi(home) AND 04:30~05:30) | iOS Shortcut / MacroDroid 로그 |

### 20.2 단일 신규 사진 상세 흐름

```
T+0     [iPhone/Galaxy 촬영]
        EXIF: DateTimeOriginal, GPS, Camera Make/Model

T+0~5분  [Immich 앱 백그라운드 동기화 감지]
        조건 충족 시 청크 업로드 시작
        실패 시: 큐 보존, 다음 동기화 시 재시도

T+5~30초 [Immich Server 수신]
        - SHA256 검증 (서버 측)
        - assets DB row insert
        - exif DB row insert
        - 썸네일 생성 (백그라운드)
        - AssetUploaded 이벤트 발행

T+30초~10분 [n8n #PHOTO-1 워크플로우]
        - 사용자 폴더 분기 확인
        - 파일 코덱 확인
        - 변환 큐 등록 (Redis Stream)

T+10분~30분 [media-converter Layer 0.5]
        - 큐 pop → 변환 → 검증 → 라이브러리 이동
        - photo_conversion_log insert
        - quarantine 7일 카운터

T = 16:00 (당일 저녁)
        [n8n #PHOTO-3 야간 분류 배치]
        - 당일 신규 자산 SELECT
        - Layer 1 → 2 → 3 순차

T = 03:00 (익일 새벽)
        [n8n #PHOTO-4 Layer 4 배치]
        - confidence < 0.6 자산 재분류
        - Qwen2.5-VL 7B 로컬 추론

T = 03:30
        [n8n #PHOTO-5 앨범 배정 + 큐 등록]
        - Immich Album API
        - cleanup_queue insert (24h grace)
        - cloud_sync_queue insert (♥/EVENT/BEST)

T = 03:30~04:30+24h [24h Grace Period ★]
        사용자 ♥ 시 → 등급 ♥ 승격 + cleanup 취소
        없으면 → 삭제 대상 확정

T = 04:00 (그날 새벽 04:00, 다음 밤 04:00이 아님)
        [n8n #PHOTO-6 클라우드 검증]
        - cloud_sync_queue 24h 미확인 알림

T = 04:30 (다음다음날)
        [Layer 6 기기 정리]
        - iOS Shortcut / MacroDroid 트리거
        - 기기 사진앱에서 삭제
        - cleanup_queue.processed_at 갱신

T+30일  [기기 Recently Deleted 자체 영구삭제]

T+30일  [TRASH 등급의 경우 HDD 영구삭제]
```

### 20.3 동시성·idempotency

| 시나리오 | 처리 |
|---|---|
| 같은 자산 두 번 업로드 | Immich SHA256 중복 검출 → 신규 row 생성 안 함 |
| 분류 중복 실행 (n8n 재시도) | photo_classification.created_at unique 제약 + UPSERT |
| 사용자 ♥ → 동시에 cleanup_queue 처리 | ♥ webhook이 cleanup_queue.cancelled=TRUE 즉시 마킹, Layer 6은 cancelled=FALSE만 처리 |
| Layer 0.5 변환 중 Immich 재스캔 | external library는 SHA256 기반, 임시 파일은 .partial 접미사로 무시 |
| 양 사용자 같은 행사 분류 동시 | shared_event_album_queue insert는 Postgres advisory lock |

### 20.4 사용자 개입 지점

| 지점 | UI | 효과 |
|---|---|---|
| Immich 앱 ♥ | 사진 꾹 누르기 | 등급 ♥로 승격, cleanup 취소, 클라우드 강제 백업 |
| Immich 앱 등급 변경 | 앨범 이동 | photo_feedback 기록, 다음 분류 임계값 권장값에 반영 |
| Telegram 자연어 질의 (§15c) | "지난주 EVENT 보여줘" | n8n + Qwen → Immich API → 결과 응답 |
| Telegram 알림 응답 | "삭제 보류 N장" 알림 | 답장으로 grace 연장 가능 |

---

## 21. 영상 특화 처리 (v3.4 신규)

영상은 이미지 대비 3가지 추가 도전 (코덱 다양성·길이·음성). v3.3까지 추상화로만 다뤘던 부분을 구체화.

### 21.1 코덱·해상도·프레임레이트 매트릭스

| 입력 코덱 | 출처 | 변환 정책 (Layer 0.5) |
|---|---|---|
| HEVC (H.265) | iPhone 4K 기본 | h264_videotoolbox 8M |
| H.264 | 갤럭시 4K, 호환 | 그대로 (재인코딩 skip 가능, 단 컨테이너 mp4로 통일) |
| ProRes 422 | iPhone Pro 4K | h264_videotoolbox 12M (HDR→SDR 변환 포함) |
| AV1 | 일부 안드로이드 12+ | h264_videotoolbox 8M (호환성 우선) |
| MJPEG | 구형 갤럭시 | h264_videotoolbox 6M |

| 해상도 | 변환 후 | 비고 |
|---|---|---|
| 720p | 720p H.264 | 그대로 |
| 1080p | 1080p H.264 | 그대로 |
| 4K (3840×2160) | 1080p 다운스케일 H.264 | 분류 분석은 1080p 충분, 저장 절약 |
| 4K HDR | 1080p SDR H.264 | HDR 메타 손실 수용 |

| 프레임레이트 | 변환 후 |
|---|---|
| 24/30fps | 그대로 |
| 60fps | 그대로 (스포츠·모션) |
| 120fps Slow Motion | 30fps로 변환 (재생 속도 정상화 또는 보존 옵션) |
| 240fps Slow Motion | 30fps로 변환 |
| Time-lapse | 그대로 (이미 압축) |

### 21.2 Live Photo / Motion Photo 처리

```
입력: HEIC + MOV 페어 (iPhone) 또는 JPG with embedded MP4 (Galaxy)

처리 단계:
1. 페어 식별
   - iPhone: 같은 prefix (IMG_1234.HEIC + IMG_1234.MOV)
   - Galaxy: JPG embedded MP4 → ffmpeg로 motion 부분 추출

2. 정지 이미지 변환
   - HEIC → JPEG (q=95)
   - asset_id = N (Immich 자산 등록)

3. 모션 영상 변환
   - MOV → H.264 mp4 (3초 내외)
   - asset_id = N+1
   - parent_asset_id = N
   - DB 컬럼: assets.parent_id (Immich 확장 또는 메타 컬럼)

4. UI 표시
   - Immich UI는 parent 자산만 갤러리에 표시
   - 클릭 시 Live Photo 재생 (motion 자동 로드)

5. 분류 처리
   - parent (이미지)만 Layer 1~3 분석
   - motion (영상)은 부속 자산으로 등급 상속
   - "꾹 누르면 움직이는 사진" UX 보존
```

### 21.3 영상 분석 파이프라인 (Layer 1~2 영상 분기)

```
┌─────────────────────────────────────────────────────┐
│ 영상 입력 (변환 완료, library/*.mp4)                │
└────────────────────┬────────────────────────────────┘
                     ▼
   ┌─────────────────────────────┐
   │ Layer 1.v1: 영상 메타 추출   │
   │ ffprobe -show_streams        │
   │ → duration, bitrate, fps     │
   └─────────────────┬─────────────┘
                     ▼
   ┌─────────────────────────────┐
   │ Layer 1.v2: 길이 분기        │
   ├─────────────────────────────┤
   │ < 3초     → 즉시 TRASH        │
   │ 3~30초    → 표준 분석         │
   │ 30s~5분   → 5초 간격 샘플     │
   │ > 5분     → 30초 간격 샘플    │
   └─────────────────┬─────────────┘
                     ▼
   ┌─────────────────────────────┐
   │ Layer 1.v3: 흔들림 점수      │
   │ 5프레임 추출 → Laplacian     │
   │ → 평균 variance 산출         │
   └─────────────────┬─────────────┘
                     ▼
   ┌─────────────────────────────┐
   │ Layer 1.v4: 무음 판별        │
   │ ffmpeg -af "volumedetect"    │
   │ → mean_volume < -50dB → 무음  │
   │ → Whisper skip               │
   └─────────────────┬─────────────┘
                     ▼
   ┌─────────────────────────────┐
   │ Layer 2.v1: 대표 프레임 분석 │
   │ Qwen2.5-VL 7B 영상 직접 입력 │
   │ (또는 프레임 샘플 일괄 분석) │
   └─────────────────┬─────────────┘
                     ▼
   ┌─────────────────────────────┐
   │ Layer 2.v2: 음성 추출·인식   │
   │ ffmpeg -vn -ac 1 -ar 16000   │
   │ → Whisper-small 한국어        │
   │ → 키워드 매칭                │
   └─────────────────┬─────────────┘
                     ▼
                Layer 3 (등급 판정, 점수 가산제)
```

### 21.4 프레임 샘플링 전략 (해상도 의존)

```
4K 영상 (3840×2160):
  ffmpeg로 1080p 다운스케일 → 5초 간격 추출
  → Qwen2.5-VL에 1024×576 리사이징 입력 (모델 최적 크기)

1080p 영상:
  720p 다운스케일 → 5초 간격 추출

720p 이하:
  원본 해상도 → 5초 간격 추출

추출 명령 예:
ffmpeg -i input.mp4 -vf "fps=1/5,scale=1024:-1" \
  -frames:v 6 output_%03d.jpg

→ 30초 영상에서 6장 샘플 → Qwen에 batch 입력
```

### 21.5 음성 처리 흐름

```
ffmpeg -i input.mp4 -vn -ac 1 -ar 16000 \
  -c:a pcm_s16le audio.wav

[무음 사전 검사]
ffmpeg -i input.mp4 -af "volumedetect" -f null /dev/null 2>&1 \
  | grep mean_volume

mean_volume ≥ -50dB:
  → Whisper-small 입력
  → 한국어 인식 결과 텍스트
  → 키워드 매칭:
    ["생일", "축하", "건배", "박수", "사랑해", "결혼",
     "케이크 자르자", "건배해", "박수쳐", "메리크리스마스",
     "새해 복", "추카포카", "환갑", "돌잔치"]
  → 매칭 1개 이상 → EVENT 점수 +2

mean_volume < -50dB:
  → 무음 처리
  → voice_keywords = []
  → Whisper 호출 skip (시간 절약)
```

### 21.6 영상 처리 시간 추정

```
30초 1080p H.264 영상 1개:
  ffprobe                  0.1s
  무음 검사                 0.5s
  프레임 추출 (6장)         1.5s
  Qwen2.5-VL 분석 (6장 batch)  4~8s
  Whisper-small (음성)     1.5s
  Layer 3 등급 판정         0.05s
  ─────────────────────────────
  소계                     8~12s

30초 4K H.264 (1080p 다운스케일 후 분석):
  소계                     12~18s

5분 영상:
  ffprobe                  0.5s
  무음 검사                 1.5s
  프레임 추출 (10장, 30s 간격)  3s
  Qwen2.5-VL (10장 batch)  10~15s
  Whisper-small (5분)      30s
  ─────────────────────────────
  소계                     45~50s
```

**일 영상 100개 (평균 30초) 기준 야간 배치 시간**: 약 15~20분 (단일 worker), 4 worker 병렬 시 5분.

### 21.7 영상 EVENT 판정 특이 케이스

| 케이스 | 처리 |
|---|---|
| 음성만 있고 화면 단조로움 (대화 영상) | voice_keywords 1+ → EVENT, 화면 분석은 face_count만 |
| 화면 풍부하지만 무음 (Time-lapse 풍경) | scene_clarity 점수만, NORMAL 또는 BEST |
| 짧은 클립 (3~5초, 박수·환호) | 음성 핵심 → EVENT 가능 |
| 영상 길이 동일 + 음성·화면 동일 (재촬영) | similarity_group_id로 묶임, 1개만 EVENT |

---

*이 문서는 v3.7 FINAL. Phase 0 + Phase 0-LLM 인벤토리 완료 후 실측치 반영하여 v3.8로 갱신 예정.*
*관련 문서:*
- *`local_llm_evaluation.md` (v1.3 FINAL) — 모델 평가·벤치마크 정량 비교*
- *`architecture_review.md` (v1.4 FINAL) — 아키텍처 평가 + 우려점 33건 + 9.0/10 도달 로드맵 + 코드 구조 §9.4 + storage_service*
