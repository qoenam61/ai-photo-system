"""Layer 5 — 등급 폴더 이동 + Immich originalPath 갱신.

설계 §5.5 — 분류 변경 후 외장 HDD `library/{GRADE}/` 폴더 정합 유지.

호스트 운용 (외장 HDD 직접 액세스). dedup_similar / reclassify_*
스크립트에서 호출. iPhone 업로드 자산(`/usr/src/app/upload/...`)은 등급 폴더
사용 안 함 — 변경 없음.

  apply_grade_change(asset_id, new_grade) → (success, message)
"""

from __future__ import annotations

import csv
import io
import subprocess
from pathlib import Path

LIBRARY_HOST = Path("/Volumes/Immich-Storage/immich-media/library")
LIBRARY_IMMICH = "/mnt/external/library"

VALID_GRADES = {"BEST", "EVENT", "EVENT-L", "FOOD",
                "MEMORY+", "MEMORY-", "NORMAL", "TRASH"}


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
        return False, f"skip:not_in_library:{immich_path}"

    current_grade = Path(immich_path).parent.name
    if current_grade == new_grade:
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
