"""Layer 5 — 등급 폴더 이동 + 뷰 심볼릭 + Immich originalPath 갱신.

설계 §5.5 — 분류 변경 후 외장 HDD `library/{GRADE}/` 폴더 정합 유지 +
`immich-views/{GRADE}/` 통합 view symlink 갱신 (legacy + iPhone 모두).

호스트 운용 (외장 HDD 직접 액세스). dedup_similar / reclassify_*
스크립트에서 호출. iPhone 업로드 자산(`/usr/src/app/upload/...`)은 library
폴더 이동은 안 하지만 view symlink는 등급별로 갱신.

  apply_grade_change(asset_id, new_grade) → (success, message)
  refresh_view_link(asset_id, immich_path, new_grade) → bool
"""

from __future__ import annotations

import csv
import io
import subprocess
from pathlib import Path

LIBRARY_HOST = Path("/Volumes/Immich-Storage/immich-media/library")
LIBRARY_IMMICH = "/mnt/external/library"
VIEWS_HOST = Path("/Volumes/Immich-Storage/immich-views")

VALID_GRADES = {  # 2026-05-09 안3: EVENT/EVENT-L → +/- 분할 (10등급)
    "BEST", "EVENT+", "EVENT-", "EVENT-L+", "EVENT-L-",
    "FOOD", "MEMORY+", "MEMORY-", "NORMAL", "TRASH",
}


def _immich_to_host(immich_path: str) -> Path:
    """Immich originalPath → 호스트 경로 (외장 HDD)."""
    if immich_path.startswith(LIBRARY_IMMICH):
        return Path(immich_path.replace(LIBRARY_IMMICH,
                                         "/Volumes/Immich-Storage/immich-media/library", 1))
    if immich_path.startswith("/usr/src/app/upload"):
        return Path(immich_path.replace("/usr/src/app/upload",
                                         "/Volumes/Immich-Storage/immich-uploads", 1))
    return Path(immich_path)


def refresh_view_link(asset_id: str, immich_path: str, new_grade: str) -> bool:
    """immich-views/{GRADE}/{asset_id}.{ext} symlink 갱신.

    이전 등급 view 자동 제거 (모든 등급 폴더 검사) + 새 등급 폴더 symlink 생성.
    target = 호스트 절대경로 (외장 HDD 자산).

    Returns: True (갱신 성공) / False (target 없음 등)
    """
    if new_grade not in VALID_GRADES:
        return False

    target = _immich_to_host(immich_path)
    if not target.exists():
        return False

    ext = target.suffix.lstrip(".")
    link_name = f"{asset_id}.{ext}"

    # 이전 등급 view 제거
    for g in VALID_GRADES:
        old_link = VIEWS_HOST / g / link_name
        if old_link.is_symlink() or old_link.exists():
            try:
                old_link.unlink()
            except Exception:
                pass

    # 새 등급 폴더 symlink 생성
    new_dir = VIEWS_HOST / new_grade
    new_dir.mkdir(parents=True, exist_ok=True)
    new_link = new_dir / link_name
    try:
        new_link.symlink_to(target)
        return True
    except FileExistsError:
        # race — 다시 unlink + symlink
        try:
            new_link.unlink()
            new_link.symlink_to(target)
            return True
        except Exception:
            return False
    except Exception:
        return False


def _immich_get_path(asset_id: str) -> tuple[str, str] | None:
    """Immich asset 조회 → (immich_id, originalPath). 없으면 None."""
    r = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "--csv", "-c",
         f"""SELECT id::text, "originalPath" FROM asset
             WHERE "deletedAt" IS NULL
               AND "originalPath" LIKE '%/{asset_id}.%'
             LIMIT 1"""],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode != 0:
        return None
    rows = [row for row in csv.reader(io.StringIO(r.stdout)) if row]
    if len(rows) < 2:
        return None
    return rows[1][0], rows[1][1]


def _immich_update_path(immich_id: str, new_path: str) -> bool:
    r = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "-c",
         f"UPDATE asset SET \"originalPath\"='{new_path}' "
         f"WHERE id='{immich_id}'"],
        capture_output=True, text=True, timeout=10,
    )
    return r.returncode == 0


def apply_grade_change(asset_id: str, new_grade: str) -> tuple[bool, str]:
    """자산을 새 등급 폴더로 이동 + Immich originalPath 갱신.

    Args:
        asset_id: photo.classification.asset_id (UUID)
        new_grade: 새 등급 (VALID_GRADES)

    Returns:
        (success, message). message:
          - "ok:{old}→{new}" 정상 이동
          - "noop:already_correct" 이미 올바른 위치
          - "skip:not_in_library:{path}" iPhone 업로드 등 library 외 자산
          - "fail:..." 실패
    """
    if new_grade not in VALID_GRADES:
        return False, f"fail:invalid_grade:{new_grade}"

    info = _immich_get_path(asset_id)
    if not info:
        return False, "fail:immich_no_match"

    immich_id, immich_path = info

    if not immich_path.startswith(LIBRARY_IMMICH):
        # iPhone 업로드 등 library/ 외부 자산은 폴더 이동 안 하지만 view는 갱신
        view_ok = refresh_view_link(asset_id, immich_path, new_grade)
        msg = "skip:not_in_library"
        if view_ok:
            msg += "+view_ok"
        return False, msg

    current_grade = Path(immich_path).parent.name
    if current_grade == new_grade:
        # library 자산은 이미 정합. 단 view symlink는 항상 갱신 (안전망).
        refresh_view_link(asset_id, immich_path, new_grade)
        return True, "noop:already_correct"

    fname = Path(immich_path).name
    old_host = LIBRARY_HOST / current_grade / fname
    new_host = LIBRARY_HOST / new_grade / fname

    if not old_host.exists():
        return False, f"fail:file_missing:{old_host}"

    new_host.parent.mkdir(parents=True, exist_ok=True)
    try:
        old_host.rename(new_host)
    except Exception as e:
        return False, f"fail:rename_failed:{e}"

    new_immich_path = f"{LIBRARY_IMMICH}/{new_grade}/{fname}"
    if not _immich_update_path(immich_id, new_immich_path):
        # 파일 이동은 됐지만 DB 갱신 실패 — 롤백 시도
        try:
            new_host.rename(old_host)
        except Exception:
            pass
        return False, "fail:immich_update_failed"

    # immich-views 통합 view symlink 갱신
    refresh_view_link(asset_id, new_immich_path, new_grade)

    return True, f"ok:{current_grade}→{new_grade}"


def apply_grade_changes_batch(items: list[tuple[str, str]]) -> dict[str, int]:
    """[(asset_id, new_grade), ...] 일괄 처리.

    Returns: {"ok": N, "noop": N, "skip": N, "fail": N, "details": [...]}
    """
    counts = {"ok": 0, "noop": 0, "skip": 0, "fail": 0}
    details: list[tuple[str, bool, str]] = []
    for asset_id, new_grade in items:
        success, msg = apply_grade_change(asset_id, new_grade)
        category = msg.split(":")[0]
        counts[category] = counts.get(category, 0) + 1
        details.append((asset_id, success, msg))
    return {**counts, "details": details}
