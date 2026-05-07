# GitHub Copilot 설정 가이드 (사용자 SDLC 시스템 이식)

Claude Code의 SDLC 시스템과 동일한 워크플로우를 GitHub Copilot에서 사용하기 위한 설정 가이드.

---

## 적용 범위

| 레이어 | 위치 | 적용 범위 |
|---|---|---|
| **글로벌 SDLC** | `~/.copilot/sdlc/*.md` | 모든 프로젝트 (VS Code 사용자 설정) |
| **프로젝트 SDLC override** | `.github/copilot-instructions.md` | 이 프로젝트만 (자동 로드) |
| **파일 패턴별 룰** | `.github/instructions/*.instructions.md` | applyTo 패턴 매칭 시 |
| **사용자 정의 명령** | `.github/prompts/*.prompt.md` | `/명령어`로 호출 |

---

## 1단계: 사전 요구사항

### IDE 버전
- **VS Code**: 1.95 이상 (`.github/instructions/`, `.github/prompts/` 지원)
- **JetBrains**: 최신 Copilot 플러그인 (instructions 부분 지원)

### Copilot 플랜
- **Copilot Pro 권장** (Claude 3.5 Sonnet / o1 사용 위해)
- 무료 플랜은 GPT-4o 자동완성만

### 확인 명령

```bash
code --version    # VS Code 버전
ls ~/.copilot/    # 글로벌 SDLC 파일 존재 확인
ls ~/Work/photo_system/ai-photo-system/.github/  # 프로젝트 instructions 확인
```

---

## 2단계: VS Code 사용자 설정 (글로벌 SDLC 적용)

### 2-1. settings.json 열기

`Cmd+Shift+P` → `Preferences: Open User Settings (JSON)`

### 2-2. instructions 배열 추가

```jsonc
{
  // ... 기존 설정 ...

  // ─────────────────────────────────────────────
  // GitHub Copilot SDLC 글로벌 설정 (모든 프로젝트 공통)
  // ─────────────────────────────────────────────

  "github.copilot.chat.codeGeneration.instructions": [
    { "file": "/Users/jw-home/.copilot/sdlc/sdlc-core.md" },
    { "file": "/Users/jw-home/.copilot/sdlc/model-routing.md" },
    { "file": "/Users/jw-home/.copilot/sdlc/deploy-protocol.md" },
    { "file": "/Users/jw-home/.copilot/sdlc/commit-protocol.md" }
  ],

  "github.copilot.chat.commitMessageGeneration.instructions": [
    { "file": "/Users/jw-home/.copilot/sdlc/commit-protocol.md" }
  ],

  "github.copilot.chat.testGeneration.instructions": [
    { "text": "TC-First 원칙: EXPECTED → 구현 → ACTUAL → PASS. 한국어 한 줄 의도 주석. pytest 권장." }
  ],

  "github.copilot.chat.reviewSelection.instructions": [
    { "file": "/Users/jw-home/.copilot/sdlc/sdlc-core.md" }
  ],

  "github.copilot.chat.pullRequestDescriptionGeneration.instructions": [
    { "file": "/Users/jw-home/.copilot/sdlc/commit-protocol.md" }
  ],

  // (선택) Copilot 인라인 자동완성에도 적용
  "github.copilot.advanced": {
    "contextualFilters": false
  }
}
```

> **중요**: `~/`는 일부 환경에서 미해석 — 절대 경로 (`/Users/jw-home/...`) 사용.

### 2-3. VS Code 재시작

`Cmd+Q` → 다시 열기. 또는 Command Palette → `Developer: Reload Window`.

---

## 3단계: 프로젝트 자동 로드 확인

이 프로젝트(`ai-photo-system`)는 이미 `.github/copilot-instructions.md`가 있어 **자동 로드**됨.

검증:

```
1. ai-photo-system 폴더에서 VS Code 열기
2. Copilot Chat 사이드바 열기 (⌃⌘I 또는 Activity Bar)
3. 입력: "@workspace 이 프로젝트의 8등급 분류는?"
```

응답에 `BEST / EVENT / EVENT-L / FOOD / MEMORY+ / MEMORY- / NORMAL / TRASH` 언급되면 정상.

---

## 4단계: 모델 선택 (요청 유형별)

VS Code Copilot Chat 입력창 좌하단 **모델 선택기** 클릭:

| 요청 유형 | 권장 모델 | 비용 (Pro) |
|---|---|---|
| 단순 자동완성, 1줄 변경 | **GPT-4o** | 무제한 |
| 코드 리뷰, 리팩터링 (1-4 파일) | **Claude 3.5 Sonnet** | 1× |
| 큰 코드베이스 검색·요약 | **GPT-4.1** | 1× |
| 알고리즘 설계, 깊은 추론 | **o1** | 1× |
| 단순 텍스트 작업 (저비용) | **Gemini 2.0 Flash** | 0.25× |

자동 라우팅 가이드: `~/.copilot/sdlc/model-routing.md` 참조.

---

## 5단계: 사용자 정의 명령 (Slash Commands)

이 프로젝트의 `.github/prompts/`에 다음 명령이 등록됨:

| 명령어 | 용도 | 호출 |
|---|---|---|
| `/plan` | EXECUTION BRIEF 작성 (PLAN 단계) | Copilot Chat에서 `/plan` |
| `/review` | 도메인 안전 + 보안 + Alignment 리뷰 | `/review` |

새 명령 추가: `.github/prompts/{name}.prompt.md` 생성. 자동 등록.

---

## 6단계: 키보드 단축키 (생산성)

| 단축키 | 기능 |
|---|---|
| `Cmd+I` | Inline Chat (현재 줄에 적용) |
| `Cmd+Shift+I` | Edit 모드 (다중 파일 수정) |
| `Ctrl+Cmd+I` | Copilot Chat 사이드바 |
| `Cmd+L` | 코드 선택 → Chat 전송 |
| `Ctrl+Enter` | 자동완성 패널 열기 |
| `Tab` | 자동완성 수락 |
| `Esc` | 자동완성 거부 |

---

## 7단계: 검증 (E2E)

다음 시나리오로 SDLC 통합 검증:

### 7-1. PLAN 단계
```
Copilot Chat 입력:
/plan task="cleanup_photos_mac.py에 dry-run summary 옵션 추가"
```

기대: FAST-VERIFY 분류, GPT-4o 라우팅, 파일 목록 명시, TC 가이드.

### 7-2. 도메인 안전 자동 승격
```
/plan task="TRASH 자산을 영구 삭제 자동화"
```

기대: DEEP-ARCHITECT 자동 승격, o1/Claude 권장, PRD 작성 요구.

### 7-3. 리뷰
선택 후 `/review` 명령. 검증 항목 6가지 체크리스트 출력 확인.

### 7-4. 커밋 메시지 자동 생성
Source Control 사이드바 → 변경 stage → ✨ 클릭. `feat:`, `fix:` 등 type 형식 준수 확인.

---

## 8단계: 프로젝트별 추가 (다른 프로젝트로 확장)

다른 프로젝트에 동일 시스템 적용:

```bash
PROJECT=/path/to/other/project

# 글로벌 SDLC는 이미 적용됨 (VS Code 사용자 설정)
# 프로젝트 단위 instructions만 복사:

mkdir -p $PROJECT/.github/instructions $PROJECT/.github/prompts

# 템플릿 복사 (각 프로젝트에 맞게 편집 필수)
cp ~/Work/photo_system/ai-photo-system/.github/copilot-instructions.md \
   $PROJECT/.github/copilot-instructions.md
cp ~/Work/photo_system/ai-photo-system/.github/instructions/sdlc-core.instructions.md \
   $PROJECT/.github/instructions/

# 프로젝트별 도메인 룰은 새로 작성
$PROJECT/.github/instructions/{project-name}.instructions.md
```

---

## 트러블슈팅

### Q1. instructions 적용이 안 되는 것 같음
- VS Code 1.95+ 확인
- 설정 JSON 문법 오류 (`Cmd+Shift+P` → `Developer: Reload Window`)
- 절대 경로 사용 (`~/` 미해석 환경 있음)

### Q2. `/명령어`가 보이지 않음
- `.github/prompts/{name}.prompt.md` 파일 frontmatter 확인:
  ```yaml
  ---
  mode: 'agent'
  description: '...'
  ---
  ```
- VS Code 1.95+ 필요. 미만은 작동 X.

### Q3. JetBrains에서 instructions 미작동
- JetBrains Copilot 플러그인은 `.github/copilot-instructions.md`만 인식 (2026-05 기준)
- `.github/instructions/`, `.github/prompts/` 미지원
- JetBrains는 핵심 룰을 `copilot-instructions.md`에 통합 권장

### Q4. Premium request 한도 초과
- `~/.copilot/sdlc/model-routing.md` 예산 가이드 참조
- GPT-4o 우선 사용 (무제한)
- Claude/o1는 SAFE-REVIEW/DEEP-ARCHITECT만 사용

### Q5. 한국어 응답이 안 나옴
- instructions에 "한국어로 답변" 명시 추가
- 또는 chat 입력에 "한국어로:" 접두

---

## Claude Code ↔ Copilot 작동 차이 요약

| 요소 | Claude Code | Copilot |
|---|---|---|
| 글로벌 user instructions | `~/.claude/CLAUDE.md` + `sdlc/*.md` | VS Code `settings.json` instructions 배열 |
| 프로젝트 instructions | `project/CLAUDE.md` | `.github/copilot-instructions.md` (자동) |
| 패턴별 룰 | (없음) | `.github/instructions/*.instructions.md` (`applyTo`) |
| 슬래시 명령 | Skill | `.github/prompts/*.prompt.md` |
| 모델 선택 | `model: opus/sonnet/haiku` 파라미터 | Chat UI 모델 선택기 |
| Sub-agent | Agent tool (subagent_type) | `@workspace`, `@vscode`, `@terminal` |
| Tasks | TaskCreate/TaskUpdate | VS Code Tasks (`.vscode/tasks.json`) |
| Memory (영구) | `memory/*.md` | 동등 기능 X — `.github/copilot-instructions.md` 활용 |
| Background tasks | `run_in_background` | VS Code Tasks `runOn` 또는 launchd/cron |
| Hooks | settings.json hooks | git pre-commit + VS Code Tasks |

---

## 참조 파일

- 글로벌 SDLC: `~/.copilot/README.md`
- 프로젝트 컨텍스트: `CLAUDE.md` (Claude Code) ↔ `.github/copilot-instructions.md` (Copilot, 양쪽 모두 정합화)
- 도메인 SSoT: `wiki/01-sot/grade_classification_spec.md`
- 모델 라우팅: `~/.copilot/sdlc/model-routing.md`
