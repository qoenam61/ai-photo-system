"""core.domain.grade 단위 테스트."""

from __future__ import annotations

import pytest

from core.domain.grade import (
    EVENT_SCORE_THRESHOLD,
    Grade,
    GradeScore,
    calculate_event_score,
    is_event_candidate,
)


@pytest.mark.unit
class TestGradeEnum:
    def test_8_grades_plus_unclassified(self) -> None:
        assert len(Grade) == 9

    def test_grade_string_values(self) -> None:
        assert Grade.EVENT == "EVENT"
        assert Grade.MEMORY_PLUS == "MEMORY+"
        assert Grade.MEMORY_MINUS == "MEMORY-"


@pytest.mark.unit
class TestEventScore:
    def test_empty_score_is_zero(self) -> None:
        assert calculate_event_score(GradeScore()) == 0

    def test_3_faces_only_2pt(self) -> None:
        assert calculate_event_score(GradeScore(face_count=3)) == 2

    def test_2_faces_no_score(self) -> None:
        assert calculate_event_score(GradeScore(face_count=2)) == 0

    def test_formal_dress_1pt(self) -> None:
        assert calculate_event_score(GradeScore(formal_dress=True)) == 1

    def test_event_object_2pt(self) -> None:
        assert (
            calculate_event_score(GradeScore(event_objects=frozenset({"cake"}))) == 2
        )

    def test_irrelevant_object_no_score(self) -> None:
        assert (
            calculate_event_score(
                GradeScore(event_objects=frozenset({"chair", "table"}))
            )
            == 0
        )

    def test_sharp_image_1pt(self) -> None:
        assert calculate_event_score(GradeScore(laplacian_variance=350)) == 1

    def test_blurry_image_no_score(self) -> None:
        assert calculate_event_score(GradeScore(laplacian_variance=200)) == 0

    def test_voice_keyword_2pt(self) -> None:
        assert calculate_event_score(GradeScore(voice_keywords=("축하",))) == 2

    def test_combined_event_threshold_pass(self) -> None:
        # 얼굴 3+ + 케이크 = 4점 → EVENT 후보
        score = GradeScore(face_count=4, event_objects=frozenset({"cake"}))
        assert calculate_event_score(score) == 4
        assert is_event_candidate(score) is True

    def test_combined_below_threshold(self) -> None:
        # 얼굴 3 + 정장 = 3점 → EVENT 미달
        score = GradeScore(face_count=3, formal_dress=True)
        assert calculate_event_score(score) == 3
        assert is_event_candidate(score) is False

    def test_threshold_constant(self) -> None:
        assert EVENT_SCORE_THRESHOLD == 4
