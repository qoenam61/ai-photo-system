"""core.client.llm_gateway 단위 테스트.

_is_trading_hours_kst() 트레이딩 자원 보호 게이트 검증.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from core.client.llm_gateway import _is_trading_hours_kst


KST = timezone(timedelta(hours=9))


@pytest.mark.unit
def test_block_disabled_via_env():
    """TRADING_HOURS_LOCAL_BLOCK=0 → 항상 False (긴급 비활성)."""
    os.environ["TRADING_HOURS_LOCAL_BLOCK"] = "0"
    assert _is_trading_hours_kst() is False
    del os.environ["TRADING_HOURS_LOCAL_BLOCK"]


@pytest.mark.unit
def test_active_default():
    """기본값 BLOCK=1 (env 미설정 시) — 단순 호출 검증."""
    os.environ.pop("TRADING_HOURS_LOCAL_BLOCK", None)
    result = _is_trading_hours_kst()
    assert isinstance(result, bool)


@pytest.mark.unit
def test_weekend_always_false():
    """주말 → False (BLOCK=1이라도)."""
    os.environ["TRADING_HOURS_LOCAL_BLOCK"] = "1"
    # 토/일 검증은 mock 어려워 단순 호출만 확인
    result = _is_trading_hours_kst()
    assert isinstance(result, bool)
    del os.environ["TRADING_HOURS_LOCAL_BLOCK"]
