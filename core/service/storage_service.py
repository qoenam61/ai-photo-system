"""HDD 등급 폴더 이동 + 뷰 심볼릭 링크 관리 (옵션 D 하이브리드, v3.7 §3.5).

Layer 5 처리 단계 #2 (등급 폴더 이동) + #7 (뷰 갱신)에서 호출.

호출 위치: core.pipeline.layer5_album.run()
의존: core.repository.classification_repo (originalPath UPDATE)
       core.client.immich_client (External Library scan 트리거)

핵심 원칙:
  - 원본은 등급 폴더에 1곳만 (mv는 메타만 변경, I/O 0)
  - 뷰는 심볼릭 링크 (디스크 추가 0)
  - 분류 변경 시 unlink + symlink (안전한 atomic)
  - Idempotency: 같은 자산 재실행 시 결과 동일
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from core.domain.grade import Grade
from core.domain.storage_layout import StorageLayout
from core.domain.user import UserContext


class ClassificationRepoProtocol(Protocol):
    """Repository 의존성 (테스트 시 mock)."""

    def update_original_path(self, asset_id: str, new_path: Path) -> None: ...


class ImmichClientProtocol(Protocol):
    """Immich API 의존성."""

    def trigger_external_library_scan(self, library_id: str) -> None: ...


class StorageService:
    """HDD 등급 폴더 + 뷰 심볼릭 관리.

    Layer 5에서 호출되는 모든 파일시스템 변경을 단일 트랜잭션 단위로 묶음.
    """

    def __init__(
        self,
        repo: ClassificationRepoProtocol,
        immich: ImmichClientProtocol,
    ) -> None:
        self._repo = repo
        self._immich = immich

    # ─────────────────────────────────────────────
    # 등급 폴더 이동 (Layer 5 처리 단계 #2)
    # ─────────────────────────────────────────────

    def move_to_grade_folder(
        self,
        layout: StorageLayout,
        asset_id: str,
        asset_uuid: str,
        ext: str,
        old_grade: Grade | None,
        new_grade: Grade,
    ) -> Path:
        """자산을 새 등급 폴더로 이동. 신규/재분류 모두 처리.

        Args:
            layout: 사용자 StorageLayout
            asset_id: Immich asset UUID (DB id)
            asset_uuid: 파일명에 사용되는 UUID (보통 asset_id와 동일)
            ext: 파일 확장자 ('jpg' 또는 'mp4')
            old_grade: 이전 등급 (None이면 신규)
            new_grade: 새 등급

        Returns:
            새 자산 경로 (Immich originalPath 업데이트용)

        Raises:
            FileNotFoundError: 원본 파일 없음
            OSError: mv 실패
        """
        new_path = layout.asset_path(new_grade, asset_uuid, ext)

        if old_grade == new_grade:
            return new_path  # idempotent

        # 등급 폴더 보장 (이미 있으면 무시)
        new_path.parent.mkdir(parents=True, exist_ok=True)

        if old_grade is None:
            # 신규: upload/ 또는 library/ 평면에서 등급 폴더로
            old_path = layout.media_root / f"{asset_uuid}.{ext}"
        else:
            old_path = layout.asset_path(old_grade, asset_uuid, ext)

        if not old_path.exists():
            raise FileNotFoundError(f"원본 자산 없음: {old_path}")

        old_path.rename(new_path)  # macOS는 같은 볼륨 내 atomic rename
        self._repo.update_original_path(asset_id, new_path)
        return new_path

    # ─────────────────────────────────────────────
    # 뷰 심볼릭 링크 (Layer 5 처리 단계 #7, 03:08)
    # ─────────────────────────────────────────────

    def add_view_link(self, view_dir: Path, target: Path, link_name: str) -> None:
        """뷰 폴더에 심볼릭 링크 추가. 기존 링크는 덮어씀 (atomic)."""
        view_dir.mkdir(parents=True, exist_ok=True)
        link_path = view_dir / link_name

        # atomic replace: 임시 링크 → rename
        tmp_link = link_path.with_suffix(link_path.suffix + ".tmp")
        if tmp_link.exists() or tmp_link.is_symlink():
            tmp_link.unlink()
        tmp_link.symlink_to(target)
        tmp_link.replace(link_path)

    def remove_view_link(self, view_dir: Path, link_name: str) -> None:
        """뷰 폴더에서 심볼릭 링크 제거. 없으면 noop."""
        link_path = view_dir / link_name
        if link_path.is_symlink() or link_path.exists():
            link_path.unlink()

    def refresh_views_for_asset(
        self,
        layout: StorageLayout,
        asset_uuid: str,
        ext: str,
        grade: Grade,
        timestamp: str,  # 'YYYY-MM-DD HH-MM-SS'
        year_month: str,  # 'YYYY-MM'
        is_favorite: bool,
        event_label: str | None,  # '2026-04-29 강남 결혼식' or None
        food_type: str | None,  # '한식' etc.
    ) -> None:
        """단일 자산의 뷰 링크 일괄 갱신.

        Layer 5 처리 단계 #7에서 호출. incremental (변경된 자산만).
        """
        target = layout.asset_path(grade, asset_uuid, ext)
        link_name = f"{timestamp}.{ext}"

        # 행사별 (EVENT*/EVENT-L* — +/-등급 모두 — 2026-05-09 안3)
        if event_label and grade in (
            Grade.EVENT_PLUS, Grade.EVENT_MINUS,
            Grade.EVENT_L_PLUS, Grade.EVENT_L_MINUS,
        ):
            self.add_view_link(layout.view_event_folder(event_label), target, link_name)

        # 월별 (TRASH 제외)
        if grade != Grade.TRASH:
            self.add_view_link(layout.view_monthly_folder(year_month), target, link_name)

        # ♥ 즐겨찾기 (등급 무관)
        if is_favorite:
            self.add_view_link(
                layout.view_favorite_folder(year_month), target, link_name
            )

        # 음식 (FOOD만)
        if grade == Grade.FOOD and food_type:
            self.add_view_link(layout.view_food_folder(food_type), target, link_name)

    # ─────────────────────────────────────────────
    # TRASH 30일 폐기 (의사결정 #20, cron 03:12)
    # ─────────────────────────────────────────────

    def purge_trash_older_than_days(
        self, layout: StorageLayout, days: int = 30
    ) -> int:
        """TRASH 폴더에서 mtime이 days 이전인 파일 삭제.

        DB trash_until 검사는 호출자(layer7_feedback)가 별도로 수행.
        이 함수는 파일시스템 측 안전망.

        Returns:
            삭제된 파일 개수
        """
        import time

        trash_dir = layout.grade_folder(Grade.TRASH)
        if not trash_dir.exists():
            return 0

        threshold = time.time() - (days * 86400)
        count = 0
        for path in trash_dir.iterdir():
            if path.is_file() and path.stat().st_mtime < threshold:
                path.unlink()
                count += 1
        return count
