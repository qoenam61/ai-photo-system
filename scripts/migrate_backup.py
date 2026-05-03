"""백업 폴더 마이그레이션 — /Users/jw-home/백업 → /Volumes/Immich-Storage.

Phases (한 자산당 일괄 처리):
  A. 인벤토리: 코덱·해상도·EXIF·SHA256
  B. 변환: HEIC→JPEG, HEVC→H.264 (필요 시)
  C. 분류: LLM 앙상블 4등급 + 자동 4등급 + 영상 < 5초 → TRASH
  D. DB insert: photo.classification + conversion_log
  E. Immich-Storage 이동: library/{등급}/<UUID>.{ext}
  F. 뷰 폴더 심볼릭 링크

Usage:
  PYTHONPATH=. poetry run python scripts/migrate_backup.py [--limit 100] [--dry-run]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import httpx
import numpy as np
import psycopg
from dotenv import load_dotenv
from PIL import Image, ExifTags

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.client.groq_client import GroqClient

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
BACKUP_DIR = Path("/Users/jw-home/백업")
STORAGE_ROOT = Path("/Volumes/Immich-Storage")
LIBRARY_DIR = STORAGE_ROOT / "immich-media" / "library"
VIEWS_DIR = STORAGE_ROOT / "immich-views"
WORK_DIR = STORAGE_ROOT / "_convert" / "work"
QUARANTINE_DIR = STORAGE_ROOT / "_convert" / "quarantine"

DB_DSN = (
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6"
)

OLLAMA_URL = "http://localhost:11434/api/generate"
QWEN_MODEL = "qwen2.5vl:7b-q4_K_M"

IMAGE_EXTS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp", ".dng"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
LLM_GRADES = {"EVENT", "BEST", "FOOD", "TRASH"}
ALL_GRADES = ["EVENT", "EVENT-L", "BEST", "FOOD", "MEMORY+", "MEMORY-", "NORMAL", "TRASH"]

PROMPT = """가족 사진 분류기. 4등급 中 정확히 하나로 분류:

판단 순서:
1. UI 스크린샷/완전 흑백/심한 흔들림 → TRASH
2. 음식이 화면 50%+ → FOOD
3. 사람 3+ OR (케이크·꽃다발·드레스·한복·웨딩·돌잔치·생일·졸업·기념일·가족스튜디오·신생아·만삭·100일·돌·칠순) → EVENT
4. 그 외 (인물 사진이거나 풍경/사물 等) → BEST

JSON만 출력:
{"grade":"<EVENT|BEST|FOOD|TRASH>","confidence":<1-10>,"reason":"<짧게>"}"""

# 폴더별 일괄 매핑 (LLM skip — 사용자 확정 정책)
FOLDER_GRADE_MAP: dict[str, str] = {
    "In2022_본식사진": "EVENT-L",   # 본식 원본, 외장하드만 (수정본 외)
    "In2022_본식영상": "EVENT-L",   # 본식 영상 원본
    "In2022_웨딩사진": "EVENT",     # 수정본
}


# ─────────────────────────────────────────────
# 데이터 모델
# ─────────────────────────────────────────────
@dataclass
class Asset:
    source_path: Path
    asset_id: str = ""
    sha256: str = ""
    file_size: int = 0
    is_video: bool = False
    converted_path: Path | None = None
    final_ext: str = ""

    width: int = 0
    height: int = 0
    duration_seconds: float = 0.0
    exif_datetime: str | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    camera_make: str | None = None
    camera_model: str | None = None

    face_count: int = 0
    laplacian_variance: float = 0.0
    is_screenshot: bool = False

    qwen_grade: str = ""
    qwen_conf: int = 0
    qwen_ms: int = 0
    groq_grade: str = ""
    groq_conf: int = 0
    groq_ms: int = 0

    grade: str = ""
    confidence: int = 0
    grade_source: str = ""

    storage_path: Path | None = None
    error: str = ""


# ─────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────
def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_image_b64(path: Path, max_dim: int = 1024) -> str:
    suffix = path.suffix.lower()
    if suffix in (".heic", ".heif"):
        tmp = Path("/tmp") / f"_mig_{os.getpid()}_{path.stem}.jpg"
        subprocess.run(
            ["sips", "-s", "format", "jpeg", "-Z", str(max_dim), str(path), "--out", str(tmp)],
            capture_output=True, check=True, timeout=30,
        )
        data = tmp.read_bytes()
        tmp.unlink(missing_ok=True)
        return base64.b64encode(data).decode()
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_dim, max_dim))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode()


def parse_json(text: str) -> dict:
    txt = text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(txt)


def extract_exif(path: Path) -> dict:
    """기본 EXIF 추출 (PIL 기반)."""
    out: dict = {}
    try:
        img = Image.open(path)
        exif = img._getexif() or {}
        named = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
        out["width"], out["height"] = img.size
        if "DateTimeOriginal" in named:
            dt = str(named["DateTimeOriginal"])
            # EXIF "YYYY:MM:DD HH:MM:SS" → ISO "YYYY-MM-DD HH:MM:SS"
            if len(dt) >= 10 and dt[4] == ":" and dt[7] == ":":
                dt = f"{dt[:4]}-{dt[5:7]}-{dt[8:]}"
            out["exif_datetime"] = dt
        if "Make" in named:
            out["camera_make"] = str(named["Make"])[:50]
        if "Model" in named:
            out["camera_model"] = str(named["Model"])[:100]
        gps = named.get("GPSInfo", {})
        if gps and 2 in gps and 4 in gps:
            def to_deg(coord, ref):
                d, m, s = coord
                deg = float(d) + float(m)/60 + float(s)/3600
                return -deg if ref in ("S", "W") else deg
            try:
                out["gps_lat"] = round(to_deg(gps[2], gps.get(1, "N")), 7)
                out["gps_lon"] = round(to_deg(gps[4], gps.get(3, "E")), 7)
            except Exception:
                pass
    except Exception:
        pass
    return out


def opencv_signals(path: Path) -> tuple[int, float, bool]:
    """face_count, laplacian_variance, is_screenshot."""
    try:
        # HEIC는 sips로 임시 JPG 만들어서 cv2 입력
        suffix = path.suffix.lower()
        if suffix in (".heic", ".heif"):
            tmp = Path("/tmp") / f"_cv_{os.getpid()}_{path.stem}.jpg"
            subprocess.run(["sips", "-s", "format", "jpeg", "-Z", "1024", str(path), "--out", str(tmp)],
                           capture_output=True, check=True, timeout=30)
            img = cv2.imread(str(tmp))
            tmp.unlink(missing_ok=True)
        else:
            img = cv2.imread(str(path))
        if img is None:
            return 0, 0.0, False

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        laplacian = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # 얼굴 감지 (Haar Cascade)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(60, 60))
        face_count = len(faces)

        # 스크린샷 휴리스틱: 종횡비가 폰 화면(예: 1170x2532) 비율 + 단색 박스
        h, w = img.shape[:2]
        ratio = h / w if w else 0
        is_screenshot = (ratio > 1.7 and ratio < 2.3) or (h > 2400 and w < 1300)

        return face_count, laplacian, is_screenshot
    except Exception:
        return 0, 0.0, False


# ─────────────────────────────────────────────
# 변환 (Layer 0.5)
# ─────────────────────────────────────────────
def convert_image(asset: Asset) -> Path:
    """HEIC → JPEG 변환. JPG/PNG 등은 그대로."""
    src = asset.source_path
    suffix = src.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return src  # 그대로 사용
    if suffix in (".heic", ".heif", ".png", ".webp", ".dng"):
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        out = WORK_DIR / f"{asset.asset_id}.jpg"
        subprocess.run(
            ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "95",
             str(src), "--out", str(out)],
            capture_output=True, check=True, timeout=60,
        )
        # EXIF 보존 시도
        subprocess.run(
            ["exiftool", "-overwrite_original", "-tagsFromFile", str(src),
             "-all:all", str(out)],
            capture_output=True, timeout=30,
        )
        return out
    return src


def convert_video(asset: Asset) -> Path:
    """영상 변환 X — 사용자 정책 (v3.10+, 효율 우선, 원본 보관).

    고용량 긴 영상의 변환은 시간·디스크 비효율. HEVC mov 호환성은 macOS·Immich 모두 지원.
    """
    return asset.source_path


def video_duration(path: Path) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            timeout=15,
        ).decode().strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0


# ─────────────────────────────────────────────
# 분류
# ─────────────────────────────────────────────
def classify_with_qwen(client: httpx.Client, img_b64: str) -> tuple[str, int, int]:
    start = time.time()
    r = client.post(OLLAMA_URL, json={
        "model": QWEN_MODEL, "system": PROMPT, "prompt": "이 사진의 등급?",
        "images": [img_b64], "stream": False, "format": "json",
        "options": {"num_ctx": 2048, "temperature": 0.0, "num_predict": 128},
        "keep_alive": "30m",
    }, timeout=90)
    elapsed = int((time.time() - start) * 1000)
    r.raise_for_status()
    payload = parse_json(r.json().get("response", "{}"))
    return str(payload.get("grade", "")).strip(), int(payload.get("confidence", 0)), elapsed


def classify_with_groq(groq: GroqClient, img_b64: str) -> tuple[str, int, int]:
    for attempt in range(3):
        try:
            r = groq.vision(system=PROMPT, user_text="등급?", image_b64=img_b64, max_tokens=150)
            payload = parse_json(r.text)
            return str(payload.get("grade", "")).strip(), int(payload.get("confidence", 0)), r.elapsed_ms
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < 2:
                time.sleep(15)
                continue
            return "", 0, 0
        except Exception:
            return "", 0, 0
    return "", 0, 0


def ensemble_decide(qg: str, qc: int, gg: str, gc: int) -> tuple[str, int, str]:
    """앙상블 가중 투표. (grade, confidence, source)"""
    if qg == gg and qg in LLM_GRADES:
        return qg, max(qc, gc), "llm_ensemble"
    if qg in LLM_GRADES and gg not in LLM_GRADES:
        return qg, qc, "llm_qwen"
    if gg in LLM_GRADES and qg not in LLM_GRADES:
        return gg, gc, "llm_groq"
    # 둘 다 LLM 등급: 가중 신뢰도
    if qc * 0.6 >= gc * 0.4:
        return qg if qg in LLM_GRADES else gg, qc, "llm_qwen"
    return gg if gg in LLM_GRADES else qg, gc, "llm_groq"


def auto_grade(asset: Asset, llm_grade: str) -> tuple[str, str]:
    """자동 4등급 (MEMORY+/-/NORMAL/EVENT-L) 결정.

    Returns: (final_grade, source).
    LLM 4등급이 결정이면 그대로 반환.
    """
    # 영상 길이 < 5초 → TRASH (의사결정 #35)
    if asset.is_video and 0 < asset.duration_seconds < 5.0:
        return "TRASH", "auto_short_video"

    if asset.is_screenshot:
        return "TRASH", "auto_screenshot"

    if llm_grade in LLM_GRADES:
        return llm_grade, "llm_ensemble"

    # LLM이 결정 못 한 경우 자동 분류
    if asset.face_count == 0:
        return "NORMAL", "auto_no_face"
    if asset.laplacian_variance < 100:
        return "MEMORY-", "auto_blurry"
    return "MEMORY+", "auto_quality_ok"


# ─────────────────────────────────────────────
# Immich-Storage 배치 (옵션 D)
# ─────────────────────────────────────────────
def move_to_storage(asset: Asset) -> Path:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    grade_dir = LIBRARY_DIR / asset.grade
    grade_dir.mkdir(parents=True, exist_ok=True)
    target = grade_dir / f"{asset.asset_id}.{asset.final_ext}"

    src = asset.converted_path or asset.source_path
    # 변환된 파일은 mv, 원본 그대로면 cp (백업 폴더 보존)
    if asset.converted_path and asset.converted_path != asset.source_path:
        src.rename(target)
    else:
        # 원본 보존 — copy
        import shutil
        shutil.copy2(src, target)
    return target


def add_view_link(target: Path, year_month: str, month_only: bool = True) -> None:
    """뷰 폴더 심볼릭 링크 (월별만 우선)."""
    view_dir = VIEWS_DIR / "월별" / year_month
    view_dir.mkdir(parents=True, exist_ok=True)
    link = view_dir / target.name
    if link.exists() or link.is_symlink():
        return
    link.symlink_to(target)


# ─────────────────────────────────────────────
# DB
# ─────────────────────────────────────────────
def save_to_db(conn, asset: Asset) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO photo.classification (
                asset_id, source_path, storage_path, sha256, file_size_bytes,
                is_video, grade, confidence, grade_source,
                qwen_grade, qwen_conf, qwen_ms,
                groq_grade, groq_conf, groq_ms,
                face_count, laplacian_variance, is_screenshot,
                width, height, duration_seconds,
                exif_datetime, gps_lat, gps_lon, camera_make, camera_model,
                model_version, classified_at, moved_at
            ) VALUES (
                %s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s, %s,%s,%s,
                %s,%s,%s, %s,%s,%s, %s,%s,%s,%s,%s, %s, NOW(), NOW()
            ) ON CONFLICT (asset_id) DO NOTHING
        """, (
            asset.asset_id, str(asset.source_path), str(asset.storage_path),
            asset.sha256, asset.file_size,
            asset.is_video, asset.grade, asset.confidence, asset.grade_source,
            asset.qwen_grade, asset.qwen_conf, asset.qwen_ms,
            asset.groq_grade, asset.groq_conf, asset.groq_ms,
            asset.face_count, asset.laplacian_variance, asset.is_screenshot,
            asset.width, asset.height, asset.duration_seconds,
            asset.exif_datetime, asset.gps_lat, asset.gps_lon,
            asset.camera_make, asset.camera_model,
            f"{QWEN_MODEL}+groq-llama-4-scout",
        ))


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
def collect_files() -> list[Path]:
    files: list[Path] = []
    exts = IMAGE_EXTS | VIDEO_EXTS
    for p in BACKUP_DIR.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            files.append(p)
    return sorted(files)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="처리 개수 제한 (시범용)")
    parser.add_argument("--dry-run", action="store_true", help="DB·이동 안 함, 분류만")
    parser.add_argument("--skip-converted", action="store_true", help="이미 변환된 자산 skip")
    parser.add_argument("--bulk-only", action="store_true",
                        help="폴더 일괄 매핑 자산만 처리 (LLM skip, 트레이딩 장중 안전)")
    parser.add_argument("--llm-only", action="store_true",
                        help="LLM 분류 필요한 자산만 처리 (장 마감 후 야간 배치용)")
    args = parser.parse_args()

    files = collect_files()

    # 폴더 기반 필터링 (macOS NFD ↔ NFC 정규화)
    import unicodedata
    def is_bulk(p: Path) -> bool:
        try:
            top = unicodedata.normalize("NFC", p.relative_to(BACKUP_DIR).parts[0])
        except ValueError:
            return False
        return top in FOLDER_GRADE_MAP

    if args.bulk_only:
        files = [f for f in files if is_bulk(f)]
        print(f"📦 bulk-only 모드: 폴더 일괄 매핑 자산만 ({len(files)}장, LLM skip)")
    elif args.llm_only:
        files = [f for f in files if not is_bulk(f)]
        print(f"🧠 llm-only 모드: LLM 분류 필요 자산만 ({len(files)}장)")

    if args.limit:
        files = files[:args.limit]

    print(f"📦 백업 폴더 마이그레이션")
    print(f"   원본: {BACKUP_DIR} ({len(files)}장)")
    print(f"   대상: {STORAGE_ROOT}")
    print(f"   dry-run: {args.dry_run}")
    print()

    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    groq = GroqClient()
    conn = None if args.dry_run else psycopg.connect(DB_DSN, autocommit=True)

    # 이미 처리된 source_path 조회 (재실행 시 중복 방지)
    processed_paths: set[str] = set()
    if conn:
        with conn.cursor() as cur:
            cur.execute("SELECT source_path FROM photo.classification")
            processed_paths = {row[0] for row in cur.fetchall()}
        print(f"📌 이미 처리된 자산: {len(processed_paths)}장 → skip")

    counts: dict[str, int] = {g: 0 for g in ALL_GRADES}
    counts["ERR"] = 0
    rate_sleep = 60.0 / 12  # Groq 12 RPM 보수적

    with httpx.Client() as oc:
        skipped = 0
        for i, src in enumerate(files, 1):
            if str(src) in processed_paths:
                skipped += 1
                continue
            asset = Asset(source_path=src)
            asset.asset_id = str(uuid.uuid4())
            asset.is_video = src.suffix.lower() in VIDEO_EXTS

            try:
                # A. 인벤토리
                asset.file_size = src.stat().st_size
                asset.sha256 = sha256_of(src)
                exif = extract_exif(src)
                asset.width = exif.get("width", 0)
                asset.height = exif.get("height", 0)
                asset.exif_datetime = exif.get("exif_datetime")
                asset.gps_lat = exif.get("gps_lat")
                asset.gps_lon = exif.get("gps_lon")
                asset.camera_make = exif.get("camera_make")
                asset.camera_model = exif.get("camera_model")

                # B. 변환
                if asset.is_video:
                    asset.duration_seconds = video_duration(src)
                    asset.converted_path = convert_video(asset) if not args.dry_run else src
                    asset.final_ext = "mp4"
                else:
                    asset.converted_path = convert_image(asset) if not args.dry_run else src
                    asset.final_ext = "jpg"

                # C. 분류
                # 폴더 기반 일괄 매핑 우선 (LLM skip, NFC 정규화)
                import unicodedata
                top_folder = unicodedata.normalize(
                    "NFC", src.relative_to(BACKUP_DIR).parts[0]
                ) if src.is_relative_to(BACKUP_DIR) else ""
                bulk_grade = FOLDER_GRADE_MAP.get(top_folder)

                if bulk_grade:
                    # 영상이고 5초 미만이면 TRASH 우선
                    if asset.is_video and 0 < asset.duration_seconds < 5.0:
                        asset.grade = "TRASH"
                        asset.grade_source = "auto_short_video"
                    else:
                        asset.grade = bulk_grade
                        asset.grade_source = f"folder_bulk:{top_folder}"
                    asset.confidence = 9
                elif not asset.is_video:
                    # LLM 분류 (일반 폴더)
                    img_b64 = load_image_b64(asset.converted_path or src)
                    asset.face_count, asset.laplacian_variance, asset.is_screenshot = opencv_signals(
                        asset.converted_path or src
                    )
                    try:
                        asset.qwen_grade, asset.qwen_conf, asset.qwen_ms = classify_with_qwen(oc, img_b64)
                    except Exception:
                        pass
                    try:
                        asset.groq_grade, asset.groq_conf, asset.groq_ms = classify_with_groq(groq, img_b64)
                    except Exception:
                        pass
                    llm_grade, llm_conf, source = ensemble_decide(
                        asset.qwen_grade, asset.qwen_conf,
                        asset.groq_grade, asset.groq_conf,
                    )
                    asset.grade, asset.grade_source = auto_grade(asset, llm_grade)
                    asset.confidence = llm_conf if asset.grade == llm_grade else 5
                else:
                    # 일반 폴더 영상: 길이 기반
                    if asset.duration_seconds < 5.0:
                        asset.grade = "TRASH"
                        asset.grade_source = "auto_short_video"
                    else:
                        asset.grade = "MEMORY+"
                        asset.grade_source = "auto_video_default"
                    asset.confidence = 5

                # D. DB 저장 + E. 이동
                if not args.dry_run:
                    asset.storage_path = move_to_storage(asset)
                    if asset.exif_datetime:
                        ym = asset.exif_datetime[:7].replace(":", "-")
                        try:
                            add_view_link(asset.storage_path, ym)
                        except Exception:
                            pass
                    save_to_db(conn, asset)

                counts[asset.grade] = counts.get(asset.grade, 0) + 1
                mark = "✓"
            except Exception as e:
                asset.error = str(e)[:200]
                counts["ERR"] += 1
                mark = "⚠"

            label = asset.grade if asset.grade else "ERR"
            err_short = f" ❌ {asset.error[:80]}" if asset.error else ""
            print(f"  [{i:4d}/{len(files)}] {mark} {label:8s} "
                  f"{src.parent.name}/{src.name[:50]}{err_short}", flush=True)

            # 폴더 일괄 매핑이면 sleep 불필요 (LLM 호출 X)
            if not asset.is_video and not bulk_grade:
                time.sleep(rate_sleep)

    # 통계
    print("\n" + "=" * 60)
    print(f"📊 마이그레이션 결과 (skip {skipped})")
    for g in ALL_GRADES + ["ERR"]:
        if counts.get(g, 0):
            print(f"  {g:10s}: {counts[g]}")

    if conn:
        conn.close()


if __name__ == "__main__":
    main()
