# Qwen2.5-VL 프롬프트 템플릿

설계 §17d (Layer 4) + §15 (확장 활용 7가지). 외부 파일로 분리하여 git diff·코드 리뷰 가능.

## 파일 목록 (9개)

| 파일 | 사용처 | Layer |
|---|---|---|
| `layer2_content_analysis.md` | Layer 2 콘텐츠 분석 | 2 |
| `layer4_classification.md` | Layer 4 8등급 재분류 | 4 |
| `ext_album_name.md` | 공유 EVENT 앨범 자동 명명 | §15.1.A |
| `ext_kpi_summary.md` | 주간 KPI 자연어 요약 | §15.1.B |
| `ext_telegram_query.md` | Telegram 자연어 질의 → API 매핑 | §15.1.C |
| `ext_feedback_analysis.md` | 사용자 피드백 패턴 분석 | §15.1.D |
| `ext_caption.md` | 사진 캡션 자동 생성 (검색용) | §15.1.E |
| `ext_face_grouping.md` | 얼굴 그룹 이름 추천 | §15.1.F |
| `ext_food_classification.md` | 음식 종류 분류 (한식/양식 등) | §15.1.G |

## 프롬프트 형식

각 파일은 다음 구조:

```markdown
# 프롬프트 제목

## System
역할 정의 + 8등급 기준 + few-shot 예시

## User Template
{변수} 치환 가능. 예: {asset_id}, {locale}, {face_count}

## Output Schema (JSON)
{
  "field": "type"
}

## Examples
입력 → 출력 예시 3건
```

## 호출 코드

`core/client/ollama_client.py` 가 이 디렉토리를 로드하여 프롬프트 템플릿 사용.
모델 변경(Qwen 3.0 등) 시에도 프롬프트는 그대로 재사용.
