"""변환 없이 영상·초대용량 사진 직접 이동.

대상: In2022_본식영상 (3개 mp4) — EVENT-L 일괄
사용자 정책: 변환 X, 원본 그대로 외장하드 보관

DB insert + cp (cp는 시간 걸림, 백그라운드 실행 권장).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_DSN = (
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"
)
LIBRARY_EVENT_L = Path("/Volumes/Immich-Storage/immich-media/library/EVENT-L")

VIDEO_FILES = [
    Path("/Users/jw-home/백업/In2022_본식영상/0306FHD로프트가든344-티저.mp4"),
    Path("/Users/jw-home/백업/In2022_본식영상/0306FHD로프트가든344.mp4"),
    Path("/Users/jw-home/백업/In2022_본식영상/0306FHD로프트가든344_converting.mp4"),
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def video_meta(path: Path) -> dict:
    out: dict = {}
    try:
        # duration
        d = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            timeout=15,
        ).decode().strip()
        if d:
            out["duration"] = float(d)
        # resolution
        r = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=s=,:p=0", str(path)],
            timeout=15,
        ).decode().strip()
        if r and "," in r:
            w, h = r.split(",")
            out["width"], out["height"] = int(w), int(h)
    except Exception:
        pass
    return out


def main():
    LIBRARY_EVENT_L.mkdir(parents=True, exist_ok=True)
    conn = psycopg.connect(DB_DSN, autocommit=True)
    cur = conn.cursor()

    for src in VIDEO_FILES:
        if not src.exists():
            print(f"⚠️ Not found: {src}")
            continue

        asset_id = str(uuid.uuid4())
        target = LIBRARY_EVENT_L / f"{asset_id}.mp4"
        size_gb = src.stat().st_size / (1024**3)

        print(f"📹 {src.name} ({size_gb:.2f} GB)")
        print(f"   SHA256 계산 중...", end=" ", flush=True)
        t0 = time.time()
        sha = sha256_of(src)
        print(f"{int(time.time()-t0)}s")

        meta = video_meta(src)
        print(f"   duration={meta.get('duration', 0):.0f}s, "
              f"{meta.get('width', 0)}x{meta.get('height', 0)}")

        print(f"   복사 중 → {target.name}", end=" ", flush=True)
        t0 = time.time()
        # 큰 파일 안전: shutil.copy (data만, copystat 생략 — 외장 HDD APFS 호환)
        if target.exists():
            target.unlink()
        shutil.copy(src, target)
        print(f"{int(time.time()-t0)}s")

        cur.execute("""
            INSERT INTO photo.classification (
                asset_id, source_path, storage_path, sha256, file_size_bytes,
                is_video, grade, confidence, grade_source,
                width, height, duration_seconds,
                model_version, classified_at, moved_at
            ) VALUES (
                %s, %s, %s, %s, %s, TRUE, 'EVENT-L', 9,
                'folder_bulk_no_convert:In2022_본식영상',
                %s, %s, %s,
                'no_convert', NOW(), NOW()
            ) ON CONFLICT (asset_id) DO NOTHING
        """, (
            asset_id, str(src), str(target), sha, src.stat().st_size,
            meta.get("width"), meta.get("height"), meta.get("duration"),
        ))
        print(f"   ✅ DB insert\n")

    cur.close()
    conn.close()
    print("✅ 본식영상 3 mp4 이동 완료 (변환 X)")


if __name__ == "__main__":
    main()
