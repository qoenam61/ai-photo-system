"""BEST unknown 자산 OpenCV 신호 재수집 + sub_category 재계산.

평가단 5/11 발견: BEST unknown 2,354장 中 2,341장이 laplacian=0/NULL.
iPhone 업로드 자산이 백업 시점에 OpenCV 신호 미수집 — 출처 불명 아닌 분석 누락.

흐름:
  1. BEST + sub_category='unknown' + lap=0/NULL 자산 조회
  2. 컨테이너 내부 (/storage 마운트)에서 opencv_signals 호출
  3. face_count/laplacian/is_screenshot/camera_make UPDATE
  4. apply_subcategory()로 sub_category 재계산

Usage:
  docker exec photo-classify python3 /app/scripts/backfill_opencv_signals.py
  또는 호스트:
  PYTHONPATH=. poetry run python scripts/backfill_opencv_signals.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, "/app" if Path("/app/core").exists()
                else str(Path(__file__).resolve().parent.parent))

import psycopg
from core.service.classifier import opencv_signals, apply_subcategory


DB_DSN = os.getenv(
    "PHOTO_DB_DSN",
    os.getenv("PHOTO_DB_DSN_HOST",
              "host=localhost port=5432 dbname=trading_db "
              "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"),
)

# 컨테이너 path 매핑 (classify_server.py PATH_MAPPINGS와 동일)
PATH_MAPPINGS = [
    ("/mnt/external", "/storage/immich-media"),
    ("/usr/src/app/upload", "/storage/immich-uploads"),
    ("/Volumes/Immich-Storage", "/storage"),
]
# 호스트 실행 시
HOST_MAPPINGS = [
    ("/mnt/external", "/Volumes/Immich-Storage/immich-media"),
    ("/usr/src/app/upload", "/Volumes/Immich-Storage/immich-uploads"),
]


def resolve_path(p: str) -> Path:
    is_container = Path("/storage").exists()
    mappings = PATH_MAPPINGS if is_container else HOST_MAPPINGS
    for src, dst in mappings:
        if p.startswith(src):
            return Path(dst + p[len(src):])
    return Path(p)


def main() -> int:
    print("🔍 BEST unknown OpenCV 재수집 시작 ...")
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT asset_id::text, source_path, grade_source
            FROM photo.classification
            WHERE grade='BEST' AND sub_category='unknown'
              AND (laplacian_variance IS NULL OR laplacian_variance = 0)
              AND is_video = FALSE
            ORDER BY asset_id
        """)
        rows = cur.fetchall()
    print(f"   대상: {len(rows)}장")

    updated = no_file = error = 0
    new_subcat: dict[str, int] = {}

    with psycopg.connect(DB_DSN, autocommit=False) as conn:
        for i, (asset_id, src_path, grade_src) in enumerate(rows, 1):
            if i % 200 == 0:
                conn.commit()
                print(f"  진행 {i}/{len(rows)} (updated {updated}, "
                      f"no_file {no_file}, error {error})")

            target = resolve_path(src_path)
            if not target.exists():
                no_file += 1
                continue

            try:
                sig = opencv_signals(target)
            except Exception as e:
                error += 1
                if error <= 5:
                    print(f"  ⚠️ {asset_id[:8]} error: {type(e).__name__}: {str(e)[:80]}")
                continue

            # sub_category 재계산 (grade=BEST 유지)
            new_sub = apply_subcategory("BEST", sig, src_path, grade_src or "")
            new_subcat[new_sub] = new_subcat.get(new_sub, 0) + 1

            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE photo.classification
                    SET face_count = %s,
                        laplacian_variance = %s,
                        is_screenshot = %s,
                        camera_make = %s,
                        sub_category = %s,
                        updated_at = NOW()
                    WHERE asset_id = %s::uuid
                """, (sig.face_count, sig.laplacian_variance,
                      sig.is_screenshot, sig.camera_make,
                      new_sub, asset_id))
            updated += 1
        conn.commit()

    print()
    print(f"📊 결과: updated={updated} / no_file={no_file} / error={error}")
    print(f"   새 sub_category 분포:")
    for sub, n in sorted(new_subcat.items(), key=lambda x: -x[1]):
        print(f"     {sub}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
