"""pytest 공통 fixture.

테스트 마커:
  unit         단위 테스트 (mock 사용, 빠름)
  integration  통합 테스트 (testcontainers, ~10s)
  e2e          E2E 시나리오 (느림)
  golden       Golden dataset 회귀 (100장)
  slow         느린 테스트 (>1s)

실행 예:
  pytest -m unit                # 빠른 단위만
  pytest -m "not slow"          # CI 기본
  pytest -m golden              # 야간 회귀
"""

from __future__ import annotations

import pytest


@pytest.fixture
def jw_son_user():
    from core.domain.user import resolve, UserAccount

    return resolve(UserAccount.JW_SON)


@pytest.fixture
def eunju_user():
    from core.domain.user import resolve, UserAccount

    return resolve(UserAccount.EUNJU)
