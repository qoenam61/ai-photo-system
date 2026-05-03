"""Phase 0-LLM 벤치마크 — Qwen2.5-VL 7B vs 사용자 라벨.

설계: photo_system_design_v3.md §9 Phase 0-LLM
       local_llm_evaluation.md §10 검증 계획
       architecture_review.md §8.5 Golden dataset CI

입력:  /Users/Shared/PhotoVault/_benchmark/{grade}/*.jpg|heic|png|...
출력:  scripts/_inventory/benchmark_result.csv
       scripts/_inventory/benchmark_summary.md

합격 기준:
  - 8등급 분류 정확도 ≥ 80% (EVENT/EVENT-L 통합 인정)
  - 사진 1장 처리 시간 ≤ 6초
"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import statistics
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from PIL import Image

BENCHMARK_DIR = Path("/Users/Shared/PhotoVault/_benchmark")
OUT_DIR = Path(__file__).parent / "_inventory"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5vl:7b"

# 사용자 라벨 폴더 (벤치마크 대상)
GRADE_FOLDERS = ["EVENT", "BEST", "FOOD", "MEMORY+", "MEMORY-", "NORMAL", "TRASH"]

# 관대한 채점: EVENT 계열 통합
EQUIVALENCE = {
    "EVENT": {"EVENT", "EVENT-L"},
    "EVENT-L": {"EVENT", "EVENT-L"},
}

PROMPT_SYSTEM = """가족 사진 분류기. 정확히 다음 등급 중 하나로 분류:

판단 순서 (위에서부터 첫 일치):
1. UI 스크린샷/완전 흑백/심한 흔들림/중복 → TRASH
2. 음식이 화면 50%+ → FOOD
3. 사람 3+ OR (케이크·꽃다발·드레스·한복·웨딩·돌잔치·생일·가족스튜디오·졸업·기념일) → EVENT
4. 사람 1~2명 + 화질 양호 + 일상 → MEMORY+
5. 사람 1~2명 + 흐림/어두움/구도 어색 → MEMORY-
6. 사람 화면 30% 미만, 풍경/사물/반려동물 主 → NORMAL
7. 위 4번에 해당하지만 매우 잘 나온 인생샷 (자랑 가능) → BEST

핵심 구분:
- BEST vs MEMORY+: "자랑 가능"이면 BEST, "그냥 일상"이면 MEMORY+
- MEMORY+ vs MEMORY-: 흐림/어두움 있으면 MEMORY-
- MEMORY- vs NORMAL: 사람이 主이면 MEMORY-, 풍경/사물이 主이면 NORMAL

JSON만 출력:
{"grade": "<등급>", "confidence": <1-10>, "reason": "<짧은 사유>"}"""


@dataclass
class Prediction:
    path: Path
    user_label: str
    ai_grade: str = ""
    confidence: int = 0
    reason: str = ""
    elapsed_ms: int = 0
    error: str = ""

    @property
    def correct(self) -> bool:
        if not self.ai_grade or self.error:
            return False
        equiv = EQUIVALENCE.get(self.user_label, {self.user_label})
        return self.ai_grade in equiv


def load_image_as_jpeg_b64(path: Path, max_dim: int = 1024) -> str:
    """이미지 로드 + 리사이즈 + JPEG base64 인코딩.

    HEIC/HEIF는 sips로 변환 (Pillow는 HEIC 지원 한정).
    """
    suffix = path.suffix.lower()
    if suffix in (".heic", ".heif"):
        # sips로 임시 JPEG 변환
        tmp = Path("/tmp") / f"_bench_{os.getpid()}_{path.stem}.jpg"
        subprocess.run(
            ["sips", "-s", "format", "jpeg", "-Z", str(max_dim),
             str(path), "--out", str(tmp)],
            capture_output=True, check=True, timeout=30,
        )
        data = tmp.read_bytes()
        tmp.unlink(missing_ok=True)
        return base64.b64encode(data).decode()

    # 일반 포맷: Pillow로 리사이즈 후 JPEG 인코딩
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_dim, max_dim))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode()


def predict(client: httpx.Client, img_b64: str) -> tuple[dict, int]:
    """Ollama API 호출. (응답 dict, 처리 시간 ms) 반환."""
    payload = {
        "model": MODEL,
        "system": PROMPT_SYSTEM,
        "prompt": "이 사진의 등급은? JSON으로만 답하세요.",
        "images": [img_b64],
        "stream": False,
        "format": "json",
        "options": {"num_ctx": 2048, "temperature": 0.0, "num_predict": 128},
        "keep_alive": "30m",
    }
    start = time.time()
    resp = client.post(OLLAMA_URL, json=payload, timeout=60.0)
    elapsed_ms = int((time.time() - start) * 1000)
    resp.raise_for_status()
    body = resp.json()
    response_text = body.get("response", "{}")
    return json.loads(response_text), elapsed_ms


def collect_assets() -> list[tuple[Path, str]]:
    """벤치마크 폴더 스캔 → (path, user_label) 리스트."""
    assets: list[tuple[Path, str]] = []
    exts = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp"}
    for grade in GRADE_FOLDERS:
        folder = BENCHMARK_DIR / grade
        if not folder.exists():
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in exts:
                assets.append((path, grade))
    return assets


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    assets = collect_assets()
    print(f"📸 벤치마크 자산: {len(assets)} 장")
    print(f"📂 출력: {OUT_DIR}")
    print()

    # Ollama 워밍업
    print("🔥 Qwen2.5-VL 7B 워밍업 (첫 추론 시간 제외용)...")
    with httpx.Client() as client:
        try:
            client.post(OLLAMA_URL, json={
                "model": MODEL,
                "prompt": "ready",
                "stream": False,
                "options": {"num_ctx": 1024},
            }, timeout=60.0).raise_for_status()
        except Exception as e:
            print(f"  ⚠️ 워밍업 실패: {e}")

    print("🤖 분류 시작\n")
    results: list[Prediction] = []
    with httpx.Client() as client:
        for i, (path, label) in enumerate(assets, 1):
            pred = Prediction(path=path, user_label=label)
            try:
                img_b64 = load_image_as_jpeg_b64(path)
                resp, ms = predict(client, img_b64)
                pred.ai_grade = str(resp.get("grade", "")).strip()
                pred.confidence = int(resp.get("confidence", 0))
                pred.reason = str(resp.get("reason", ""))
                pred.elapsed_ms = ms
            except Exception as e:
                pred.error = str(e)[:200]
            results.append(pred)

            mark = "✓" if pred.correct else ("✗" if not pred.error else "⚠")
            print(
                f"  [{i:3d}/{len(assets)}] {mark} {label:9s} "
                f"→ {pred.ai_grade:9s} ({pred.elapsed_ms:4d}ms) "
                f"{path.name}"
            )

    # ─────────────────────────────────────
    # CSV 저장
    # ─────────────────────────────────────
    csv_path = OUT_DIR / "benchmark_result.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "path", "user_label", "ai_grade", "correct",
            "confidence", "reason", "elapsed_ms", "error",
        ])
        for p in results:
            writer.writerow([
                str(p.path), p.user_label, p.ai_grade, p.correct,
                p.confidence, p.reason, p.elapsed_ms, p.error,
            ])

    # ─────────────────────────────────────
    # 통계 + 요약 마크다운
    # ─────────────────────────────────────
    valid = [p for p in results if not p.error]
    correct_n = sum(1 for p in valid if p.correct)
    accuracy = correct_n / len(valid) if valid else 0.0
    elapsed_list = [p.elapsed_ms for p in valid]
    p50 = int(statistics.median(elapsed_list)) if elapsed_list else 0
    p95 = int(sorted(elapsed_list)[int(len(elapsed_list) * 0.95)]) if elapsed_list else 0
    avg = int(statistics.mean(elapsed_list)) if elapsed_list else 0

    # 등급별 정확도
    by_grade: dict[str, list[Prediction]] = {g: [] for g in GRADE_FOLDERS}
    for p in valid:
        by_grade[p.user_label].append(p)

    # confusion: 실제 → 예측 분포
    confusion: dict[str, dict[str, int]] = {g: {} for g in GRADE_FOLDERS}
    for p in valid:
        confusion[p.user_label].setdefault(p.ai_grade, 0)
        confusion[p.user_label][p.ai_grade] += 1

    # 미스매치 (사용자 라벨 ≠ AI 예측)
    mismatches = [p for p in valid if not p.correct]

    md = OUT_DIR / "benchmark_summary.md"
    with md.open("w") as f:
        f.write("# Phase 0-LLM 벤치마크 결과\n\n")
        f.write(f"- **모델**: {MODEL}\n")
        f.write(f"- **벤치마크 자산**: {len(assets)} 장\n")
        f.write(f"- **유효**: {len(valid)} / 오류 {len(results) - len(valid)}\n\n")

        f.write("## 종합 정확도\n\n")
        f.write(f"- **정확도**: **{accuracy:.1%}** ({correct_n}/{len(valid)})\n")
        f.write(f"- **합격 기준 (80%)**: {'✅ PASS' if accuracy >= 0.8 else '❌ FAIL'}\n\n")

        f.write("## 처리 시간 (ms)\n\n")
        f.write(f"- 평균: {avg} / 중앙값: {p50} / p95: {p95}\n")
        f.write(f"- 합격 기준 (1장 ≤ 6000ms): {'✅ PASS' if p50 <= 6000 else '❌ FAIL'}\n\n")

        f.write("## 등급별 정확도\n\n")
        f.write("| 등급 | 자산 | 정확 | 정확도 |\n|---|---|---|---|\n")
        for g in GRADE_FOLDERS:
            preds = by_grade[g]
            n = len(preds)
            ok = sum(1 for p in preds if p.correct)
            acc = (ok / n) if n else 0
            f.write(f"| {g} | {n} | {ok} | {acc:.1%} |\n")

        f.write("\n## Confusion Matrix (사용자 라벨 → AI 예측 분포)\n\n")
        for g in GRADE_FOLDERS:
            if not confusion[g]:
                continue
            f.write(f"\n### {g} ({len(by_grade[g])} 장)\n")
            for ai, cnt in sorted(confusion[g].items(), key=lambda x: -x[1]):
                marker = " ✓" if ai == g or ai in EQUIVALENCE.get(g, set()) else ""
                f.write(f"  - {ai}: {cnt}{marker}\n")

        f.write(f"\n## 재분류 후보 ({len(mismatches)} 장)\n\n")
        f.write("AI 예측이 사용자 라벨과 다름 — 검토하시고 폴더 이동 또는 그대로 유지 결정.\n\n")
        f.write("| # | 파일 | 사용자 | AI | 신뢰도 | AI 사유 |\n|---|---|---|---|---|---|\n")
        for i, p in enumerate(sorted(mismatches, key=lambda x: -x.confidence), 1):
            f.write(
                f"| {i} | `{p.path.name}` | **{p.user_label}** | "
                f"**{p.ai_grade}** | {p.confidence} | {p.reason[:80]} |\n"
            )

    print()
    print("=" * 60)
    print(f"📊 종합 정확도: {accuracy:.1%}  ({'PASS' if accuracy >= 0.8 else 'FAIL'})")
    print(f"⏱️  중앙값 처리 시간: {p50} ms ({'PASS' if p50 <= 6000 else 'FAIL'})")
    print(f"🔄 재분류 후보: {len(mismatches)} 장")
    print(f"📂 결과: {csv_path}")
    print(f"📄 리포트: {md}")
    print("=" * 60)


if __name__ == "__main__":
    main()
