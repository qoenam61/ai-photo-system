"""core.domain.user 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.domain.user import DeviceType, USERS, UserAccount, resolve


@pytest.mark.unit
class TestUserContext:
    def test_jw_son_iphone_icloud_50gb(self, jw_son_user) -> None:
        assert jw_son_user.account == UserAccount.JW_SON
        assert jw_son_user.device == DeviceType.IPHONE
        assert jw_son_user.cloud_quota_gb == 50
        assert jw_son_user.cloud_provider == "icloud"

    def test_eunju_galaxy_galaxy_cloud_15gb(self, eunju_user) -> None:
        assert eunju_user.account == UserAccount.EUNJU
        assert eunju_user.device == DeviceType.GALAXY
        assert eunju_user.cloud_quota_gb == 15
        assert eunju_user.cloud_provider == "galaxy_cloud"

    def test_jw_son_vault_path(self, jw_son_user) -> None:
        assert jw_son_user.vault_path == Path("/Users/Shared/PhotoVault/jw.son")

    def test_jw_son_hdd_path(self, jw_son_user) -> None:
        assert jw_son_user.hdd_path == Path(
            "/Volumes/PhotoHDD/immich-media/jw.son"
        )

    def test_resolve_by_string(self) -> None:
        ctx = resolve("eunju")
        assert ctx.account == UserAccount.EUNJU

    def test_resolve_by_enum(self) -> None:
        ctx = resolve(UserAccount.JW_SON)
        assert ctx.account == UserAccount.JW_SON

    def test_3_users_registered(self) -> None:
        assert len(USERS) == 3
        assert UserAccount.SHARED in USERS
