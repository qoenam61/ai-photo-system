"""사진 분류 8등급 + EVENT 점수 가산제.

설계 문서 §4 분류 등급 + §5 Layer 3 등급 자동 판정 + §17d Layer 4.
변경 영향: 새 등급 추가 시 이 파일만 수정.
"""

from dataclasses import dataclass
from enum import StrEnum


class Grade(StrEnum):
    """10단계 자동 분류 등급 (2026-05-09 안3 — EVENT/EVENT-L → +/- 분할).

    Legacy alias EVENT/EVENT_L 유지 (테스트·구버전 코드 호환).
    """

    EVENT_PLUS = "EVENT+"        # 자녀 등장 행사 (iCloud 보존)
    EVENT_MINUS = "EVENT-"       # 자녀 미등장 행사 (HDD only)
    EVENT_L_PLUS = "EVENT-L+"    # 본식 영상 + 자녀 행사 long form (iCloud)
    EVENT_L_MINUS = "EVENT-L-"   # 일상 영상 + 비자녀 행사 long form (HDD only)
    BEST = "BEST"
    FOOD = "FOOD"
    MEMORY_PLUS = "MEMORY+"
    MEMORY_MINUS = "MEMORY-"
    NORMAL = "NORMAL"
    TRASH = "TRASH"
    UNCLASSIFIED = "UNCLASSIFIED"  # Layer 4 큐 진입용
    # Legacy alias (2026-05-09 이전 코드/테스트 호환). 분류 결과는 항상 +/- 사용.
    EVENT = "EVENT"
    EVENT_L = "EVENT-L"


# 보존 = +등급만 (자녀 OR 본식 영상). iCloud 50GB 한도 유지 (2026-05-09 안3).
CLOUD_BACKUP_GRADES: frozenset[Grade] = frozenset({
    Grade.BEST, Grade.EVENT_PLUS, Grade.EVENT_L_PLUS, Grade.MEMORY_PLUS,
})
DEVICE_KEEP_GRADES: frozenset[Grade] = frozenset({
    Grade.BEST, Grade.EVENT_PLUS, Grade.EVENT_L_PLUS, Grade.MEMORY_PLUS,
})


@dataclass(frozen=True, slots=True)
class GradeScore:
    """EVENT 점수 가산제 입력.

    설계 §4 알고리즘 임계값 명세.
    """

    face_count: int = 0
    formal_dress: bool = False
    event_objects: frozenset[str] = frozenset()
    laplacian_variance: float = 0.0
    voice_keywords: tuple[str, ...] = ()


EVENT_SCORE_THRESHOLD: int = 4
EVENT_OBJECT_TAGS: frozenset[str] = frozenset(
    {"cake", "flowers", "stage", "balloon", "banner"}
)
SHARP_LAPLACIAN_THRESHOLD: float = 300.0


def calculate_event_score(score: GradeScore) -> int:
    """EVENT 점수 가산. 합계 >= EVENT_SCORE_THRESHOLD 시 EVENT 후보.

    Args:
        score: 분류 입력 신호.

    Returns:
        가산 점수 (0~8).
    """
    points = 0
    if score.face_count >= 3:
        points += 2
    if score.formal_dress:
        points += 1
    if score.event_objects & EVENT_OBJECT_TAGS:
        points += 2
    if score.laplacian_variance > SHARP_LAPLACIAN_THRESHOLD:
        points += 1
    if score.voice_keywords:
        points += 2
    return points


def is_event_candidate(score: GradeScore) -> bool:
    """EVENT 자동 판정 여부."""
    return calculate_event_score(score) >= EVENT_SCORE_THRESHOLD
