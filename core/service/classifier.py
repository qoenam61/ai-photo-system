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


PROMPT = """가족 사진 4등급 분류기 + 어린이 포함 판정. 결과는 JSON만 출력.

═══════════════════════════════════════════════════════════════════
판단 순서 (위에서 아래로, 첫 매칭 사용)
═══════════════════════════════════════════════════════════════════

[1단계] TRASH 검사 (다음 中 하나라도 해당 → TRASH)

  (A) 의미 없는 사진:
      · UI 스크린샷 (메신저/웹/앱 캡처, "광고" 텍스트 가득)
      · 완전 흑백/단색 화면, 검은/흰 빈 화면
      · 초점 완전 나감 — 피사체 식별 자체 불가능
      · 바닥/벽/천장만 (찍히는 의도 없는 우연 촬영)
      · 손가락 가림으로 피사체 안 보임
      · 노출 완전 실패 (전체가 새카맣거나 새하얗다)
      · 영상 < 3초 (짧은 우연 촬영)

  (B) 사람이 있지만 얼굴이 안 보이는 사진 — **사용자 명시 핵심 룰**:
      · 다리만/발만/손만 보이는 부분 신체
      · 뒷모습만 (얼굴 측면도 식별 불가)
      · 얼굴이 잘리거나 가려져 인물 식별 불가
      · 멀리 있어 얼굴이 픽셀 단위로 작음
      → **결혼식·돌잔치·생일 등 행사 컨텍스트여도 얼굴 미가시 → TRASH**
      → 행사 분위기 그 자체로는 보존 가치 X, 사람 식별이 핵심

  [TRASH 아닌 경우 — 보존선]
      ⊘ 약간 흐림 (초점이 살짝 안 맞음) → TRASH 아님 → BEST/EVENT 또는 흐림 등급 보존
      ⊘ 의도적 흑백 필터 + 인물 명확 → TRASH 아님 → BEST 가능
      ⊘ 의도적 보케·아웃포커스 + 피사체 명확 → BEST 가능

[2단계] FOOD 검사

  음식이 화면 50% 이상 차지 → FOOD
  단, 음식 + 사람 얼굴 명확이 큰 비중이면 → 인물 우선 (EVENT/BEST/MEMORY+)

[3단계] EVENT 검사 (얼굴 가시성 필수 — 이게 핵심)

  다음 중 하나에 해당하면 EVENT:
    (A) 얼굴 명확히 보이는 사람 3명 이상 (단체 사진)
    (B) 얼굴 명확히 보이는 사람 1+ AND 행사 키워드 명백:
        · 결혼·웨딩: 드레스, 턱시도, 한복, 신부 부케, 웨딩 케이크, 웨딩홀
        · 돌잔치: 돌상, 돌띠, 돌잡이 도구
        · 생일: 생일 케이크, 고깔모자, "HAPPY BIRTHDAY", 풍선 장식
        · 가족 행사: 가족스튜디오, 명절 한복, 가족 단체
        · 기념일: 100일, 돌, 만삭, 신생아, 칠순, 졸업장, 학사모
        · 제사·차례상

  ※ 행사 분위기지만 얼굴 가시성 X → TRASH (1단계로 회귀)
  ※ 사람 1-2명 + 행사 키워드 X → BEST 또는 인물 BEST

[4단계] BEST (위 단계 모두 해당 X)

  · 얼굴 명확한 인물 사진 (1-2명, 행사 X)
  · 풍경·여행지·도시 풍경
  · 사물 클로즈업 (꽃·작품·기념품 등)
  · 동물 (반려동물·야생)
  · 의도적 흑백/보케 필터 + 식별 가능

═══════════════════════════════════════════════════════════════════
경계 케이스 가이드
═══════════════════════════════════════════════════════════════════

  · 웨딩 사진 + 신부 뒷모습 → TRASH (얼굴 미가시 우선)
  · 웨딩 사진 + 신부+신랑 정면 → EVENT
  · 행사장 단체 사진 + 일부만 얼굴 안 보임 → 다수 명확하면 EVENT
  · 햄버거 + 손에 들고 셀카 + 얼굴 명확 → BEST/MEMORY+ (얼굴 우선)
  · 행사 케이크 컷 + 가족 얼굴 명확 → EVENT (행사 우선)
  · 풍경 + 사람 작게 → BEST (사람은 부수)
  · 흑백 모니터 화면 → TRASH (UI 스크린샷)
  · 의도적 흑백 인물 → BEST (필터 적용)

═══════════════════════════════════════════════════════════════════
contains_child (어린이 포함)
═══════════════════════════════════════════════════════════════════

  18세 미만 어린이(영유아·아동·청소년) 1명 이상의 얼굴이 보이면 true.
  어른만 / 사물·풍경뿐 / 어린이 있어도 얼굴 안 보임 → false.

═══════════════════════════════════════════════════════════════════
출력 형식 (JSON만)
═══════════════════════════════════════════════════════════════════

{"grade":"<EVENT|BEST|FOOD|TRASH>","confidence":<1-10>,"reason":"<10자 이내 핵심 이유>","contains_child":<true|false>}

confidence 가이드:
  · 10 = 명확 (예: 정면 셀카 BEST, 웨딩 단체 EVENT)
  · 7-9 = 안전 (대부분의 케이스)
  · 5-6 = 경계 (세부 룰 적용 필요)
  · 1-4 = 불확실 (어두움/잘 안 보임)
"""

LLM_GRADES = {"EVENT", "BEST", "FOOD", "TRASH"}


@dataclass(slots=True)
class Signals:
    face_count: int = 0
    laplacian_variance: float = 0.0
    is_screenshot: bool = False
    is_video: bool = False
    duration_seconds: float = 0.0
    camera_make: str = ""
    # 2026-05-09 안3: EVENT/EVENT-L → +/- 분할 신호 (apply_subgrade에서 사용).
    contains_child: bool = False


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


def _llm_sanity_check(llm_grade: str, signals: Signals) -> tuple[str, str]:
    """LLM 응답 + 자동 신호 sanity check (사용자 명시 강화 2026-05-06).

    LLM이 환각하거나 오판한 케이스 보정:
      - LLM=BEST + 신호 모두 의심 → TRASH 재판정
      - LLM=FOOD + 사람 다수 → 인물 우선 재판정
      - LLM=TRASH + 사람 명확 + 선명 → MEMORY+ 재판정 (단순 흐림 보호)

    반환: (corrected_grade, source_suffix)
    """
    fc = signals.face_count
    lap = signals.laplacian_variance
    cam = signals.camera_make

    # BEST → 신호 모두 의심: 얼굴 X + 카메라메타 X + 매우 흐림
    if llm_grade == "BEST":
        if fc == 0 and not cam and lap < 30 and lap > 0:
            return "TRASH", "_llm_best_unverified"

    # FOOD → 사람 다수 (인물 우선)
    if llm_grade == "FOOD" and fc >= 5:
        return "EVENT", "_llm_food_with_crowd"

    # TRASH → 사람 명확 + 선명 (LLM 오판 의심, 단순 흐림 보호)
    if llm_grade == "TRASH" and fc > 0 and lap >= 100:
        return "MEMORY+", "_llm_trash_face_sharp"

    return llm_grade, ""


VIDEO_SHORT_THRESHOLD = 3.0   # < 3s → TRASH
VIDEO_LONG_THRESHOLD = 10.0   # ≥ 10s → EVENT-L (행사). 3-10s는 MEMORY+ (짧은 일상 영상)


def apply_subgrade(grade: str, signals: Signals, source_path: str = "") -> str:
    """EVENT/EVENT-L 등급에 +/- suffix 적용 (2026-05-09 안3 — iCloud 50GB 한도).

    - EVENT  → EVENT+  (자녀) / EVENT-  (그 외)
    - EVENT-L 이미지 → EVENT-L+ (자녀) / EVENT-L- (그 외)
    - EVENT-L 영상   → EVENT-L+ (source_path '본식' 매칭) / EVENT-L- (그 외)

    BEST/MEMORY+/MEMORY-/NORMAL/FOOD/TRASH는 그대로.
    """
    if grade == "EVENT":
        return "EVENT+" if signals.contains_child else "EVENT-"
    if grade == "EVENT-L":
        if signals.is_video:
            # 영상: 본식 폴더만 보존 (사용자 명시 백업 폴더 추적)
            if "본식" in source_path or "wedding" in source_path.lower():
                return "EVENT-L+"
            return "EVENT-L-"
        # 이미지: 자녀 기반
        return "EVENT-L+" if signals.contains_child else "EVENT-L-"
    return grade


def _auto_grade(llm_grade: str, signals: Signals) -> tuple[str, str]:
    """자동 등급 결정 (CLAUDE.md "자동 분류 룰" + grade_classification_spec.md).

    우선순위:
      1. 영상 길이 (2026-05-08 P1-D 세분화):
         < 3초              → TRASH (auto_short_video)
         3-10초              → MEMORY+ (auto_short_clip — 일상 영상, iCloud 미동기)
         ≥ 10초             → EVENT-L (auto_video — 행사 영상, iCloud 동기)
      2. is_screenshot (UI 스크린샷)
      3. LLM 응답 + sanity check (있으면 그대로 또는 보정)
      4. Auto 신호 fallback (face / camera_make / laplacian)
    """
    if signals.is_video and 0 < signals.duration_seconds < VIDEO_SHORT_THRESHOLD:
        return "TRASH", "auto_short_video"
    if signals.is_video and (
        VIDEO_SHORT_THRESHOLD <= signals.duration_seconds < VIDEO_LONG_THRESHOLD
    ):
        return "MEMORY+", "auto_short_clip"
    if signals.is_video and signals.duration_seconds >= VIDEO_LONG_THRESHOLD:
        return "EVENT-L", "auto_video"
    if signals.is_screenshot:
        return "TRASH", "auto_screenshot"
    if llm_grade in LLM_GRADES:
        # LLM 응답 sanity check (보정 룰)
        corrected, suffix = _llm_sanity_check(llm_grade, signals)
        if suffix:
            return corrected, f"llm_corrected{suffix}"
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

    def classify_image(
        self, path: Path, signals: Signals | None = None,
        source_path: str = "",
    ) -> Decision:
        sig = signals or opencv_signals(path)
        img_b64 = encode_image(path)

        grade, conf, ms, contains_child = "", 0, 0, False
        used_model = ""

        try:
            r = vision_classify(PROMPT, "이 사진의 등급?", img_b64)
            if r.grade in LLM_GRADES:
                grade, conf, ms, contains_child = r.grade, r.confidence, r.elapsed_ms, r.contains_child
                # 2026-05-09 P1-F bugfix: _role(LiteLLM 모델 그룹) 기반 정확 판정.
                # photo/classify-fb → groq / photo/classify → qwen.
                # 이전: _model 누락(빈 값) → 'qwen' 기본값 → 항상 잘못 집계.
                role = r.raw.get("_role", "")
                model = r.raw.get("_model", "")
                if "classify-fb" in role or "groq" in model.lower() or "llama" in model.lower():
                    used_model = "groq"
                else:
                    used_model = "qwen"
        except LLMGatewayError as e:
            logger.warning("vision_classify 완전 실패: %s", e)

        # contains_child를 Signals에 반영 → apply_subgrade에서 사용.
        sig.contains_child = bool(contains_child)
        final, final_src = _auto_grade(grade, sig)
        # 2026-05-09 안3: EVENT/EVENT-L → +/- suffix 적용 (자녀/본식 신호 기반)
        final = apply_subgrade(final, sig, source_path or str(path))
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

    def classify_video(self, path: Path, source_path: str = "") -> Decision:
        dur = video_duration(path)
        sig = Signals(is_video=True, duration_seconds=dur)
        # 2026-05-08 P1-D: 길이 세분화. _auto_grade와 동일 임계 — SSoT 일치.
        if 0 < dur < VIDEO_SHORT_THRESHOLD:
            return Decision(grade="TRASH", confidence=10, source="auto_short_video")
        if VIDEO_SHORT_THRESHOLD <= dur < VIDEO_LONG_THRESHOLD:
            return Decision(grade="MEMORY+", confidence=8, source="auto_short_clip")
        # ≥10s 영상 → EVENT-L 후 본식 폴더 매칭 시 +로 승격
        grade = apply_subgrade("EVENT-L", sig, source_path or str(path))
        return Decision(grade=grade, confidence=8, source="auto_video")
