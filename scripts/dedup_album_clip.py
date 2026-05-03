"""앨범당 사진 1개만 유지 — Immich CLIP 임베딩 기반.

설계 §6 앨범 정합성 원칙: 동일 그룹 내 1장만 keep, 나머지는 album_member에서 제거.
등급은 유지 — 단지 album에서만 빠진다.

알고리즘:
  for each album:
    1. album_member.asset_id → Immich asset_id (originalPath stem)
    2. CLIP embedding 조회 (smart_search.embedding)
    3. pairwise cosine similarity ≥ THRESHOLD → union-find
    4. 클러스터당 quality 최고 1장 keep, 나머지 album_member DELETE

Immich DB는 호스트에 노출 안 됨 → docker exec psql로 쿼리.

Usage:
  PYTHONPATH=. poetry run python scripts/dedup_album_clip.py [--dry-run] [--threshold 0.93]
"""

from __future__ import annotations

import argparse
import csv
import io
import subprocess
from collections import defaultdict
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

OUR_DSN = (
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"
)


def immich_query(sql: str, stdin_input: str | None = None) -> list[list[str]]:
    """docker exec immich-postgres → CSV rows."""
    cmd = ["docker", "exec", "-i", "immich-postgres",
           "psql", "-U", "postgres", "-d", "immich",
           "-A", "-t", "-F", ",", "--csv", "-c", sql]
    proc = subprocess.run(
        cmd, input=stdin_input, capture_output=True, text=True, check=True,
    )
    reader = csv.reader(io.StringIO(proc.stdout))
    return [row for row in reader if row]


def immich_script(script: str) -> str:
    """Run multi-statement script via psql stdin, return raw stdout."""
    proc = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich",
         "-A", "-t", "-F", ",", "--csv"],
        input=script, capture_output=True, text=True, check=True,
    )
    return proc.stdout


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[rx] = ry


def fetch_immich_mapping() -> dict[str, str]:
    rows = immich_query(
        'SELECT id, "originalPath" FROM asset '
        "WHERE \"deletedAt\" IS NULL AND type = 'IMAGE'"
    )
    # CSV header included → skip if first row is column names
    out: dict[str, str] = {}
    for r in rows:
        if r[0] == "id":
            continue
        out[Path(r[1]).stem] = r[0]
    return out


def fetch_album_members(cur) -> dict[int, tuple[str, list[str]]]:
    cur.execute("""
        SELECT a.id, a.name, ARRAY_AGG(am.asset_id::text)
        FROM photo.album a
        JOIN photo.album_member am ON a.id = am.album_id
        GROUP BY a.id, a.name
        ORDER BY a.id
    """)
    return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def fetch_quality(cur, asset_uuids: list[str]) -> dict[str, float]:
    cur.execute("""
        SELECT asset_id::text,
               COALESCE(laplacian_variance, 0) * file_size_bytes
        FROM photo.classification
        WHERE asset_id = ANY(%s::uuid[])
    """, (asset_uuids,))
    return {r[0]: float(r[1] or 0) for r in cur.fetchall()}


def cluster_album(
    immich_ids: list[str], threshold: float
) -> list[list[int]]:
    if len(immich_ids) < 2:
        return [[i] for i in range(len(immich_ids))]

    uf = UnionFind(len(immich_ids))
    id_to_idx = {iid: i for i, iid in enumerate(immich_ids)}
    max_dist = 1 - threshold

    # 큰 앨범 대비 임시 테이블 + COPY FROM stdin
    copy_payload = "\n".join(immich_ids) + "\n\\.\n"
    script = (
        "BEGIN;\n"
        "CREATE TEMP TABLE _ids (id uuid);\n"
        "COPY _ids FROM stdin;\n"
        f"{copy_payload}"
        f'SELECT a."assetId"::text, b."assetId"::text '
        f'FROM smart_search a JOIN _ids ia ON a."assetId" = ia.id, '
        f'     smart_search b JOIN _ids ib ON b."assetId" = ib.id '
        f'WHERE a."assetId" < b."assetId" '
        f'  AND (a.embedding <=> b.embedding) <= {max_dist};\n'
        "ROLLBACK;\n"
    )
    raw = immich_script(script)
    for line in raw.splitlines():
        if not line or "," not in line:
            continue
        parts = line.split(",")
        if len(parts) < 2 or parts[0] == "assetId":
            continue
        a, b = parts[0], parts[1]
        if a in id_to_idx and b in id_to_idx:
            uf.union(id_to_idx[a], id_to_idx[b])

    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(immich_ids)):
        clusters[uf.find(i)].append(i)
    return list(clusters.values())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--threshold", type=float, default=0.93)
    args = parser.parse_args()

    print(f"📚 앨범 CLIP 중복 제거 (threshold={args.threshold})")
    print("1. Immich asset 매핑 로딩...")
    immich_map = fetch_immich_mapping()
    print(f"   {len(immich_map)}장")

    conn = psycopg.connect(OUR_DSN, autocommit=True)
    with conn.cursor() as cur:
        albums = fetch_album_members(cur)

    total_removed = 0
    for album_id, (name, our_uuids) in albums.items():
        immich_ids = [immich_map[u] for u in our_uuids if u in immich_map]
        uuid_by_immich = {immich_map[u]: u for u in our_uuids if u in immich_map}

        if len(immich_ids) < 2:
            continue

        # 큰 앨범은 N^2 SQL이 무거움 → batch 단위로 처리
        # 3000장이면 4.5M pair = 메모리 부담 → 일단 실행해보고 조정
        clusters = cluster_album(immich_ids, args.threshold)
        dup_clusters = [c for c in clusters if len(c) > 1]
        if not dup_clusters:
            print(f"  [{name[:30]:30s}] {len(immich_ids):4d}장 — 중복 없음")
            continue

        with conn.cursor() as cur:
            quality = fetch_quality(cur, list(uuid_by_immich.values()))

        to_remove: list[str] = []
        for cluster in dup_clusters:
            members = [(uuid_by_immich[immich_ids[idx]], idx) for idx in cluster]
            members.sort(key=lambda m: quality.get(m[0], 0), reverse=True)
            for losing_uuid, _ in members[1:]:
                to_remove.append(losing_uuid)

        print(f"  [{name[:30]:30s}] {len(immich_ids):4d}장 → "
              f"클러스터 {len(dup_clusters)}, 제거 {len(to_remove)}장")
        total_removed += len(to_remove)

        if not args.dry_run and to_remove:
            with conn.cursor() as cur:
                cur.execute(
                    """DELETE FROM photo.album_member
                       WHERE album_id = %s AND asset_id = ANY(%s::uuid[])""",
                    (album_id, to_remove),
                )

    print(f"\n총 제거: {total_removed}장")
    if args.dry_run:
        print("💡 dry-run — DB 변경 X")
    conn.close()


if __name__ == "__main__":
    main()
