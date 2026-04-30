"""core.domain.storage_layout 단위 테스트 (옵션 D 하이브리드 §3.5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.domain.grade import Grade
from core.domain.storage_layout import GRADE_FOLDERS, StorageLayout, ViewCategory


@pytest.mark.unit
class TestGradeFolders:
    def test_8_grade_folders(self) -> None:
        # 의사결정 #16 — 8개 (UNCLASSIFIED 제외)
        assert len(GRADE_FOLDERS) == 8
        assert Grade.UNCLASSIFIED not in GRADE_FOLDERS

    def test_grade_folders_includes_all_8(self) -> None:
        expected = {
            Grade.EVENT,
            Grade.EVENT_L,
            Grade.BEST,
            Grade.FOOD,
            Grade.MEMORY_PLUS,
            Grade.MEMORY_MINUS,
            Grade.NORMAL,
            Grade.TRASH,
        }
        assert set(GRADE_FOLDERS) == expected


@pytest.mark.unit
class TestStorageLayout:
    def test_media_root_jw_son(self, jw_son_user) -> None:
        layout = StorageLayout(user=jw_son_user)
        assert layout.media_root == Path(
            "/Volumes/PhotoHDD/immich-media/jw.son/library"
        )

    def test_views_root_eunju(self, eunju_user) -> None:
        layout = StorageLayout(user=eunju_user)
        assert layout.views_root == Path("/Volumes/PhotoHDD/immich-views/eunju")

    def test_grade_folder(self, jw_son_user) -> None:
        layout = StorageLayout(user=jw_son_user)
        assert (
            layout.grade_folder(Grade.EVENT)
            == Path("/Volumes/PhotoHDD/immich-media/jw.son/library/EVENT")
        )

    def test_event_l_grade_folder_has_dash(self, jw_son_user) -> None:
        layout = StorageLayout(user=jw_son_user)
        assert layout.grade_folder(Grade.EVENT_L).name == "EVENT-L"

    def test_memory_plus_grade_folder(self, jw_son_user) -> None:
        layout = StorageLayout(user=jw_son_user)
        assert layout.grade_folder(Grade.MEMORY_PLUS).name == "MEMORY+"

    def test_asset_path_jpeg(self, jw_son_user) -> None:
        layout = StorageLayout(user=jw_son_user)
        path = layout.asset_path(Grade.BEST, "abc-123", "jpg")
        assert path == Path(
            "/Volumes/PhotoHDD/immich-media/jw.son/library/BEST/abc-123.jpg"
        )

    def test_asset_path_video(self, eunju_user) -> None:
        layout = StorageLayout(user=eunju_user)
        path = layout.asset_path(Grade.EVENT, "vid-456", "mp4")
        assert path == Path(
            "/Volumes/PhotoHDD/immich-media/eunju/library/EVENT/vid-456.mp4"
        )


@pytest.mark.unit
class TestViewFolders:
    def test_view_event_folder(self, jw_son_user) -> None:
        layout = StorageLayout(user=jw_son_user)
        assert layout.view_event_folder("2026-04-29 강남 결혼식") == Path(
            "/Volumes/PhotoHDD/immich-views/jw.son/행사별/2026-04-29 강남 결혼식"
        )

    def test_view_monthly(self, jw_son_user) -> None:
        layout = StorageLayout(user=jw_son_user)
        assert layout.view_monthly_folder("2026-04") == Path(
            "/Volumes/PhotoHDD/immich-views/jw.son/월별/2026-04"
        )

    def test_view_favorite(self, jw_son_user) -> None:
        layout = StorageLayout(user=jw_son_user)
        assert layout.view_favorite_folder("2026-04") == Path(
            "/Volumes/PhotoHDD/immich-views/jw.son/♥ 즐겨찾기/2026-04"
        )

    def test_view_food(self, eunju_user) -> None:
        layout = StorageLayout(user=eunju_user)
        assert layout.view_food_folder("한식") == Path(
            "/Volumes/PhotoHDD/immich-views/eunju/음식/한식"
        )

    def test_view_categories_count(self) -> None:
        # 의사결정 #17 — 4개 1차 카테고리
        assert len(ViewCategory) == 4
