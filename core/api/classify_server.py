"""Classify Service — n8n에서 호출되는 HTTP 분류 엔드포인트.

POST /classify
  body: {"immich_id": "...", "path": "/storage/.../UUID.jpg"}
  resp: {"grade": "EVENT", "confidence": 9, "source": "llm_ensemble",
         "qwen_grade": "EVENT", "qwen_conf": 9, "qwen_ms": 1234,
         "groq_grade": "EVENT", "groq_conf": 8, "groq_ms": 567}

POST /classify_and_persist
  body: {"immich_id": "...", "path": "..."}
  → /classify + DB INSERT photo.classification

GET /health → {"ok": true, "qwen": "...", "groq": bool}

배포: Docker container, trading_net, 8000 노출
환경변수:
  OLLAMA_URL          (기본 http://host.docker.internal:11434/api/generate)
  GROQ_API_KEY        (없으면 Qwen 단독)
  PHOTO_DB_DSN        (Postgres DSN)
  STORAGE_PREFIX      (호스트 경로 → 컨테이너 경로 매핑, 예: /Volumes/Immich-Storage→/storage)
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("photo-classify")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

from core.client.qwen_client import QwenClient
from core.service.backup_verifier import verify_asset
from core.service.classifier import Classifier, Decision


app = FastAPI(title="photo-classify-service", version="0.1.0")

DB_DSN = os.getenv(
    "PHOTO_DB_DSN",
    "host=trading_postgres port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)
# Immich originalPath → classify 컨테이너 내부 경로 매핑.
# Immich 컨테이너는 /Volumes/Immich-Storage/immich-media:/mnt/external 마운트.
# Classify 컨테이너는 /Volumes/Immich-Storage:/storage 마운트.
PATH_MAPPINGS = [
    ("/mnt/external", "/storage/immich-media"),       # Immich External Library
    ("/usr/src/app/upload", "/storage/immich-uploads"),  # iPhone 업로드
    ("/Volumes/Immich-Storage", "/storage"),          # 호스트 직접 경로
]


def _resolve_path(p: str) -> Path:
    """Immich 경로 → classify 컨테이너 내부 경로."""
    for src, dst in PATH_MAPPINGS:
        if p.startswith(src):
            return Path(dst + p[len(src):])
    return Path(p)


_classifier: Classifier | None = None


def _get_classifier() -> Classifier:
    global _classifier
    if _classifier is None:
        # v3.12: Qwen 단독 (사진 외부 전송 금지)
        _classifier = Classifier(qwen=QwenClient())
    return _classifier


class ClassifyRequest(BaseModel):
    immich_id: str
    path: str
    asset_id: str | None = None  # 명시 시 우선; 미명시면 path.stem 또는 immich_id로 결정


class ClassifyResponse(BaseModel):
    grade: str
    confidence: int
    source: str
    qwen_grade: str = ""
    qwen_conf: int = 0
    qwen_ms: int = 0
    groq_grade: str = ""
    groq_conf: int = 0
    groq_ms: int = 0
    contains_child: bool = False


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "qwen_url": os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate"),
        "groq_enabled": bool(os.getenv("GROQ_API_KEY")),
        "vision_model_chain": os.getenv("VISION_MODEL_CHAIN", "groq,qwen"),
        "groq_vision_model": os.getenv(
            "GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"
        ),
        "policy": "v3.13 VISION_MODEL_CHAIN dynamic routing",
        "path_mappings": PATH_MAPPINGS,
    }


@app.post("/classify", response_model=ClassifyResponse)
def classify(req: ClassifyRequest) -> ClassifyResponse:
    p = _resolve_path(req.path)
    if not p.exists():
        raise HTTPException(404, f"path not found: {p}")

    is_video = p.suffix.lower() in (".mov", ".mp4", ".m4v", ".webm")
    cls = _get_classifier()
    d: Decision = cls.classify_video(p) if is_video else cls.classify_image(p)
    return ClassifyResponse(
        grade=d.grade, confidence=d.confidence, source=d.source,
        qwen_grade=d.qwen_grade, qwen_conf=d.qwen_conf, qwen_ms=d.qwen_ms,
        groq_grade=d.groq_grade, groq_conf=d.groq_conf, groq_ms=d.groq_ms,
        contains_child=d.contains_child,
    )


IMMICH_DB_DSN = os.getenv(
    "IMMICH_DB_DSN",
    "host=immich-postgres port=5432 dbname=immich "
    "user=postgres password=immich_pg_2026",
)
IMMICH_API_URL = os.getenv("IMMICH_API_URL", "http://immich-server:2283")
IMMICH_API_KEY = os.getenv("IMMICH_API_KEY", "")

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


def _fetch_pending(limit: int) -> list[tuple[str, str]]:
    """Immich asset 中 classification 미존재. (immich_id, originalPath). IMAGE+VIDEO."""
    with psycopg.connect(IMMICH_DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id::text, "originalPath" FROM asset
            WHERE "deletedAt" IS NULL AND type IN ('IMAGE', 'VIDEO')
              AND "originalPath" NOT LIKE '%/encoded-video/%'
              AND "originalPath" NOT LIKE '%/thumbs/%'
        """)
        immich_rows = cur.fetchall()

    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT asset_id::text FROM photo.classification")
        classified = {r[0] for r in cur.fetchall()}

    out = []
    for iid, path in immich_rows:
        stem = Path(path).stem
        if iid in classified or stem in classified:
            continue
        out.append((iid, path))
        if len(out) >= limit:
            break
    return out


def _add_to_album(client: httpx.Client, album_id: str, immich_id: str) -> bool:
    headers = {"x-api-key": IMMICH_API_KEY}
    r = client.put(
        f"{IMMICH_API_URL}/api/albums/{album_id}/assets",
        json={"ids": [immich_id]}, headers=headers, timeout=20,
    )
    return r.status_code == 200


def _get_or_create_album(
    client: httpx.Client, name: str, cache: dict[str, str]
) -> str:
    if name in cache:
        return cache[name]
    headers = {"x-api-key": IMMICH_API_KEY, "Accept": "application/json"}
    r = client.get(f"{IMMICH_API_URL}/api/albums", headers=headers, timeout=20)
    for alb in r.json():
        if alb["albumName"] == name:
            cache[name] = alb["id"]
            return alb["id"]
    r = client.post(
        f"{IMMICH_API_URL}/api/albums",
        json={"albumName": name, "assetIds": []},
        headers=headers, timeout=20,
    )
    aid = r.json()["id"]
    cache[name] = aid
    return aid


class ProcessPendingResponse(BaseModel):
    pending: int
    processed: int
    success: int
    failed: int
    by_grade: dict[str, int]


@app.post("/process_pending", response_model=ProcessPendingResponse)
def process_pending(limit: int = 20) -> ProcessPendingResponse:
    """신규 Immich 자산 자동 분류 + Album 추가. n8n cron 진입점."""
    import httpx as _httpx

    pending = _fetch_pending(limit)
    if not pending:
        return ProcessPendingResponse(
            pending=0, processed=0, success=0, failed=0, by_grade={},
        )

    success = failed = 0
    by_grade: dict[str, int] = {}
    cache: dict[str, str] = {}
    immich = _httpx.Client()
    try:
        for iid, path in pending:
            try:
                resp = classify_and_persist(
                    ClassifyRequest(immich_id=iid, path=path)
                )
                album_name = GRADE_ALBUMS.get(resp.grade)
                if album_name and IMMICH_API_KEY:
                    aid = _get_or_create_album(immich, album_name, cache)
                    _add_to_album(immich, aid, iid)
                by_grade[resp.grade] = by_grade.get(resp.grade, 0) + 1
                success += 1
            except Exception as e:
                failed += 1
                logger.exception(
                    "classify failed immich_id=%s path=%s err=%s",
                    iid, path, e,
                )
    finally:
        immich.close()

    return ProcessPendingResponse(
        pending=len(pending), processed=success + failed,
        success=success, failed=failed, by_grade=by_grade,
    )


# ─────────────────────────────────────────────
# 백업 검증 + Layer 6 cleanup 엔드포인트 (도메인 안전)
# ─────────────────────────────────────────────


class VerifyRequest(BaseModel):
    asset_id: str


class VerifyResponse(BaseModel):
    asset_id: str
    verified: bool
    reason: str
    expected_sha: str = ""
    actual_sha: str = ""
    expected_size: int = 0
    actual_size: int = 0
    immich_id: str = ""
    immich_path: str = ""


@app.post("/verify_backup", response_model=VerifyResponse)
def verify_backup(req: VerifyRequest) -> VerifyResponse:
    """Phase 5 + Layer 6 삭제 전 게이트. SHA256 + 파일 + Immich 3중 검증."""
    r = verify_asset(req.asset_id)
    return VerifyResponse(
        asset_id=r.asset_id, verified=r.verified, reason=r.reason,
        expected_sha=r.expected_sha, actual_sha=r.actual_sha,
        expected_size=r.expected_size, actual_size=r.actual_size,
        immich_id=r.immich_id, immich_path=r.immich_path,
    )


class CleanupCandidate(BaseModel):
    asset_id: str
    immich_id: str
    immich_path: str
    grade: str
    sha256: str
    file_size_bytes: int
    classified_at: str


class CleanupCandidatesResponse(BaseModel):
    grades: list[str]
    min_age_days: int
    total_candidates: int
    verified_safe: int
    failed_verification: int
    excluded_protected: int
    items: list[CleanupCandidate]


def _phase5_progressive_limit(default_limit: int) -> int:
    """Phase 5 단계적 활성화: 1주차 20장 / 2주차 100장 / 3주차+ 200장.

    트리거: scripts/_inventory/phase5_ready.flag 파일의 ctime 기준 경과 주차.
    플래그 없으면 0 반환 (실삭제 사실상 차단).
    """
    from pathlib import Path
    flag = Path("/app/scripts/_inventory/phase5_ready.flag")
    if not flag.exists():
        # 컨테이너 내부 마운트 X — host 경로 시뮬레이션 차단 정책
        return 0
    elapsed_days = (
        time.time() - flag.stat().st_ctime
    ) / 86400 if hasattr(flag.stat(), "st_ctime") else 0
    if elapsed_days < 7:
        return min(20, default_limit)
    if elapsed_days < 14:
        return min(100, default_limit)
    return default_limit


@app.get("/cleanup_candidates", response_model=CleanupCandidatesResponse)
def cleanup_candidates(
    grades: str = "NORMAL,TRASH,FOOD",
    min_age_days: int = 14,
    limit: int = 200,
    progressive: bool = True,
) -> CleanupCandidatesResponse:
    """Layer 6 디바이스 정리용 — 검증 PASS 자산만 반환.

    조건:
      1. grade ∈ {grades}
      2. classified_at + min_age_days < NOW() (등급 안정화 대기)
      3. photo.feedback에 'protect' 표시 없음
      4. backup_verifier.verify_asset() == True
      5. progressive=True 시 phase5_ready.flag 기반 단계적 limit 적용
    """
    grade_list = [g.strip() for g in grades.split(",") if g.strip()]
    if progressive:
        eff_limit = _phase5_progressive_limit(limit)
        if eff_limit == 0:
            # phase5_ready.flag 없음 → cleanup 사실상 차단
            return CleanupCandidatesResponse(
                grades=grade_list, min_age_days=min_age_days,
                total_candidates=0, verified_safe=0,
                failed_verification=0, excluded_protected=0, items=[],
            )
        limit = eff_limit

    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT c.asset_id::text, c.sha256, c.file_size_bytes, c.grade,
                   c.classified_at::text,
                   EXISTS(
                     SELECT 1 FROM photo.feedback f
                     WHERE f.asset_id = c.asset_id AND f.feedback_type = 'protect'
                   ) AS is_protected
            FROM photo.classification c
            WHERE c.grade = ANY(%s)
              AND c.classified_at < NOW() - (%s || ' days')::interval
            ORDER BY c.classified_at ASC
            LIMIT %s
        """, (grade_list, str(min_age_days), limit))
        candidates = cur.fetchall()

    items: list[CleanupCandidate] = []
    failed = 0
    protected = 0
    for asset_id, sha, size, grade, classified_at, is_protected in candidates:
        if is_protected:
            protected += 1
            continue
        v = verify_asset(asset_id)
        if not v.verified:
            failed += 1
            continue
        items.append(CleanupCandidate(
            asset_id=asset_id,
            immich_id=v.immich_id,
            immich_path=v.immich_path,
            grade=grade,
            sha256=sha,
            file_size_bytes=size or 0,
            classified_at=classified_at,
        ))

    return CleanupCandidatesResponse(
        grades=grade_list,
        min_age_days=min_age_days,
        total_candidates=len(candidates),
        verified_safe=len(items),
        failed_verification=failed,
        excluded_protected=protected,
        items=items,
    )


# ─────────────────────────────────────────────
# 사용자 보호 표시 (Phase 5 안전 게이트)
# ─────────────────────────────────────────────


class ProtectRequest(BaseModel):
    asset_id: str
    note: str | None = None


class ProtectResponse(BaseModel):
    asset_id: str
    protected: bool
    protected_at: str | None = None


class CleanupResultRequest(BaseModel):
    asset_id: str
    immich_id: str | None = None
    device: str  # "iphone-jw" | "galaxy-eunju" 등
    success: bool
    reason: str | None = None
    reclaimed_bytes: int | None = None
    device_deleted_at: str  # ISO 8601


class CleanupResultResponse(BaseModel):
    audit_id: int
    asset_id: str
    success: bool
    recorded_at: str


@app.post("/cleanup_result", response_model=CleanupResultResponse)
def cleanup_result(req: CleanupResultRequest) -> CleanupResultResponse:
    """Layer 6 디바이스 정리 결과 회신 — 감사 추적용.

    iOS Shortcut / MacroDroid가 디바이스 사진 삭제 후 호출.
    photo.cleanup_audit에 기록 + 실패 시 통계 누적.
    """
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO photo.cleanup_audit
              (asset_id, immich_id, device, success, reason,
               reclaimed_bytes, device_deleted_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s::timestamptz)
            RETURNING id, reported_at::text
        """, (
            req.asset_id, req.immich_id, req.device, req.success,
            req.reason, req.reclaimed_bytes, req.device_deleted_at,
        ))
        audit_id, reported_at = cur.fetchone()

    return CleanupResultResponse(
        audit_id=audit_id, asset_id=req.asset_id,
        success=req.success, recorded_at=reported_at,
    )


@app.get("/cleanup_audit")
def cleanup_audit_summary(days: int = 7) -> dict:
    """최근 N일 cleanup 결과 통계."""
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT device,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE success) AS success,
                   COUNT(*) FILTER (WHERE NOT success) AS failed,
                   COALESCE(SUM(reclaimed_bytes) FILTER (WHERE success), 0) AS reclaimed
            FROM photo.cleanup_audit
            WHERE reported_at > NOW() - (%s || ' days')::interval
            GROUP BY device
            ORDER BY device
        """, (str(days),))
        rows = cur.fetchall()

    return {
        "days": days,
        "by_device": [
            {
                "device": d, "total": t, "success": s, "failed": f,
                "reclaimed_mb": round(rb / 1024 / 1024, 1),
            }
            for d, t, s, f, rb in rows
        ],
    }


class NLQueryRequest(BaseModel):
    question: str


class NLQueryResponse(BaseModel):
    intent: str
    answer: str
    data: dict


@app.post("/nl_query", response_model=NLQueryResponse)
def nl_query(req: NLQueryRequest) -> NLQueryResponse:
    """자연어 질의 → Groq 인텐트 파싱 + 답변. 사진 데이터 X."""
    from core.service.nl_query import answer_question
    r = answer_question(req.question)
    return NLQueryResponse(intent=r.intent, answer=r.answer, data=r.data)


@app.post("/feedback/protect", response_model=ProtectResponse)
def protect_asset(req: ProtectRequest) -> ProtectResponse:
    """asset 보호 표시 — cleanup_candidates에서 영구 제외."""
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        # asset_id 존재 확인
        cur.execute(
            "SELECT 1 FROM photo.classification WHERE asset_id = %s", (req.asset_id,)
        )
        if not cur.fetchone():
            raise HTTPException(404, f"asset_id {req.asset_id} not in classification")

        # idempotent — 이미 protect면 created_at만 갱신
        cur.execute("""
            INSERT INTO photo.feedback (asset_id, feedback_type, created_at)
            VALUES (%s, 'protect', NOW())
            RETURNING created_at::text
        """, (req.asset_id,))
        ts = cur.fetchone()[0]
    return ProtectResponse(asset_id=req.asset_id, protected=True, protected_at=ts)


@app.delete("/feedback/protect/{asset_id}", response_model=ProtectResponse)
def unprotect_asset(asset_id: str) -> ProtectResponse:
    """보호 해제."""
    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            DELETE FROM photo.feedback
            WHERE asset_id = %s AND feedback_type = 'protect'
        """, (asset_id,))
        deleted = cur.rowcount
    return ProtectResponse(
        asset_id=asset_id, protected=False,
        protected_at=None if deleted else "not_protected",
    )


@app.get("/feedback/protect")
def list_protected(limit: int = 200) -> dict:
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (f.asset_id)
                   f.asset_id::text, f.created_at::text, c.grade
            FROM photo.feedback f
            JOIN photo.classification c ON f.asset_id = c.asset_id
            WHERE f.feedback_type = 'protect'
            ORDER BY f.asset_id, f.created_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
    return {
        "count": len(rows),
        "items": [
            {"asset_id": aid, "protected_at": ts, "grade": g}
            for aid, ts, g in rows
        ],
    }


@app.post("/classify_and_persist", response_model=ClassifyResponse)
def classify_and_persist(req: ClassifyRequest) -> ClassifyResponse:
    resp = classify(req)
    p = _resolve_path(req.path)

    # asset_id 결정:
    #   요청 명시 > path.stem (UUID 형식) > immich_id
    asset_id = req.asset_id or p.stem
    # UUID 형식 검증
    import re
    if not re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", asset_id):
        asset_id = req.immich_id

    import hashlib
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    sha = h.hexdigest()
    file_size = p.stat().st_size

    with psycopg.connect(DB_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO photo.classification
              (asset_id, source_path, sha256, file_size_bytes, grade, grade_source,
               qwen_grade, qwen_conf, qwen_ms,
               groq_grade, groq_conf, groq_ms,
               contains_child, classified_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (asset_id) DO UPDATE SET
              grade = EXCLUDED.grade,
              grade_source = EXCLUDED.grade_source,
              qwen_grade = EXCLUDED.qwen_grade,
              qwen_conf = EXCLUDED.qwen_conf,
              groq_grade = EXCLUDED.groq_grade,
              groq_conf = EXCLUDED.groq_conf,
              contains_child = EXCLUDED.contains_child,
              updated_at = NOW()
        """, (
            asset_id, req.path, sha, file_size, resp.grade, resp.source,
            resp.qwen_grade, resp.qwen_conf, resp.qwen_ms,
            resp.groq_grade, resp.groq_conf, resp.groq_ms,
            resp.contains_child,
        ))
    return resp
