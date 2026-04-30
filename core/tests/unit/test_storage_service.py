"""core.service.storage_service 단위 테스트."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.domain.grade import Grade
from core.domain.storage_layout import StorageLayout
from core.service.storage_service import StorageService


@pytest.fixture
def tmp_layout(tmp_path, jw_son_user):
    return StorageLayout(user=jw_son_user, hdd_root=tmp_path)


@pytest.fixture
def mock_repo():
    return MagicMock()


@pytest.fixture
def mock_immich():
    return MagicMock()


@pytest.fixture
def service(mock_repo, mock_immich):
    return StorageService(repo=mock_repo, immich=mock_immich)


@pytest.mark.unit
class TestMoveToGradeFolder:
    def test_new_asset_moves_from_library_root_to_grade(
        self, service, tmp_layout, mock_repo
    ) -> None:
        # 신규 자산: library/<UUID>.jpg → library/EVENT/<UUID>.jpg
        old_path = tmp_layout.media_root / "abc-123.jpg"
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_bytes(b"fake")

        new_path = service.move_to_grade_folder(
            tmp_layout, "asset-1", "abc-123", "jpg", None, Grade.EVENT
        )

        assert not old_path.exists()
        assert new_path.exists()
        assert new_path == tmp_layout.grade_folder(Grade.EVENT) / "abc-123.jpg"
        mock_repo.update_original_path.assert_called_once_with("asset-1", new_path)

    def test_regrade_moves_between_folders(
        self, service, tmp_layout
    ) -> None:
        # NORMAL → BEST 재분류
        old_path = tmp_layout.asset_path(Grade.NORMAL, "vid-456", "mp4")
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_bytes(b"fake")

        service.move_to_grade_folder(
            tmp_layout, "asset-2", "vid-456", "mp4", Grade.NORMAL, Grade.BEST
        )

        assert not old_path.exists()
        assert (tmp_layout.grade_folder(Grade.BEST) / "vid-456.mp4").exists()

    def test_same_grade_is_idempotent(
        self, service, tmp_layout, mock_repo
    ) -> None:
        # old == new → 이동 없음 (idempotent)
        path = tmp_layout.asset_path(Grade.EVENT, "abc-123", "jpg")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake")

        result = service.move_to_grade_folder(
            tmp_layout, "asset-1", "abc-123", "jpg", Grade.EVENT, Grade.EVENT
        )

        assert path.exists()
        assert result == path
        mock_repo.update_original_path.assert_not_called()

    def test_missing_source_raises(self, service, tmp_layout) -> None:
        with pytest.raises(FileNotFoundError):
            service.move_to_grade_folder(
                tmp_layout, "asset-x", "missing", "jpg", None, Grade.EVENT
            )


@pytest.mark.unit
class TestViewLinks:
    def test_add_view_link_creates_symlink(self, service, tmp_layout) -> None:
        target = tmp_layout.asset_path(Grade.EVENT, "abc-123", "jpg")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fake")

        view_dir = tmp_layout.view_event_folder("2026-04-29 강남 결혼식")
        service.add_view_link(view_dir, target, "14-32-15.jpg")

        link = view_dir / "14-32-15.jpg"
        assert link.is_symlink()
        assert link.resolve() == target.resolve()

    def test_add_view_link_atomic_replace(self, service, tmp_layout) -> None:
        # 기존 링크 있을 때 덮어쓰기 (atomic)
        target1 = tmp_layout.asset_path(Grade.EVENT, "old", "jpg")
        target2 = tmp_layout.asset_path(Grade.EVENT, "new", "jpg")
        target1.parent.mkdir(parents=True, exist_ok=True)
        target1.write_bytes(b"old")
        target2.write_bytes(b"new")

        view_dir = tmp_layout.view_monthly_folder("2026-04")
        service.add_view_link(view_dir, target1, "x.jpg")
        service.add_view_link(view_dir, target2, "x.jpg")  # 덮어쓰기

        assert (view_dir / "x.jpg").resolve() == target2.resolve()

    def test_remove_view_link(self, service, tmp_layout) -> None:
        target = tmp_layout.asset_path(Grade.EVENT, "abc", "jpg")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fake")

        view_dir = tmp_layout.view_favorite_folder("2026-04")
        service.add_view_link(view_dir, target, "y.jpg")
        assert (view_dir / "y.jpg").exists()

        service.remove_view_link(view_dir, "y.jpg")
        assert not (view_dir / "y.jpg").exists()

    def test_remove_nonexistent_is_noop(self, service, tmp_layout) -> None:
        view_dir = tmp_layout.view_monthly_folder("2026-04")
        view_dir.mkdir(parents=True, exist_ok=True)
        service.remove_view_link(view_dir, "missing.jpg")  # 예외 안 남


@pytest.mark.unit
class TestRefreshViewsForAsset:
    def test_event_creates_event_and_monthly_links(
        self, service, tmp_layout
    ) -> None:
        target = tmp_layout.asset_path(Grade.EVENT, "abc", "jpg")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fake")

        service.refresh_views_for_asset(
            tmp_layout,
            asset_uuid="abc",
            ext="jpg",
            grade=Grade.EVENT,
            timestamp="2026-04-29 14-32-15",
            year_month="2026-04",
            is_favorite=False,
            event_label="2026-04-29 강남 결혼식",
            food_type=None,
        )

        # 행사별 + 월별 둘 다
        assert (
            tmp_layout.view_event_folder("2026-04-29 강남 결혼식")
            / "2026-04-29 14-32-15.jpg"
        ).is_symlink()
        assert (
            tmp_layout.view_monthly_folder("2026-04") / "2026-04-29 14-32-15.jpg"
        ).is_symlink()

    def test_favorite_creates_favorite_link(self, service, tmp_layout) -> None:
        target = tmp_layout.asset_path(Grade.NORMAL, "x", "jpg")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fake")

        service.refresh_views_for_asset(
            tmp_layout,
            asset_uuid="x",
            ext="jpg",
            grade=Grade.NORMAL,
            timestamp="t",
            year_month="2026-04",
            is_favorite=True,
            event_label=None,
            food_type=None,
        )

        # ♥ 폴더에 링크 생김
        assert (
            tmp_layout.view_favorite_folder("2026-04") / "t.jpg"
        ).is_symlink()
        # 행사별은 안 만듬
        assert not tmp_layout.view_event_folder("any").exists()

    def test_food_creates_food_subfolder(self, service, tmp_layout) -> None:
        target = tmp_layout.asset_path(Grade.FOOD, "f", "jpg")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fake")

        service.refresh_views_for_asset(
            tmp_layout,
            asset_uuid="f",
            ext="jpg",
            grade=Grade.FOOD,
            timestamp="t",
            year_month="2026-04",
            is_favorite=False,
            event_label=None,
            food_type="한식",
        )

        assert (tmp_layout.view_food_folder("한식") / "t.jpg").is_symlink()

    def test_trash_skips_monthly_view(self, service, tmp_layout) -> None:
        target = tmp_layout.asset_path(Grade.TRASH, "junk", "jpg")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fake")

        service.refresh_views_for_asset(
            tmp_layout,
            asset_uuid="junk",
            ext="jpg",
            grade=Grade.TRASH,
            timestamp="t",
            year_month="2026-04",
            is_favorite=False,
            event_label=None,
            food_type=None,
        )

        # TRASH는 월별 뷰에서 제외 (사용자 시야 분리)
        assert not (tmp_layout.view_monthly_folder("2026-04") / "t.jpg").exists()


@pytest.mark.unit
class TestPurgeTrash:
    def test_purge_old_trash_files(self, service, tmp_layout) -> None:
        import os
        import time

        trash_dir = tmp_layout.grade_folder(Grade.TRASH)
        trash_dir.mkdir(parents=True, exist_ok=True)
        old_file = trash_dir / "old.jpg"
        new_file = trash_dir / "new.jpg"
        old_file.write_bytes(b"x")
        new_file.write_bytes(b"y")

        # old_file을 31일 전으로
        old_time = time.time() - (31 * 86400)
        os.utime(old_file, (old_time, old_time))

        count = service.purge_trash_older_than_days(tmp_layout, days=30)

        assert count == 1
        assert not old_file.exists()
        assert new_file.exists()

    def test_purge_empty_returns_zero(self, service, tmp_layout) -> None:
        assert service.purge_trash_older_than_days(tmp_layout) == 0
