"""core.service.classifier 단위 테스트.

_auto_grade 결정 트리 + Signals 데이터클래스 검증.
"""

from __future__ import annotations

import pytest

from core.service.classifier import LLM_GRADES, Signals, _auto_grade


@pytest.mark.unit
def test_llm_grades_are_4():
    """LLM_GRADES = {EVENT, BEST, FOOD, TRASH}."""
    assert LLM_GRADES == {"EVENT", "BEST", "FOOD", "TRASH"}


@pytest.mark.unit
def test_signals_default():
    sig = Signals()
    assert sig.face_count == 0
    assert sig.laplacian_variance == 0.0
    assert sig.is_screenshot is False
    assert sig.is_video is False
    assert sig.duration_seconds == 0.0
    assert sig.camera_make == ""


@pytest.mark.unit
def test_short_video_to_trash():
    """3초 미만 영상 → TRASH/auto_short_video."""
    sig = Signals(is_video=True, duration_seconds=2.5)
    grade, src = _auto_grade("", sig)
    assert grade == "TRASH"
    assert src == "auto_short_video"


@pytest.mark.unit
def test_long_video_to_event_l():
    """3초 이상 영상 → EVENT-L/auto_video."""
    sig = Signals(is_video=True, duration_seconds=10)
    grade, src = _auto_grade("", sig)
    assert grade == "EVENT-L"
    assert src == "auto_video"


@pytest.mark.unit
def test_screenshot_to_trash():
    """스크린샷 → TRASH/auto_screenshot."""
    sig = Signals(is_screenshot=True)
    grade, src = _auto_grade("", sig)
    assert grade == "TRASH"
    assert src == "auto_screenshot"


@pytest.mark.unit
def test_llm_event_passthrough():
    """LLM=EVENT → EVENT/llm_ensemble."""
    sig = Signals()
    grade, src = _auto_grade("EVENT", sig)
    assert grade == "EVENT"


@pytest.mark.unit
def test_face_blurry_to_memory_minus():
    """face>0 + lap<100 → MEMORY-/auto_blurry (사용자 명시)."""
    sig = Signals(face_count=2, laplacian_variance=50.0)
    grade, src = _auto_grade("", sig)
    assert grade == "MEMORY-"
    assert src == "auto_blurry"


@pytest.mark.unit
def test_face_quality_ok_to_memory_plus():
    """face>0 + lap>=100 → MEMORY+/auto_quality_ok."""
    sig = Signals(face_count=1, laplacian_variance=200.0)
    grade, src = _auto_grade("", sig)
    assert grade == "MEMORY+"
    assert src == "auto_quality_ok"


@pytest.mark.unit
def test_no_face_with_camera_to_normal():
    """face=0 + camera_make 있음 → NORMAL/auto_no_face (재분류 정책)."""
    sig = Signals(face_count=0, camera_make="Apple")
    grade, src = _auto_grade("", sig)
    assert grade == "NORMAL"
    assert src == "auto_no_face"


@pytest.mark.unit
def test_no_face_no_camera_to_trash():
    """face=0 + camera 없음 → TRASH (의미없는 사진 fallback)."""
    sig = Signals(face_count=0, camera_make="")
    grade, src = _auto_grade("", sig)
    assert grade == "TRASH"
    assert src == "auto_screenshot"
