"""core.service.backup_verifier 단위 테스트.

_resolve 경로 매핑 + VerifyResult dataclass 검증.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.service.backup_verifier import (
    PATH_MAPPINGS,
    VerifyResult,
    _resolve,
)


@pytest.mark.unit
def test_path_mappings_3():
    """PATH_MAPPINGS = 3개 (mnt/external, upload, Volumes)."""
    assert len(PATH_MAPPINGS) == 3
    keys = {src for src, _ in PATH_MAPPINGS}
    assert "/mnt/external" in keys
    assert "/usr/src/app/upload" in keys


@pytest.mark.unit
def test_resolve_external_library():
    """/mnt/external → /storage/immich-media (External Library)."""
    p = _resolve("/mnt/external/library/BEST/abc.jpg")
    assert str(p) == "/storage/immich-media/library/BEST/abc.jpg"


@pytest.mark.unit
def test_resolve_iphone_upload():
    """/usr/src/app/upload → /storage/immich-uploads (iPhone)."""
    p = _resolve("/usr/src/app/upload/upload/user/00/aa/abc.HEIC")
    assert str(p) == "/storage/immich-uploads/upload/user/00/aa/abc.HEIC"


@pytest.mark.unit
def test_resolve_passthrough():
    """매핑 안 되는 경로 → 그대로."""
    p = _resolve("/some/other/path/file.jpg")
    assert str(p) == "/some/other/path/file.jpg"


@pytest.mark.unit
def test_verify_result_dataclass_default():
    res = VerifyResult(asset_id="aaa", verified=False)
    assert res.asset_id == "aaa"
    assert res.verified is False
    assert res.reason == ""
    assert res.expected_size == 0
    assert res.actual_size == 0
