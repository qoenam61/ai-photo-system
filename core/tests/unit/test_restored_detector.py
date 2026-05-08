"""core.service.restored_detector 단위 테스트.

mock psycopg.connect로 DB 의존 X.

TC: wiki/03-pdca/active/report/TC-restored-asset-protection.md
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.service.restored_detector import (
    MarkResult,
    RestoredPair,
    detect_iphone_rebackup,
    mark_restored,
)


@pytest.mark.unit
@patch("core.service.restored_detector.psycopg.connect")
def test_detect_iphone_rebackup_returns_pairs(mock_connect):
    """sha256 매칭 + asset_id 다른 자산 → RestoredPair."""
    cur = MagicMock()
    cur.fetchall.return_value = [
        ("aaaa-old", "bbbb-new", "SHA_X"),
    ]
    mock_connect.return_value.__enter__.return_value.cursor \
        .return_value.__enter__.return_value = cur

    pairs = detect_iphone_rebackup()
    assert len(pairs) == 1
    assert pairs[0] == RestoredPair(
        old_asset_id="aaaa-old",
        new_asset_id="bbbb-new",
        sha256="SHA_X",
    )


@pytest.mark.unit
@patch("core.service.restored_detector.psycopg.connect")
def test_detect_iphone_rebackup_empty_when_no_match(mock_connect):
    """cleanup_audit 있으나 sha256 동일 새 자산 없음 → 빈 리스트."""
    cur = MagicMock()
    cur.fetchall.return_value = []
    mock_connect.return_value.__enter__.return_value.cursor \
        .return_value.__enter__.return_value = cur

    pairs = detect_iphone_rebackup()
    assert pairs == []


@pytest.mark.unit
@patch("core.service.restored_detector.psycopg.connect")
def test_mark_restored_inserts_feedback_and_cancels_queue(mock_connect):
    """첫 호출: feedback INSERT + cleanup_queue cancel 동시."""
    cur = MagicMock()
    cur.fetchone.return_value = None  # 보호 미등록
    cur.rowcount = 1  # cleanup_queue 1건 cancel
    mock_connect.return_value.__enter__.return_value.cursor \
        .return_value.__enter__.return_value = cur

    r = mark_restored(["bbbb-new"])
    assert r.feedback_inserted == 1
    assert r.feedback_already == 0
    assert r.queue_cancelled == 1
    assert r.errors == []


@pytest.mark.unit
@patch("core.service.restored_detector.psycopg.connect")
def test_mark_restored_idempotent_when_already_protected(mock_connect):
    """이미 protect/restored 있으면 skip — feedback_already 카운트만."""
    cur = MagicMock()
    cur.fetchone.return_value = (1,)  # 보호 이미 등록
    mock_connect.return_value.__enter__.return_value.cursor \
        .return_value.__enter__.return_value = cur

    r = mark_restored(["aaaa-already-protected"])
    assert r.feedback_inserted == 0
    assert r.feedback_already == 1
    assert r.queue_cancelled == 0


@pytest.mark.unit
def test_mark_restored_empty_input():
    """빈 입력 → no-op."""
    r = mark_restored([])
    assert r == MarkResult()


@pytest.mark.unit
def test_restored_pair_dataclass():
    p = RestoredPair(old_asset_id="a", new_asset_id="b", sha256="c")
    assert p.old_asset_id == "a"
    assert p.new_asset_id == "b"
    assert p.sha256 == "c"
