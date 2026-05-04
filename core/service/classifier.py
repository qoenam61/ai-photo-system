"""사진 분류 서비스 — LiteLLM 게이트웨이 + 자동 4등급.

설계 §3 분류 책임 분리 (LLM 4등급, 자동 4등급).
**v3.14 (2026-05-04)**: LiteLLM 게이트웨이 통합.
  - photo/classify → Qwen VL 7B (로컬, 우선)
  - photo/classify-fb → Groq Llama-4-Scout (fallback, LiteLLM 내장)
  - 체인/스로틀 관리는 LiteLLM이 담당

Inputs:
  Path → 이미지 파일 경로
  Asset signals → face_count, laplacian, is_screenshot, is_video, duration

Outputs:
  Decision(grade, confidence, source, qwen_*, groq_*)
"""

from __future__ import annotations

import base64
import io
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ExifTags

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

from core.client.llm_gateway import vision_classify, LLMGatewayError

logger = logging.getLogger(__name__)


PROMPT = """가족 사진 분류기. 4등급 中 정확히 하나 + 어린이 포함 여부:

[TRASH 정의] (사용자 명시 2026-05-04 — 의미 없는 사진)
  - UI 스크린샷, 완전 흑백/단색 화면
  - 초점이 완전히 나간 사진 (피사체 식별 불가)
  - 바닥·벽·천장만 찍힌 사진 (피사체 없음)
  - 잘못 촬영된 사진 (손가락 가림, 흔들림 심함, 노출 완전 실패)
  - 매우 짧거나 잘못 찍힌 영상
  ※ 단순 흐림(약간 초점 안 맞음)은 TRASH 아님 → BEST 또는 EVENT

판단 순서:
1. 위 TRASH 정의에 해당 → TRASH
2. 음식이 화면 50%+ → FOOD
3. 사람 3+ OR (케이크·꽃다발·드레스·한복·웨딩·돌잔치·생일·졸업·기념일·가족스튜디오·신생아·만삭·100일·돌·칠순) → EVENT
4. 그 외 (인물 사진이거나 풍경/사물 等) → BEST

contains_child: 만 18세 미만 어린이(영유아·아동·청소년) 1명 이상 보이면 true, 아니면 false.
어른만 있거나 사물·풍경뿐이면 false.

JSON만 출력:
{"grade":"<EVENT|BEST|FOOD|TRASH>","confidence":<1-10>,"reason":"<짧게>","contains_child":<true|false>}"""

LLM_GRADES = {"EVENT", "BEST", "FOOD", "TRASH"}


@dataclass(slots=True)
class Signals:
    face_count: int = 0
    laplacian_variance: float = 0.0
    is_screenshot: bool = False
    is_video: bool = False
    duration_seconds: float = 0.0
    camera_make: str = ""


@dataclass(slots=True)
class Decision:
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


def encode_image(path: Path, max_dim: int = 512) -> str:
    """이미지 → base64 JPEG (LLM 입력용). HEIC는 pillow-heif 자동 처리.

    v3.13: max_dim 512 (이전 1024) — Groq TPM 한도 4배 절감, 분류 품질 영향 미미.
    명시적 close + buf.close()로 메모리 누수 방지.
    """
    with Image.open(path) as raw:
        img = raw.convert("RGB")
        img.thumbnail((max_dim, max_dim))
        with io.BytesIO() as buf:
            img.save(buf, format="JPEG", quality=80)
            data = buf.getvalue()
        img.close()
    return base64.b64encode(data).decode()


def exif_camera_make(path: Path) -> str:
    """EXIF Make 태그 추출. 카메라 사진 판별용."""
    try:
        with Image.open(path) as pil:
            exif = pil.getexif()
            return str(exif.get(271, "") or "").strip()
    except Exception:
        return ""


def opencv_signals(path: Path) -> Signals:
    """OpenCV 기반 face_count, laplacian_variance, is_screenshot.

    is_screenshot 강화 (사용자 명시 2026-05-04):
      - face_count > 0 → 절대 스크린샷 아님 (사람 사진)
      - EXIF camera_make 있음 → 절대 스크린샷 아님 (카메라 사진)
      - 그 외에만 종횡비/해상도 휴리스틱
    """
    try:
        suffix = path.suffix.lower()
        if suffix in (".heic", ".heif"):
            with Image.open(path) as raw:
                pil_img = raw.convert("RGB")
                arr = np.array(pil_img)
                pil_img.close()
            img = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            del arr
        else:
            img = cv2.imread(str(path))
        if img is None:
            return Signals()

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        laplacian = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(60, 60))
        face_count = len(faces)

        h, w = img.shape[:2]
        ratio = h / w if w else 0

        camera = exif_camera_make(path)
        if face_count > 0 or camera:
            is_screenshot = False
        else:
            is_screenshot = (ratio > 1.7 and ratio < 2.3) or (h > 2400 and w < 1300)

        return Signals(
            face_count=face_count,
            laplacian_variance=laplacian,
            is_screenshot=is_screenshot,
            camera_make=camera,
        )
    except Exception:
        return Signals()


def video_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return float(r.stdout.strip() or 0)
    except Exception:
        return 0.0


def _ensemble(qg: str, qc: int, gg: str, gc: int) -> tuple[str, int, str]:
    if qg == gg and qg in LLM_GRADES:
        return qg, max(qc, gc), "llm_ensemble"
    if qg in LLM_GRADES and gg not in LLM_GRADES:
        return qg, qc, "llm_qwen"
    if gg in LLM_GRADES and qg not in LLM_GRADES:
        return gg, gc, "llm_groq"
    if qc * 0.6 >= gc * 0.4:
        return qg if qg in LLM_GRADES else gg, qc, "llm_qwen"
    return gg if gg in LLM_GRADES else qg, gc, "llm_groq"


def _auto_grade(llm_grade: str, signals: Signals) -> tuple[str, str]:
    """자동 등급 결정 (CLAUDE.md "자동 분류 룰" 결정 트리 구현).

    우선순위:
      1. 영상 길이 (< 3초 TRASH / >= 3초 EVENT-L)
      2. is_screenshot (UI 스크린샷)
      3. LLM 응답 (있으면 그대로 — BEST/EVENT/FOOD/TRASH)
      4. Auto 신호 fallback (face / camera_make / laplacian)
    """
    if signals.is_video and 0 < signals.duration_seconds < 3.0:
        return "TRASH", "auto_short_video"
    if signals.is_video and signals.duration_seconds >= 3.0:
        return "EVENT-L", "auto_video"
    if signals.is_screenshot:
        return "TRASH", "auto_screenshot"
    if llm_grade in LLM_GRADES:
        return llm_grade, "llm_ensemble"

    # LLM 미응답 → auto 신호 fallback
    if signals.face_count > 0:
        if signals.laplacian_variance < 100:
            return "MEMORY-", "auto_blurry"
        return "MEMORY+", "auto_quality_ok"
    # 사람 없음
    if signals.camera_make:
        return "NORMAL", "auto_no_face"
    # 사람 없음 + 카메라 메타 없음 = 의미 없는 사진 가능성
    return "TRASH", "auto_screenshot"


class Classifier:
    """v3.14: LiteLLM 게이트웨이 통합 (photo/classify → photo/classify-fb).

    체인/스로틀 관리는 LiteLLM이 담당.
    Decision.qwen_* / groq_* 필드는 실제 사용 모델로 채워진다.
    """

    def __init__(self, **_kwargs) -> None:
        # 구버전 QwenClient/GroqClient 파라미터 무시 (호환성)
        pass

    def classify_image(self, path: Path, signals: Signals | None = None) -> Decision:
        sig = signals or opencv_signals(path)
        img_b64 = encode_image(path)

        grade, conf, ms, contains_child = "", 0, 0, False
        used_model = ""

        try:
            r = vision_classify(PROMPT, "이 사진의 등급?", img_b64)
            if r.grade in LLM_GRADES:
                grade, conf, ms, contains_child = r.grade, r.confidence, r.elapsed_ms, r.contains_child
                # raw에 model 힌트가 없으면 'qwen' 기본 (primary = Qwen VL)
                used_model = r.raw.get("_model", "qwen")
                if "groq" in used_model or "llama" in used_model:
                    used_model = "groq"
                else:
                    used_model = "qwen"
        except LLMGatewayError as e:
            logger.warning("vision_classify 완전 실패: %s", e)

        final, final_src = _auto_grade(grade, sig)
        if final_src == "llm_ensemble":
            final_src = f"llm_{used_model}" if used_model else "llm_unknown"

        qwen_grade = grade if used_model == "qwen" else ""
        qwen_conf  = conf  if used_model == "qwen" else 0
        qwen_ms    = ms    if used_model == "qwen" else 0
        groq_grade = grade if used_model == "groq" else ""
        groq_conf  = conf  if used_model == "groq" else 0
        groq_ms    = ms    if used_model == "groq" else 0

        return Decision(
            grade=final,
            confidence=conf if used_model else 10,
            source=final_src,
            qwen_grade=qwen_grade, qwen_conf=qwen_conf, qwen_ms=qwen_ms,
            groq_grade=groq_grade, groq_conf=groq_conf, groq_ms=groq_ms,
            contains_child=contains_child,
        )

    def classify_video(self, path: Path) -> Decision:
        dur = video_duration(path)
        sig = Signals(is_video=True, duration_seconds=dur)
        if 0 < dur < 3.0:
            return Decision(grade="TRASH", confidence=10, source="auto_short_video")
        return Decision(grade="EVENT-L", confidence=8, source="auto_video")
