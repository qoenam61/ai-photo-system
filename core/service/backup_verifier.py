"""백업 무결성 검증 — Phase 5 + Layer 6 삭제 전 게이트.

설계 §5 도메인 안전 영역: **3중 검증 PASS 시에만 verified=True**.
하나라도 실패하면 절대 삭제 금지.

검증 단계:
  1. **DB 일관성**: photo.classification에 asset 존재 + sha256 NOT NULL
  2. **파일 존재**: Immich External Library 경로에 파일 존재 + 크기 일치
  3. **SHA256 일치**: 파일 실제 SHA256 == DB 기록 SHA256
  4. **Immich 등록**: Immich asset 테이블에 동일 originalPath 등록 + deletedAt IS NULL

ALL PASS → verified=True
ANY FAIL → verified=False, reason 필드에 실패 사유

⚠️ 이 모듈은 절대 삭제 자체를 수행하지 않음. 검증 결과만 반환.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import psycopg


PHOTO_DSN = os.getenv(
    "PHOTO_DB_DSN",
    "host=trading_postgres port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)
IMMICH_DSN = os.getenv(
    "IMMICH_DB_DSN",
    "host=immich-postgres port=5432 dbname=immich "
    "user=postgres password=immich_pg_2026",
)

# Immich originalPath → classify 컨테이너 내부 경로 매핑.
# classify_server.py의 PATH_MAPPINGS와 동일 — 중복 정의는 의도적 (모듈 독립성).
PATH_MAPPINGS = [
    ("/mnt/external", "/storage/immich-media"),
    ("/usr/src/app/upload", "/storage/immich-uploads"),
    ("/Volumes/Immich-Storage", "/storage"),
]


def _resolve(path: str) -> Path:
    for src, dst in PATH_MAPPINGS:
        if path.startswith(src):
            return Path(dst + path[len(src):])
    return Path(path)


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(slots=True)
class VerifyResult:
    asset_id: str
    verified: bool
    reason: str = ""
    expected_sha: str = ""
    actual_sha: str = ""
    expected_size: int = 0
    actual_size: int = 0
    immich_id: str = ""
    immich_path: str = ""


def verify_asset(asset_id: str) -> VerifyResult:
    """단일 asset의 백업 무결성 3중 검증.

    Args:
        asset_id: photo.classification.asset_id (UUID).
    Returns:
        VerifyResult — verified=True 시에만 삭제 안전.
    """
    res = VerifyResult(asset_id=asset_id, verified=False)

    # 1. DB 일관성
    with psycopg.connect(PHOTO_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT sha256, file_size_bytes, source_path, storage_path, grade
            FROM photo.classification
            WHERE asset_id = %s
        """, (asset_id,))
        row = cur.fetchone()
    if not row:
        res.reason = "db_no_classification"
        return res

    sha, size, source_path, storage_path, grade = row
    if not sha or len(sha) != 64:
        res.reason = "db_invalid_sha"
        return res
    if not size or size <= 0:
        res.reason = "db_invalid_size"
        return res

    res.expected_sha = sha
    res.expected_size = size

    # 2. Immich 자산 등록 확인 (Immich DB에 우리 sha256 또는 originalPath 일치)
    # Immich는 자체 hash 테이블을 가짐 (asset.checksum) — base64 형태.
    # SHA256 hex → bytes → base64로 비교하거나, originalPath stem 매칭.
    immich_id, immich_path = _find_immich_asset(asset_id, sha)
    if not immich_id:
        res.reason = "immich_not_found"
        return res
    res.immich_id = immich_id
    res.immich_path = immich_path

    # 3. 파일 실제 존재 + 크기 일치
    p = _resolve(immich_path)
    if not p.exists() or not p.is_file():
        res.reason = f"file_missing:{p}"
        return res

    actual_size = p.stat().st_size
    res.actual_size = actual_size
    if actual_size != size:
        res.reason = f"size_mismatch:expected={size}/actual={actual_size}"
        return res

    # 4. SHA256 일치 (가장 비싼 검증 — 마지막)
    actual_sha = _compute_sha256(p)
    res.actual_sha = actual_sha
    if actual_sha != sha:
        res.reason = f"sha256_mismatch"
        return res

    res.verified = True
    res.reason = "ok"
    return res


def _find_immich_asset(asset_id: str, sha256_hex: str) -> tuple[str, str]:
    """Immich asset 매칭. originalPath stem == asset_id 우선, 폴백 sha256.

    Returns:
        (immich_id, originalPath) — 없으면 ("", "").
    """
    # 1차: originalPath stem == asset_id (마이그레이션 시 부여한 우리 UUID)
    with psycopg.connect(IMMICH_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id::text, "originalPath"
            FROM asset
            WHERE "deletedAt" IS NULL
              AND "originalPath" LIKE %s
            LIMIT 1
        """, (f"%/{asset_id}.%",))
        row = cur.fetchone()
        if row:
            return row[0], row[1]

        # 2차: checksum 매칭 (Immich는 base64 인코딩 sha1, 우리는 sha256 — 직접 비교 불가)
        # → 우리 sha256 hex → 바이너리 → base64 변환 시 sha256 일치 시 매칭
        # Immich asset.checksum은 sha1 (20 bytes). 우리는 sha256 (32 bytes). 호환 X.
        # 따라서 폴백은 path-based만.
    return "", ""


def verify_assets_batch(asset_ids: list[str]) -> list[VerifyResult]:
    return [verify_asset(aid) for aid in asset_ids]
