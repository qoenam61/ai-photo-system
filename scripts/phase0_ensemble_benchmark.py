"""Phase 0-LLM 앙상블 벤치마크 — Qwen + Groq, 4등급 LLM 분류만.

설계 v3.10 §3.4 분류 책임 분리:
  LLM 분류: EVENT, BEST, FOOD, TRASH (의미 4등급)
  자동 분류: MEMORY+/MEMORY-/NORMAL/EVENT-L (객관 신호, 이번 벤치마크 제외)

채점 정책: 사용자 라벨이 자동 4등급(MEMORY+/-/NORMAL)이면 평가 제외.
          LLM 4등급(EVENT/BEST/FOOD/TRASH) 라벨만 정확도 측정.
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

import httpx
from dotenv import load_dotenv
from PIL import Image

load_dotenv()
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.client.groq_client import GroqClient

BENCHMARK_DIR = Path("/Users/Shared/PhotoVault/_benchmark")
OUT_DIR = Path(__file__).parent / "_inventory"
OLLAMA_URL = "http://localhost:11434/api/generate"
QWEN_MODEL = "qwen2.5vl:7b-q4_K_M"

# LLM이 분류하는 4등급만 (의사결정 #40a)
LLM_GRADES = {"EVENT", "BEST", "FOOD", "TRASH"}
ALL_FOLDERS = ["EVENT", "BEST", "FOOD", "MEMORY+", "MEMORY-", "NORMAL", "TRASH"]

PROMPT = """가족 사진 분류기. 4등급 中 정확히 하나로 분류:

판단 순서:
1. UI 스크린샷/완전 흑백/심한 흔들림 → TRASH
2. 음식이 화면 50%+ → FOOD
3. 사람 3+ OR (케이크·꽃다발·드레스·한복·웨딩·돌잔치·생일·졸업·기념일·가족스튜디오·신생아·만삭) → EVENT
4. 그 외 (자랑할 인생샷이거나 평범한 인물 사진) → BEST

JSON만 출력:
{"grade":"<등급>","confidence":<1-10>,"reason":"<짧게>"}"""


@dataclass
class Pred:
    path: Path
    user_label: str
    qwen_grade: str = ""
    qwen_conf: int = 0
    qwen_ms: int = 0
    groq_grade: str = ""
    groq_conf: int = 0
    groq_ms: int = 0
    ensemble_grade: str = ""
    error: str = ""


def load_b64(path: Path, max_dim: int = 1024) -> str:
    suffix = path.suffix.lower()
    if suffix in (".heic", ".heif"):
        tmp = Path("/tmp") / f"_ens_{os.getpid()}_{path.stem}.jpg"
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


def qwen_predict(client: httpx.Client, img_b64: str) -> tuple[str, int, int]:
    start = time.time()
    r = client.post(OLLAMA_URL, json={
        "model": QWEN_MODEL, "system": PROMPT, "prompt": "이 사진의 등급?",
        "images": [img_b64], "stream": False, "format": "json",
        "options": {"num_ctx": 2048, "temperature": 0.0, "num_predict": 128},
        "keep_alive": "30m",
    }, timeout=60)
    elapsed = int((time.time() - start) * 1000)
    r.raise_for_status()
    payload = parse_json(r.json().get("response", "{}"))
    return str(payload.get("grade", "")).strip(), int(payload.get("confidence", 0)), elapsed


def groq_predict(groq: GroqClient, img_b64: str) -> tuple[str, int, int]:
    r = groq.vision(system=PROMPT, user_text="등급?", image_b64=img_b64, max_tokens=150)
    payload = parse_json(r.text)
    return str(payload.get("grade", "")).strip(), int(payload.get("confidence", 0)), r.elapsed_ms


def ensemble(qg: str, qc: int, gg: str, gc: int) -> str:
    if qg == gg and qg in LLM_GRADES:
        return qg
    # 다르면 가중 점수 (Qwen 0.6 + Groq 0.4)
    if qg in LLM_GRADES and gg not in LLM_GRADES:
        return qg
    if gg in LLM_GRADES and qg not in LLM_GRADES:
        return gg
    # 둘 다 LLM 등급, 신뢰도로 결정
    if qc * 0.6 >= gc * 0.4:
        return qg if qg in LLM_GRADES else gg
    return gg if gg in LLM_GRADES else qg


def collect_assets() -> list[tuple[Path, str]]:
    assets: list[tuple[Path, str]] = []
    exts = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp"}
    for grade in ALL_FOLDERS:
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
    eval_assets = [(p, l) for p, l in assets if l in LLM_GRADES]
    print(f"📸 전체 {len(assets)}장 / 평가 대상 {len(eval_assets)}장 (LLM 4등급만)")
    print(f"⚠️  Groq 사진 외부 전송 (v3.10 정책 변경)")

    # 워밍업
    print("🔥 Qwen 워밍업...")
    with httpx.Client(timeout=60) as wc:
        try:
            wc.post(OLLAMA_URL, json={"model": QWEN_MODEL, "prompt": "ready", "stream": False,
                                      "options": {"num_ctx": 1024}}).raise_for_status()
        except Exception:
            pass

    groq = GroqClient()
    results: list[Pred] = []
    rate_sleep = 60.0 / 12  # 12 RPM (Groq vision 안전선)

    with httpx.Client() as oclient:
        for i, (path, label) in enumerate(eval_assets, 1):
            pred = Pred(path=path, user_label=label)
            try:
                img_b64 = load_b64(path)
                # Qwen
                try:
                    pred.qwen_grade, pred.qwen_conf, pred.qwen_ms = qwen_predict(oclient, img_b64)
                except Exception as e:
                    pred.qwen_grade = "ERR"
                # Groq (rate limit 대응)
                for attempt in range(3):
                    try:
                        pred.groq_grade, pred.groq_conf, pred.groq_ms = groq_predict(groq, img_b64)
                        break
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 429 and attempt < 2:
                            time.sleep(20)
                            continue
                        pred.groq_grade = "ERR"
                        break
                    except Exception:
                        pred.groq_grade = "ERR"
                        break

                # 앙상블
                pred.ensemble_grade = ensemble(
                    pred.qwen_grade, pred.qwen_conf,
                    pred.groq_grade, pred.groq_conf,
                )
            except Exception as e:
                pred.error = str(e)[:200]
            results.append(pred)

            ok = pred.ensemble_grade == label
            mark = "✓" if ok else "✗"
            print(f"  [{i:3d}/{len(eval_assets)}] {mark} {label:6s} Q:{pred.qwen_grade:6s} G:{pred.groq_grade:6s} → {pred.ensemble_grade:6s} {path.name[:40]}")

            time.sleep(rate_sleep)

    # CSV
    csv_path = OUT_DIR / "benchmark_ensemble_result.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["path", "user_label", "qwen_grade", "qwen_conf", "qwen_ms",
                    "groq_grade", "groq_conf", "groq_ms",
                    "ensemble_grade", "correct", "error"])
        for p in results:
            w.writerow([str(p.path), p.user_label, p.qwen_grade, p.qwen_conf, p.qwen_ms,
                        p.groq_grade, p.groq_conf, p.groq_ms,
                        p.ensemble_grade, p.ensemble_grade == p.user_label, p.error])

    # Summary
    valid = [p for p in results if p.ensemble_grade and not p.error]
    qwen_correct = sum(1 for p in valid if p.qwen_grade == p.user_label)
    groq_correct = sum(1 for p in valid if p.groq_grade == p.user_label)
    ens_correct = sum(1 for p in valid if p.ensemble_grade == p.user_label)
    total = len(valid)

    by_grade: dict[str, list[Pred]] = {g: [] for g in LLM_GRADES}
    for p in valid:
        by_grade[p.user_label].append(p)

    md = OUT_DIR / "benchmark_ensemble_summary.md"
    with md.open("w") as f:
        f.write("# Phase 0-LLM 앙상블 벤치마크 (v3.10 분류 책임 분리)\n\n")
        f.write(f"- 평가 대상: {len(eval_assets)} (LLM 4등급만, MEMORY/NORMAL 제외)\n")
        f.write(f"- 유효: {total}\n\n")
        f.write("## 정확도 비교\n\n")
        f.write(f"- Qwen 단독:  {qwen_correct/total*100 if total else 0:.1f}% ({qwen_correct}/{total})\n")
        f.write(f"- Groq 단독:  {groq_correct/total*100 if total else 0:.1f}% ({groq_correct}/{total})\n")
        f.write(f"- **앙상블:    {ens_correct/total*100 if total else 0:.1f}% ({ens_correct}/{total})**\n")
        f.write(f"- 합격: {'✅ PASS' if ens_correct/total >= 0.8 else '❌ FAIL'} (목표 80%)\n\n")

        if valid:
            qwen_ms = [p.qwen_ms for p in valid if p.qwen_ms > 0]
            groq_ms = [p.groq_ms for p in valid if p.groq_ms > 0]
            f.write("## 처리 시간\n\n")
            if qwen_ms:
                f.write(f"- Qwen 중앙값: {int(statistics.median(qwen_ms))}ms\n")
            if groq_ms:
                f.write(f"- Groq 중앙값: {int(statistics.median(groq_ms))}ms\n")

        f.write("\n## 등급별 (앙상블)\n\n| 등급 | 자산 | 정확 | % |\n|---|---|---|---|\n")
        for g in sorted(LLM_GRADES):
            preds = by_grade.get(g, [])
            n = len(preds)
            c = sum(1 for p in preds if p.ensemble_grade == g)
            f.write(f"| {g} | {n} | {c} | {(c/n*100 if n else 0):.1f}% |\n")

    print(f"\n📊 Qwen {qwen_correct/total*100 if total else 0:.1f}% / Groq {groq_correct/total*100 if total else 0:.1f}% / 앙상블 {ens_correct/total*100 if total else 0:.1f}%")
    print(f"📂 {csv_path}")
    print(f"📄 {md}")


if __name__ == "__main__":
    main()
