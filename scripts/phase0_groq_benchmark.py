"""Phase 0-LLM Groq Vision 벤치마크 (Llama-4-scout-17B).

⚠️ 사진을 Groq 외부 서버로 전송. 사용자 명시 정책 변경 시만 사용.
출력: scripts/_inventory/benchmark_groq_result.csv
       scripts/_inventory/benchmark_groq_summary.md
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
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image

load_dotenv()

from core.client.groq_client import GroqClient

BENCHMARK_DIR = Path("/Users/Shared/PhotoVault/_benchmark")
OUT_DIR = Path(__file__).parent / "_inventory"
GRADE_FOLDERS = ["EVENT", "BEST", "FOOD", "MEMORY+", "MEMORY-", "NORMAL", "TRASH"]
EQUIVALENCE = {"EVENT": {"EVENT", "EVENT-L"}, "EVENT-L": {"EVENT", "EVENT-L"}}

PROMPT_SYSTEM = """가족 사진 분류기. 정확히 다음 등급 중 하나로 분류:

판단 순서 (위에서부터 첫 일치):
1. UI 스크린샷/완전 흑백/심한 흔들림/중복 → TRASH
2. 음식이 화면 50%+ → FOOD
3. 사람 3+ OR (케이크·꽃다발·드레스·한복·웨딩·돌잔치·생일·가족스튜디오·졸업·기념일) → EVENT
4. 사람 1~2명 + 화질 양호 + 일상 → MEMORY+
5. 사람 1~2명 + 흐림/어두움/구도 어색 → MEMORY-
6. 사람 화면 30% 미만, 풍경/사물/반려동물 主 → NORMAL
7. 위 4번 사진이 매우 잘 나온 인생샷이면 → BEST

JSON만 출력 (다른 텍스트 금지):
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


def load_image_b64(path: Path, max_dim: int = 1024) -> str:
    suffix = path.suffix.lower()
    if suffix in (".heic", ".heif"):
        tmp = Path("/tmp") / f"_groq_{os.getpid()}_{path.stem}.jpg"
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


def collect_assets() -> list[tuple[Path, str]]:
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
    print(f"📸 Groq Vision 벤치마크: {len(assets)}장")
    print(f"⚠️  사진을 Groq 서버로 전송 (사용자 명시 정책)")
    print()

    client = GroqClient()
    results: list[Prediction] = []
    rate_sleep = 60.0 / 28  # 30 RPM 한도, 안전 마진 28

    for i, (path, label) in enumerate(assets, 1):
        pred = Prediction(path=path, user_label=label)
        try:
            img_b64 = load_image_b64(path)
            r = client.vision(
                system=PROMPT_SYSTEM,
                user_text="이 사진의 등급?",
                image_b64=img_b64,
                max_tokens=200,
            )
            try:
                payload = json.loads(r.text.strip().replace("```json", "").replace("```", "").strip())
                pred.ai_grade = str(payload.get("grade", "")).strip()
                pred.confidence = int(payload.get("confidence", 0))
                pred.reason = str(payload.get("reason", ""))[:120]
            except Exception:
                pred.ai_grade = "PARSE_ERROR"
                pred.reason = r.text[:120]
            pred.elapsed_ms = r.elapsed_ms
        except Exception as e:
            pred.error = str(e)[:200]
        results.append(pred)

        mark = "✓" if pred.correct else ("✗" if not pred.error else "⚠")
        print(f"  [{i:3d}/{len(assets)}] {mark} {label:9s} → {pred.ai_grade:9s} ({pred.elapsed_ms:5d}ms) {path.name[:60]}")

        # Rate limit (30 RPM)
        if i < len(assets):
            time.sleep(rate_sleep)

    # CSV
    csv_path = OUT_DIR / "benchmark_groq_result.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["path", "user_label", "ai_grade", "correct", "confidence", "reason", "elapsed_ms", "error"])
        for p in results:
            w.writerow([str(p.path), p.user_label, p.ai_grade, p.correct, p.confidence, p.reason, p.elapsed_ms, p.error])

    # Summary
    valid = [p for p in results if not p.error]
    correct_n = sum(1 for p in valid if p.correct)
    accuracy = correct_n / len(valid) if valid else 0.0
    elapsed = [p.elapsed_ms for p in valid]
    p50 = int(statistics.median(elapsed)) if elapsed else 0
    p95 = int(sorted(elapsed)[int(len(elapsed)*0.95)]) if elapsed else 0

    by_grade = {g: [] for g in GRADE_FOLDERS}
    for p in valid:
        by_grade[p.user_label].append(p)
    confusion = {g: {} for g in GRADE_FOLDERS}
    for p in valid:
        confusion[p.user_label].setdefault(p.ai_grade, 0)
        confusion[p.user_label][p.ai_grade] += 1
    mismatches = [p for p in valid if not p.correct]

    md = OUT_DIR / "benchmark_groq_summary.md"
    with md.open("w") as f:
        f.write(f"# Phase 0-LLM Groq Vision 벤치마크\n\n")
        f.write(f"- 모델: meta-llama/llama-4-scout-17b-16e-instruct\n")
        f.write(f"- 자산: {len(assets)} / 유효 {len(valid)}\n\n")
        f.write(f"## 정확도\n\n- **{accuracy:.1%}** ({correct_n}/{len(valid)}) — {'✅ PASS' if accuracy >= 0.8 else '❌ FAIL'}\n\n")
        f.write(f"## 처리 시간\n\n- 중앙값 {p50}ms / p95 {p95}ms — {'✅ PASS' if p50 <= 6000 else '❌ FAIL'}\n\n")
        f.write("## 등급별\n\n| 등급 | 자산 | 정확 | % |\n|---|---|---|---|\n")
        for g in GRADE_FOLDERS:
            preds = by_grade[g]
            n, ok = len(preds), sum(1 for p in preds if p.correct)
            f.write(f"| {g} | {n} | {ok} | {(ok/n*100 if n else 0):.1f}% |\n")
        f.write("\n## Confusion (사용자 → AI)\n\n")
        for g in GRADE_FOLDERS:
            if not confusion[g]:
                continue
            f.write(f"### {g} ({len(by_grade[g])})\n")
            for ai, c in sorted(confusion[g].items(), key=lambda x: -x[1]):
                check = " ✓" if ai in EQUIVALENCE.get(g, {g}) else ""
                f.write(f"- {ai}: {c}{check}\n")

    print(f"\n📊 정확도: {accuracy:.1%}  중앙값 {p50}ms")
    print(f"📂 {csv_path}")
    print(f"📄 {md}")


if __name__ == "__main__":
    main()
