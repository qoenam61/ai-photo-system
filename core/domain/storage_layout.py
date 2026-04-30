"""HDD 폴더 레이아웃 — 옵션 D 하이브리드 (v3.7 §3.5).

원본은 등급별 폴더 (평면 UUID 파일명).
뷰는 행사/♥/월/음식 다층 (심볼릭 링크).

새 등급·뷰 카테고리 추가 시 이 파일만 수정.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from core.domain.grade import Grade
from core.domain.user import UserContext


class ViewCategory(StrEnum):
    """뷰 폴더 1차 카테고리. 의사결정 #17."""

    EVENT = "행사별"
    MONTHLY = "월별"
    FAVORITE = "♥ 즐겨찾기"
    FOOD = "음식"


# 의사결정 #16 — 등급 폴더 8개 (UNCLASSIFIED 제외)
GRADE_FOLDERS: tuple[Grade, ...] = (
    Grade.EVENT,
    Grade.EVENT_L,
    Grade.BEST,
    Grade.FOOD,
    Grade.MEMORY_PLUS,
    Grade.MEMORY_MINUS,
    Grade.NORMAL,
    Grade.TRASH,
)


@dataclass(frozen=True, slots=True)
class StorageLayout:
    """사용자별 HDD 폴더 경로 계산기."""

    user: UserContext
    hdd_root: Path = Path("/Volumes/PhotoHDD")

    @property
    def media_root(self) -> Path:
        """Immich External Library 루트."""
        return self.hdd_root / "immich-media" / self.user.account.value / "library"

    @property
    def views_root(self) -> Path:
        """뷰 폴더 루트 (심볼릭 링크 모음)."""
        return self.hdd_root / "immich-views" / self.user.account.value

    def grade_folder(self, grade: Grade) -> Path:
        """등급별 원본 폴더 (평면 UUID 저장)."""
        return self.media_root / grade.value

    def asset_path(self, grade: Grade, asset_uuid: str, ext: str) -> Path:
        """원본 자산 경로. ext는 'jpg' 또는 'mp4'."""
        return self.grade_folder(grade) / f"{asset_uuid}.{ext}"

    def view_event_folder(self, event_label: str) -> Path:
        """행사별 뷰 폴더 (예: '2026-04-29 강남 결혼식')."""
        return self.views_root / ViewCategory.EVENT.value / event_label

    def view_monthly_folder(self, year_month: str) -> Path:
        """월별 뷰 폴더 (예: '2026-04')."""
        return self.views_root / ViewCategory.MONTHLY.value / year_month

    def view_favorite_folder(self, year_month: str) -> Path:
        """♥ 즐겨찾기 폴더 (월별 sub)."""
        return self.views_root / ViewCategory.FAVORITE.value / year_month

    def view_food_folder(self, food_type: str) -> Path:
        """음식 종류 폴더 (한식/양식/일식/디저트 등, §15.G)."""
        return self.views_root / ViewCategory.FOOD.value / food_type
