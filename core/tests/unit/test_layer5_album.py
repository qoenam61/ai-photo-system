"""core.pipeline.layer5_album 단위 테스트.

apply_grade_change 결정 로직 검증 (mock subprocess + filesystem).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.pipeline.layer5_album import (
    LIBRARY_HOST,
    LIBRARY_IMMICH,
    VALID_GRADES,
    apply_grade_change,
    apply_grade_changes_batch,
)


@pytest.mark.unit
def test_valid_grades_8():
    """VALID_GRADES = 8등급."""
    assert VALID_GRADES == {"BEST", "EVENT", "EVENT-L", "FOOD",
                            "MEMORY+", "MEMORY-", "NORMAL", "TRASH"}


@pytest.mark.unit
def test_invalid_grade_rejected():
    """알 수 없는 grade → fail."""
    success, msg = apply_grade_change("aaa", "INVALID_GRADE")
    assert not success
    assert "invalid_grade" in msg


@pytest.mark.unit
@patch("core.pipeline.layer5_album._immich_get_path")
def test_no_immich_match(mock_get):
    """Immich 미매칭 → fail."""
    mock_get.return_value = None
    success, msg = apply_grade_change("aaa-uuid", "BEST")
    assert not success
    assert "immich_no_match" in msg


@pytest.mark.unit
@patch("core.pipeline.layer5_album.refresh_view_link")
@patch("core.pipeline.layer5_album._immich_get_path")
def test_iphone_upload_skip_with_view(mock_get, mock_view):
    """iPhone 업로드 자산 → library 외부 → skip but view 갱신."""
    mock_get.return_value = ("img-id", "/usr/src/app/upload/foo.HEIC")
    mock_view.return_value = True
    success, msg = apply_grade_change("aaa-uuid", "BEST")
    assert not success
    assert "skip:not_in_library" in msg
    assert "view_ok" in msg
    mock_view.assert_called_once()


@pytest.mark.unit
@patch("core.pipeline.layer5_album.refresh_view_link")
@patch("core.pipeline.layer5_album._immich_get_path")
def test_already_correct_grade(mock_get, mock_view):
    """등급 이미 일치 → noop, view만 refresh."""
    mock_get.return_value = ("img-id", f"{LIBRARY_IMMICH}/BEST/file.jpg")
    success, msg = apply_grade_change("aaa", "BEST")
    assert success
    assert msg == "noop:already_correct"
    mock_view.assert_called_once()


@pytest.mark.unit
def test_apply_grade_changes_batch_empty():
    counts = apply_grade_changes_batch([])
    assert counts["ok"] == 0
    assert counts["details"] == []
