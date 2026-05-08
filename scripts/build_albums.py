"""추억앨범 자동 생성 — photo.classification 기반.

3가지 방식:
  A. 폴더 기반: 백업 폴더 이름 그대로 앨범 (In2022_본식사진 → "2022 본식 추억")
  B. 연도별: EXIF year → "YYYY년 추억"
  C. 시간·장소 군집: ±2h + GPS ±500m (백업 폴더 외 자산용, 추후)

Usage:
  PYTHONPATH=. poetry run python scripts/build_albums.py
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_DSN = (
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"
)

BACKUP_DIR = Path("/Users/jw-home/백업")

# 폴더 → 앨범 이름 매핑
FOLDER_ALBUM_MAP = {
    "In2022_본식사진": "2022 결혼식 본식 추억 (원본)",
    "In2022_본식영상": "2022 결혼식 본식 영상",
    "In2022_웨딩사진": "2022 결혼식 수정본",
    "In2015": "2015년 추억",
    "In2021": "2021년 추억",
    "etc": "기타 추억",
    "로이": "로이 (반려동물)",
}


def get_or_create_album(cur, name: str, album_type: str, source_folder: str | None = None) -> int:
    """name UNIQUE — 같은 이름 album은 단일 row (album_type 무관)."""
    cur.execute("SELECT id FROM photo.album WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """INSERT INTO photo.album (name, album_type, source_folder)
           VALUES (%s, %s, %s) RETURNING id""",
        (name, album_type, source_folder),
    )
    return cur.fetchone()[0]


def build_folder_albums(conn) -> int:
    """A. 폴더 기반 앨범. classification.source_path → top folder → album."""
    added = 0
    with conn.cursor() as cur:
        cur.execute("SELECT asset_id, source_path FROM photo.classification")
        for asset_id, source_path in cur.fetchall():
            try:
                p = Path(source_path)
                top = unicodedata.normalize(
                    "NFC", p.relative_to(BACKUP_DIR).parts[0]
                )
            except (ValueError, IndexError):
                continue
            album_name = FOLDER_ALBUM_MAP.get(top)
            if not album_name:
                continue
            album_id = get_or_create_album(cur, album_name, "folder_based", top)
            cur.execute(
                """INSERT INTO photo.album_member (album_id, asset_id)
                   VALUES (%s, %s) ON CONFLICT DO NOTHING""",
                (album_id, asset_id),
            )
            if cur.rowcount > 0:
                added += 1
    return added


def build_year_albums(conn) -> int:
    """B. 연도별 추억 앨범. EXIF datetime 기반.

    네이밍 정책: "{year}년 추억" 고정 (기존 앨범 호환). Groq 자연 네이밍은
    `core/service/album_namer.py`로 별도 제공 (이벤트·장소 기반 신규 앨범에서 사용).
    """
    added = 0
    with conn.cursor() as cur:
        cur.execute("""
            SELECT asset_id, EXTRACT(YEAR FROM exif_datetime)::int AS year
            FROM photo.classification
            WHERE exif_datetime IS NOT NULL
        """)
        for asset_id, year in cur.fetchall():
            album_name = f"{year}년 추억"
            album_id = get_or_create_album(cur, album_name, "year_memory")
            cur.execute(
                """INSERT INTO photo.album_member (album_id, asset_id)
                   VALUES (%s, %s) ON CONFLICT DO NOTHING""",
                (album_id, asset_id),
            )
            if cur.rowcount > 0:
                added += 1
    return added


def update_album_stats(conn) -> None:
    """앨범 메타 갱신 (asset_count, started_at, ended_at, cover_asset_id).

    dedup_excluded=TRUE 멤버는 통계·cover 후보에서 제외 (2026-05-08 P0-A).
    """
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE photo.album a SET
                asset_count = sub.cnt,
                started_at = sub.min_dt,
                ended_at = sub.max_dt,
                cover_asset_id = sub.cover
            FROM (
                SELECT
                    am.album_id,
                    COUNT(*) AS cnt,
                    MIN(c.exif_datetime) AS min_dt,
                    MAX(c.exif_datetime) AS max_dt,
                    (
                        SELECT c2.asset_id
                        FROM photo.album_member am2
                        JOIN photo.classification c2 ON am2.asset_id = c2.asset_id
                        WHERE am2.album_id = am.album_id
                          AND am2.dedup_excluded = FALSE
                          AND c2.grade IN ('EVENT', 'BEST')
                        ORDER BY c2.confidence DESC NULLS LAST, c2.classified_at
                        LIMIT 1
                    ) AS cover
                FROM photo.album_member am
                JOIN photo.classification c ON am.asset_id = c.asset_id
                WHERE am.dedup_excluded = FALSE
                GROUP BY am.album_id
            ) sub
            WHERE a.id = sub.album_id
        """)


def main():
    conn = psycopg.connect(DB_DSN, autocommit=True)
    try:
        print("📚 추억앨범 자동 생성")
        added_folder = build_folder_albums(conn)
        print(f"  A. 폴더 기반: {added_folder} 자산 추가")
        added_year = build_year_albums(conn)
        print(f"  B. 연도별:    {added_year} 자산 추가")

        update_album_stats(conn)
        print("  통계 갱신 완료")

        with conn.cursor() as cur:
            cur.execute("""
                SELECT album_type, name, asset_count, started_at, ended_at
                FROM photo.album
                ORDER BY album_type, asset_count DESC
            """)
            print("\n📋 생성된 앨범:")
            for at, name, cnt, st, et in cur.fetchall():
                period = ""
                if st and et:
                    period = f" ({st.strftime('%Y-%m')} ~ {et.strftime('%Y-%m')})"
                print(f"  [{at:14s}] {name:35s} {cnt}장{period}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
