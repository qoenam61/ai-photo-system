"""사진 분류 서비스 — Vision 모델 체인 + 자동 4등급.

설계 §3 분류 책임 분리 (LLM 4등급, 자동 4등급).
**v3.13 (2026-05-03 사용자 명시)**: VISION_MODEL_CHAIN env 기반 동적 라우팅.
  - 기본: "groq,qwen" (Groq 우선, rate limit/실패 시 Qwen fallback)
  - "qwen" 단독: 로컬 전용 (v3.12 정책)
  - "groq" 단독: 외부 전용

Groq는 추가로 텍스트 작업 (§15: 앨범명, KPI 요약, NL 질의)에도 사용.

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
import httpx
import numpy as np
from PIL import Image, ExifTags

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

from core.client.groq_client import GroqClient, GroqRateLimitError
from core.client.qwen_client import QwenClient

logger = logging.getLogger(__name__)


PROMPT = """가족 사진 분류기. 4등급 中 정확히 하나 + 어린이 포함 여부:

판단 순서:
1. UI 스크린샷/완전 흑백/심한 흔들림 → TRASH
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


def opencv_signals(path: Path) -> Signals:
    """OpenCV 기반 face_count, laplacian_variance, is_screenshot."""
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
        is_screenshot = (ratio > 1.7 and ratio < 2.3) or (h > 2400 and w < 1300)

        return Signals(
            face_count=face_count,
            laplacian_variance=laplacian,
            is_screenshot=is_screenshot,
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
    if signals.is_video and 0 < signals.duration_seconds < 3.0:
        return "TRASH", "auto_short_video"
    if signals.is_screenshot:
        return "TRASH", "auto_screenshot"
    if llm_grade in LLM_GRADES:
        return llm_grade, "llm_ensemble"
    if signals.face_count == 0:
        return "NORMAL", "auto_no_face"
    if signals.laplacian_variance < 100:
        return "MEMORY-", "auto_blurry"
    return "MEMORY+", "auto_quality_ok"


class Classifier:
    """v3.13: VISION_MODEL_CHAIN env로 동적 라우팅 (groq/qwen, fallback 자동).

    환경변수:
      VISION_MODEL_CHAIN  콤마 리스트, 좌→우 우선순위 (기본 "groq,qwen")
      GROQ_API_KEY        없으면 groq 자동 스킵
    """

    def __init__(
        self,
        qwen: QwenClient | None = None,
        groq: GroqClient | None = None,
        chain: str | None = None,
    ) -> None:
        self._qwen = qwen or QwenClient()
        self._groq = groq if groq is not None else (
            GroqClient() if os.getenv("GROQ_API_KEY") else None
        )
        chain_str = chain or os.getenv("VISION_MODEL_CHAIN", "groq,qwen")
        self._chain = [m.strip().lower() for m in chain_str.split(",") if m.strip()]
        self._throttled_until: dict[str, float] = {}

    def _vision_call(
        self, model: str, img_b64: str
    ) -> tuple[str, int, int, bool] | None:
        """단일 모델 호출. 성공 시 (grade, conf, ms, contains_child), 실패 시 None."""
        if model == "groq":
            if not self._groq:
                return None
            try:
                r = self._groq.vision(PROMPT, "이 사진의 등급?", img_b64)
                return r.grade, r.confidence, r.elapsed_ms, r.contains_child
            except GroqRateLimitError as e:
                wait = min(e.retry_after, 120)
                self._throttled_until["groq"] = time.time() + wait
                logger.warning(
                    "groq rate limited, capped fallback %ds (retry-after=%ds)",
                    wait, e.retry_after,
                )
                return None
            except (httpx.HTTPError, ValueError) as e:
                logger.warning("groq vision failed: %s", e)
                return None
        if model == "qwen":
            try:
                r = self._qwen.vision(PROMPT, "이 사진의 등급?", img_b64)
                return r.grade, r.confidence, r.elapsed_ms, r.contains_child
            except (httpx.HTTPError, ValueError) as e:
                logger.warning("qwen vision failed: %s", e)
                return None
        return None

    def classify_image(self, path: Path, signals: Signals | None = None) -> Decision:
        sig = signals or opencv_signals(path)
        img_b64 = encode_image(path)

        used_model = ""
        grade, conf, ms, contains_child = "", 0, 0, False
        for model in self._chain:
            if self._throttled_until.get(model, 0) > time.time():
                continue
            result = self._vision_call(model, img_b64)
            if result and result[0] in LLM_GRADES:
                grade, conf, ms, contains_child = result
                used_model = model
                break

        final, final_src = _auto_grade(grade, sig)
        if final_src == "llm_ensemble":
            final_src = f"llm_{used_model}" if used_model else "llm_unknown"

        qwen_grade = grade if used_model == "qwen" else ""
        qwen_conf = conf if used_model == "qwen" else 0
        qwen_ms = ms if used_model == "qwen" else 0
        groq_grade = grade if used_model == "groq" else ""
        groq_conf = conf if used_model == "groq" else 0
        groq_ms = ms if used_model == "groq" else 0

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
