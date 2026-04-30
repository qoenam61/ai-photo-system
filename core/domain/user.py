"""사용자 도메인 — jw.son(iPhone) / eunju(Galaxy) / shared.

설계 §3 사용자 구성. 새 가족 멤버 추가 시 이 파일만 수정.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class UserAccount(StrEnum):
    """가족 사용자 계정. shared 는 공유 EVENT 앨범용 가상 계정."""

    JW_SON = "jw.son"
    EUNJU = "eunju"
    SHARED = "shared"


class DeviceType(StrEnum):
    IPHONE = "iphone"
    GALAXY = "galaxy"
    SHARED = "shared"


@dataclass(frozen=True, slots=True)
class UserContext:
    """사용자 단위 컨텍스트. 모든 Layer가 이 객체로 분기."""

    account: UserAccount
    device: DeviceType
    cloud_quota_gb: int
    cloud_provider: str  # "icloud" | "galaxy_cloud" | None

    @property
    def vault_path(self) -> Path:
        """SSD 임시 vault 경로 (Phase 0~5)."""
        return Path("/Users/Shared/PhotoVault") / self.account.value

    @property
    def hdd_path(self) -> Path:
        """HDD 영구 경로 (Phase 6~)."""
        return Path("/Volumes/PhotoHDD/immich-media") / self.account.value


USERS: dict[UserAccount, UserContext] = {
    UserAccount.JW_SON: UserContext(
        account=UserAccount.JW_SON,
        device=DeviceType.IPHONE,
        cloud_quota_gb=50,
        cloud_provider="icloud",
    ),
    UserAccount.EUNJU: UserContext(
        account=UserAccount.EUNJU,
        device=DeviceType.GALAXY,
        cloud_quota_gb=15,
        cloud_provider="galaxy_cloud",
    ),
    UserAccount.SHARED: UserContext(
        account=UserAccount.SHARED,
        device=DeviceType.SHARED,
        cloud_quota_gb=0,
        cloud_provider=None,  # type: ignore[arg-type]
    ),
}


def resolve(account: UserAccount | str) -> UserContext:
    """문자열 또는 enum으로 UserContext 조회."""
    key = UserAccount(account) if isinstance(account, str) else account
    return USERS[key]
