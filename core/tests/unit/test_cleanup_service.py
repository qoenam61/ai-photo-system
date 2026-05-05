"""core.service.cleanup_service 단위 테스트.

mock psycopg.connect로 DB 의존 X. 비즈니스 로직만 검증.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.service.cleanup_service import (
    DEFAULT_GRACE_HOURS,
    HDD_DELETABLE_GRADES,
    EnqueueResult,
    enqueue_cleanup,
)


@pytest.mark.unit
def test_default_grace_is_seven_days():
    """grace 기본값 = 7일 (사용자 명시 2026-05-05)."""
    assert DEFAULT_GRACE_HOURS == 168


@pytest.mark.unit
def test_hdd_deletable_only_trash():
    """HDD 영구삭제 가능 등급 = TRASH만 (v3.13 정책)."""
    assert HDD_DELETABLE_GRADES == {"TRASH"}


@pytest.mark.unit
def test_enqueue_empty_input():
    """빈 입력 → enqueued=0, no DB 호출."""
    r = enqueue_cleanup([])
    assert r.enqueued == 0
    assert r.skipped == []


@pytest.mark.unit
@patch("core.service.cleanup_service.psycopg.connect")
def test_enqueue_skips_protected(mock_connect):
    """feedback_protect 자산 → skipped."""
    cur = MagicMock()
    cur.fetchall.side_effect = [
        [("aaa-protected",)],  # protected query
        [("aaa-protected", "TRASH", "auto_screenshot")],  # meta
    ]
    cur.fetchone.return_value = None
    mock_connect.return_value.__enter__.return_value.cursor \
        .return_value.__enter__.return_value = cur

    r = enqueue_cleanup(["aaa-protected"])
    assert r.enqueued == 0
    assert any(s["reason"] == "protected" for s in r.skipped)


@pytest.mark.unit
@patch("core.service.cleanup_service.psycopg.connect")
def test_enqueue_skips_no_classification(mock_connect):
    """classification 미등록 자산 → skipped."""
    cur = MagicMock()
    cur.fetchall.side_effect = [
        [],  # protected: 없음
        [],  # meta: 없음
    ]
    mock_connect.return_value.__enter__.return_value.cursor \
        .return_value.__enter__.return_value = cur

    r = enqueue_cleanup(["bbb-unknown"])
    assert r.enqueued == 0
    assert any(s["reason"] == "no_classification" for s in r.skipped)


@pytest.mark.unit
@patch("core.service.cleanup_service.psycopg.connect")
def test_enqueue_skips_non_trash_non_dedup(mock_connect):
    """grade=BEST (비TRASH + 비dedup_demoted) → skipped."""
    cur = MagicMock()
    cur.fetchall.side_effect = [
        [],  # protected
        [("ccc-best", "BEST", "llm_qwen")],  # meta
    ]
    mock_connect.return_value.__enter__.return_value.cursor \
        .return_value.__enter__.return_value = cur

    r = enqueue_cleanup(["ccc-best"])
    assert r.enqueued == 0
    assert any("not_deletable" in s["reason"] for s in r.skipped)


@pytest.mark.unit
def test_enqueue_result_dataclass():
    """EnqueueResult 기본값 검증."""
    r = EnqueueResult()
    assert r.enqueued == 0
    assert r.already_queued == 0
    assert r.skipped == []
