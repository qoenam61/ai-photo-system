"""신규 Immich 자산 자동 분류 — classify-service 호출.

순서:
  1. Immich에서 photo.classification에 없는 자산 조회
  2. 각 자산을 classify-service /classify_and_persist 로 POST
  3. grade 결정 시 Immich Album에 추가

Usage:
  PYTHONPATH=. poetry run python scripts/auto_classify_pending.py [--limit N]

환경:
  CLASSIFY_URL  (기본 http://127.0.0.1:8765)
  IMMICH_API_KEY (.env)
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import subprocess
from pathlib import Path

import httpx
import psycopg
from dotenv import load_dotenv

load_dotenv()

CLASSIFY_URL = os.getenv("CLASSIFY_URL", "http://127.0.0.1:8765")
IMMICH_URL = "http://localhost:2283"
IMMICH_KEY = os.environ.get("IMMICH_API_KEY", "")

DB_DSN = (
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"
)

GRADE_ALBUMS = {  # 2026-05-09 안3: EVENT/EVENT-L → +/- 분할 (10등급)
    "EVENT+":   "⭐ EVENT+",
    "EVENT-":   "⭐ EVENT-",
    "EVENT-L+": "⭐ EVENT-L+",
    "EVENT-L-": "⭐ EVENT-L-",
    "BEST":     "✦ BEST",
    "FOOD":     "🍽 FOOD",
    "MEMORY+":  "◆ MEMORY+",
    "MEMORY-":  "◇ MEMORY-",
    "NORMAL":   "○ NORMAL",
    "TRASH":    "🗑 TRASH",
}


def fetch_pending() -> list[tuple[str, str]]:
    """Immich asset 中 classification에 없는 것. (immich_id, originalPath)."""
    proc = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich",
         "--csv", "-c",
         'SELECT id::text, "originalPath" FROM asset '
         "WHERE \"deletedAt\" IS NULL AND type = 'IMAGE' "
         "AND \"originalPath\" NOT LIKE '%/encoded-video/%' "
         "AND \"originalPath\" NOT LIKE '%/thumbs/%'"],
        capture_output=True, text=True, check=True,
    )
    rows = [r for r in csv.reader(io.StringIO(proc.stdout)) if r]
    if rows and rows[0][0] == "id":
        rows = rows[1:]

    immich_ids = [(r[0], r[1]) for r in rows]
    if not immich_ids:
        return []

    # Filter: classification에 없는 것만.
    # 기존 자산은 originalPath stem이 our UUID (마이그레이션 시 부여).
    # iPhone 업로드는 immich_id가 fresh.
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT asset_id::text FROM photo.classification")
        classified = {row[0] for row in cur.fetchall()}

    out = []
    for iid, path in immich_ids:
        stem = Path(path).stem
        if iid in classified or stem in classified:
            continue
        out.append((iid, path))
    return out


def get_or_create_album(client: httpx.Client, name: str) -> str:
    headers = {"x-api-key": IMMICH_KEY, "Accept": "application/json"}
    r = client.get(f"{IMMICH_URL}/api/albums", headers=headers)
    for alb in r.json():
        if alb["albumName"] == name:
            return alb["id"]
    r = client.post(f"{IMMICH_URL}/api/albums",
                    json={"albumName": name, "assetIds": []}, headers=headers)
    return r.json()["id"]


def add_to_album(client: httpx.Client, album_id: str, immich_id: str) -> None:
    headers = {"x-api-key": IMMICH_KEY}
    client.put(f"{IMMICH_URL}/api/albums/{album_id}/assets",
               json={"ids": [immich_id]}, headers=headers)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20,
                        help="한 번 실행 최대 처리 자산 수")
    args = parser.parse_args()

    pending = fetch_pending()
    if not pending:
        print("✅ 분류 대기 자산 없음")
        return

    print(f"🔄 분류 대기 {len(pending)}건 (이번 실행 limit={args.limit})")
    pending = pending[:args.limit]

    album_cache: dict[str, str] = {}
    classify_client = httpx.Client(timeout=180)
    immich_client = httpx.Client(timeout=30)

    success = fail = 0
    for immich_id, path in pending:
        try:
            r = classify_client.post(
                f"{CLASSIFY_URL}/classify_and_persist",
                json={"immich_id": immich_id, "path": path},
            )
            if r.status_code != 200:
                print(f"  ✗ {immich_id[:8]} {Path(path).name}: HTTP {r.status_code}")
                fail += 1
                continue
            data = r.json()
            grade = data["grade"]
            album_name = GRADE_ALBUMS.get(grade)
            if album_name:
                if album_name not in album_cache:
                    album_cache[album_name] = get_or_create_album(immich_client, album_name)
                add_to_album(immich_client, album_cache[album_name], immich_id)
            print(f"  ✓ {immich_id[:8]} {Path(path).name} → {grade} ({data['source']})")
            success += 1
        except Exception as e:
            print(f"  ✗ {immich_id[:8]} {Path(path).name}: {e}")
            fail += 1

    print(f"\n✅ 성공 {success} / 실패 {fail}")
    classify_client.close()
    immich_client.close()


if __name__ == "__main__":
    main()
