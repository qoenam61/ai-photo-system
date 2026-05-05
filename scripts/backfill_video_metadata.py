"""1982 EVENT-L auto_video 자산 영상 메타 backfill.

배경: classify_server.py INSERT 버그로 is_video/duration_seconds/face_count
등 메타가 1982장에 영구 저장 안 됨. fix는 41be6e5 커밋. 본 스크립트는
기존 자산의 메타를 ffprobe(컨테이너 내부)로 재측정 + DB 갱신.

추가 동작:
  - duration < 3초 → TRASH (auto_short_video)로 강등 (사용자 명시 정책)
  - duration >= 3초 → EVENT-L 유지, 메타만 보강

Usage:
  PYTHONPATH=. poetry run python scripts/backfill_video_metadata.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import psycopg
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.pipeline.layer5_album import apply_grade_change  # noqa: E402

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)

# Container path → host path 매핑 (호스트 ffprobe 미설치 → 컨테이너 ffprobe 사용)
SHORT_VIDEO_THRESHOLD = 3.0


def fetch_targets(limit: int) -> list[tuple[str, str]]:
    """duration NULL인 EVENT-L auto_video 자산. (asset_id, source_path)."""
    sql = """
        SELECT asset_id::text, source_path
        FROM photo.classification
        WHERE grade='EVENT-L' AND grade_source='auto_video'
          AND duration_seconds IS NULL
        ORDER BY classified_at DESC
    """
    if limit > 0:
        sql += f" LIMIT {limit}"
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def fetch_immich_paths(asset_ids: list[str]) -> dict[str, str]:
    """asset_id stem → Immich originalPath 매핑."""
    if not asset_ids:
        return {}
    proc = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "--csv", "-c",
         """SELECT "originalPath" FROM asset WHERE "deletedAt" IS NULL"""],
        capture_output=True, text=True, check=True, timeout=120,
    )
    aid_set = set(asset_ids)
    out: dict[str, str] = {}
    for row in csv.reader(io.StringIO(proc.stdout)):
        if not row:
            continue
        path = row[0]
        stem = Path(path).stem
        if stem in aid_set:
            out[stem] = path
    return out


def ffprobe_in_container(immich_path: str) -> float | None:
    """photo-classify 컨테이너에서 ffprobe 실행 (호스트엔 미설치).

    Immich 경로 → 컨테이너 마운트 경로 변환 필요.
    photo-classify 컨테이너 path mappings: /storage → /Volumes/Immich-Storage
    """
    # photo-classify 마운트 path:
    # /storage/immich-media → /Volumes/Immich-Storage/immich-media
    # /storage/immich-uploads → /Volumes/Immich-Storage/immich-uploads
    # 따라서 immich_path가 /usr/src/app/upload/... (server 컨테이너 mount) 인 경우
    # photo-classify는 /storage/immich-uploads/... 로 매핑됨.
    container_path = immich_path
    if immich_path.startswith("/usr/src/app/upload"):
        container_path = immich_path.replace("/usr/src/app/upload", "/storage/immich-uploads", 1)
    elif immich_path.startswith("/Volumes/Immich-Storage"):
        container_path = immich_path.replace("/Volumes/Immich-Storage", "/storage", 1)

    try:
        r = subprocess.run(
            ["docker", "exec", "photo-classify",
             "ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of", "default=nw=1:nk=1", container_path],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return None
        s = r.stdout.strip()
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def update_metadata(asset_id: str, duration: float, demote_to_trash: bool) -> None:
    new_grade = "TRASH" if demote_to_trash else "EVENT-L"
    new_source = "auto_short_video" if demote_to_trash else "auto_video"
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE photo.classification
            SET is_video = TRUE,
                duration_seconds = %s,
                grade = %s,
                grade_source = %s,
                updated_at = NOW()
            WHERE asset_id = %s::uuid
        """, (duration, new_grade, new_source, asset_id))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="0=전수")
    args = parser.parse_args()

    targets = fetch_targets(args.limit)
    print(f"📼 backfill 대상: {len(targets)}장 (EVENT-L auto_video, duration NULL)")
    if not targets:
        return

    asset_ids = [a for a, _ in targets]
    print("🔍 Immich originalPath 매핑 ...")
    path_map = fetch_immich_paths(asset_ids)
    print(f"   매핑 성공: {len(path_map)}/{len(asset_ids)}")

    durations: dict[str, float] = {}
    fail = 0
    print("\n📊 ffprobe 측정 (컨테이너 내부) ...")
    for i, (aid, _) in enumerate(targets, 1):
        if i % 100 == 0:
            print(f"  진행 {i}/{len(targets)} (실패 {fail})")
        path = path_map.get(aid)
        if not path:
            fail += 1
            continue
        d = ffprobe_in_container(path)
        if d is None:
            fail += 1
            continue
        durations[aid] = d

    if not durations:
        print(f"\n❌ 측정 가능 자산 없음 (실패 {fail})")
        return

    short = [a for a, d in durations.items() if d < SHORT_VIDEO_THRESHOLD]
    long_ = [a for a, d in durations.items() if d >= SHORT_VIDEO_THRESHOLD]

    bucket = Counter()
    for d in durations.values():
        if d < 3:
            bucket["<3 (TRASH 강등)"] += 1
        elif d < 5:
            bucket["3-5초"] += 1
        elif d < 10:
            bucket["5-10초"] += 1
        elif d < 30:
            bucket["10-30초"] += 1
        else:
            bucket["≥30초"] += 1

    print(f"\n📊 측정 분포 (성공 {len(durations)}, 실패 {fail}):")
    for k, v in bucket.most_common():
        print(f"  {k}: {v}")

    print(f"\n🔧 업데이트 계획:")
    print(f"  TRASH 강등 (<3초): {len(short)}장")
    print(f"  EVENT-L 메타 보강 (≥3초): {len(long_)}장")

    if args.dry_run:
        print("\n💡 dry-run — DB/HDD 변경 X")
        return

    print("\n🔧 적용 중 ...")
    move_ok = move_fail = 0
    for i, (aid, dur) in enumerate(durations.items(), 1):
        if i % 100 == 0:
            print(f"  진행 {i}/{len(durations)} (HDD ok={move_ok} fail={move_fail})")
        demote = dur < SHORT_VIDEO_THRESHOLD
        update_metadata(aid, dur, demote)
        if demote:
            ok, _ = apply_grade_change(aid, "TRASH")
            if ok:
                move_ok += 1
            else:
                move_fail += 1

    print(f"\n📊 결과: 메타 갱신 {len(durations)} / "
          f"TRASH 강등 {len(short)} (HDD move ok={move_ok} fail={move_fail})")


if __name__ == "__main__":
    main()
