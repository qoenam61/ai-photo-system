"""DB photo.classification + photo.album → Immich Album 동기화.

매칭: Immich asset.originalPath → 파일명에서 our UUID → photo.classification 조회.

생성 Album:
  등급 (8개): EVENT, EVENT-L, BEST, FOOD, MEMORY+, MEMORY-, NORMAL, TRASH
  추억앨범:  photo.album 의 모든 row

Usage:
  IMMICH_API_KEY=... PYTHONPATH=. poetry run python scripts/sync_immich_albums.py
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import psycopg
from dotenv import load_dotenv

load_dotenv()

IMMICH_URL = "http://localhost:2283"
KEY = os.environ["IMMICH_API_KEY"]
DB_DSN = (
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"
)
HEADERS = {"x-api-key": KEY, "Accept": "application/json"}
LIB_ID = "a6153155-c7a8-4d63-8d92-20d0bac8820f"

GRADE_ALBUMS = {
    "EVENT":   "⭐ EVENT",
    "EVENT-L": "⭐ EVENT-L",
    "BEST":    "✦ BEST",
    "FOOD":    "🍽 FOOD",
    "MEMORY+": "◆ MEMORY+",
    "MEMORY-": "◇ MEMORY-",
    "NORMAL":  "○ NORMAL",
    "TRASH":   "🗑 TRASH",
}


def fetch_immich_assets(client: httpx.Client) -> dict[str, str]:
    """Immich 모든 자산 조회 → {our_uuid: immich_asset_id}."""
    mapping: dict[str, str] = {}
    page = 1
    page_size = 1000
    while True:
        r = client.get(f"{IMMICH_URL}/api/libraries/{LIB_ID}", headers=HEADERS)
        # Library statistics는 카운트만
        # asset 목록은 search API
        body = {"libraryId": LIB_ID, "page": page, "size": page_size}
        r = client.post(f"{IMMICH_URL}/api/search/metadata", json=body, headers=HEADERS)
        if r.status_code != 200:
            print(f"  ⚠️ search failed: {r.status_code} {r.text[:100]}")
            break
        data = r.json()
        items = data.get("assets", {}).get("items", [])
        if not items:
            break
        for asset in items:
            path = asset.get("originalPath", "")
            our_uuid = Path(path).stem
            mapping[our_uuid] = asset["id"]
        next_page = data.get("assets", {}).get("nextPage")
        if not next_page:
            break
        page = int(next_page)
    return mapping


def get_or_create_album(client: httpx.Client, name: str) -> str:
    """이름으로 앨범 조회 or 생성."""
    r = client.get(f"{IMMICH_URL}/api/albums", headers=HEADERS)
    for alb in r.json():
        if alb["albumName"] == name:
            return alb["id"]
    r = client.post(f"{IMMICH_URL}/api/albums",
                    json={"albumName": name, "assetIds": []}, headers=HEADERS)
    return r.json()["id"]


def add_assets(client: httpx.Client, album_id: str, asset_ids: list[str]) -> int:
    """앨범에 자산 추가 (배치 500). 추가된 수 반환."""
    added = 0
    for i in range(0, len(asset_ids), 500):
        batch = asset_ids[i:i+500]
        r = client.put(
            f"{IMMICH_URL}/api/albums/{album_id}/assets",
            json={"ids": batch}, headers=HEADERS,
        )
        if r.status_code == 200:
            for x in r.json():
                if x.get("success"):
                    added += 1
    return added


def main() -> None:
    print("📚 Immich Album 동기화\n")

    with httpx.Client(timeout=60) as client:
        # 1. Immich 자산 매핑
        print("1. Immich 자산 조회...")
        mapping = fetch_immich_assets(client)
        print(f"   {len(mapping)}장 매핑")

        if not mapping:
            print("   ⚠️ 자산 0건 — Library scan 미완료. 잠시 후 재시도")
            return

        # 2. DB grade 조회 + 매칭
        conn = psycopg.connect(DB_DSN)
        with conn.cursor() as cur:
            cur.execute("SELECT asset_id, grade FROM photo.classification")
            db_rows = cur.fetchall()
        conn.close()

        # asset_id (str UUID) → grade
        db_map = {str(aid): g for aid, g in db_rows}

        # 3. 등급별 Album 생성·자산 추가
        print("\n2. 등급 Album 동기화...")
        for grade, album_name in GRADE_ALBUMS.items():
            asset_ids = [
                immich_id for our_uuid, immich_id in mapping.items()
                if db_map.get(our_uuid) == grade
            ]
            if not asset_ids:
                continue
            album_id = get_or_create_album(client, album_name)
            added = add_assets(client, album_id, asset_ids)
            print(f"   {album_name:18s} → {added}/{len(asset_ids)}장 추가")

        # 4. 추억앨범 동기화 (dedup_excluded 자산 제외 — 2026-05-08 P0-A)
        print("\n3. 추억앨범 동기화...")
        conn = psycopg.connect(DB_DSN)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.name, ARRAY_AGG(am.asset_id::text)
                FROM photo.album a
                JOIN photo.album_member am ON a.id = am.album_id
                WHERE am.dedup_excluded = FALSE
                GROUP BY a.id, a.name
                ORDER BY a.album_type, a.name
            """)
            for name, asset_ids_db in cur.fetchall():
                asset_ids = [
                    mapping[our_uuid] for our_uuid in asset_ids_db
                    if our_uuid in mapping
                ]
                if not asset_ids:
                    continue
                album_id = get_or_create_album(client, name)
                added = add_assets(client, album_id, asset_ids)
                print(f"   {name[:30]:30s} → {added}/{len(asset_ids)}장")
        conn.close()

        print("\n✅ 동기화 완료")


if __name__ == "__main__":
    main()
