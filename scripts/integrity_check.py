"""데이터 무결성 모니터링 — DB ↔ Immich ↔ HDD ↔ immich-views 정합 검증.

사용자 명시 (2026-05-05): 자산 수 차이 / orphan 자동 감시. 차이 발견 시 Telegram 알림.

검증 항목:
  1. photo.classification 자산 수 vs Immich active asset
  2. classification grade별 분포 vs immich-views/{GRADE}/ symlink 수
  3. cleanup_queue.processed = cleanup_audit.success
  4. broken symlink (immich-views) 수
  5. orphan: classification 행 + Immich에서 deletedAt
  6. orphan: classification 행 + 외장 HDD 파일 미존재 (legacy만)

trigger: maintenance.sh 일일 또는 weekly cron.

Usage:
  PYTHONPATH=. poetry run python scripts/integrity_check.py [--telegram]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import os
import subprocess
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv(
    "PHOTO_DB_DSN_HOST",
    "host=localhost port=5432 dbname=trading_db "
    "user=trading_user password=RyIokQY7bV3y7SEsyFLu2Oa6",
)
LIBRARY_HOST = Path("/Volumes/Immich-Storage/immich-media/library")
VIEWS_HOST = Path("/Volumes/Immich-Storage/immich-views")
GRADES = (
    "BEST", "EVENT+", "EVENT-", "EVENT-L+", "EVENT-L-",
    "FOOD", "MEMORY+", "MEMORY-", "NORMAL", "TRASH",
)  # 2026-05-09 안3: EVENT/EVENT-L → +/- 분할 (10등급)


def fetch_db_stats() -> dict:
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT grade, COUNT(*) FROM photo.classification
            GROUP BY grade ORDER BY grade
        """)
        by_grade = dict(cur.fetchall())

        cur.execute("""
            SELECT
              (SELECT COUNT(*) FROM photo.classification),
              (SELECT COUNT(*) FROM photo.cleanup_queue WHERE processed_at IS NOT NULL),
              (SELECT COUNT(*) FROM photo.cleanup_audit WHERE success AND device='hdd')
        """)
        classified, processed, audit_ok = cur.fetchone()

    return {"by_grade": by_grade, "classified": classified,
            "processed": processed, "audit_ok": audit_ok}


def fetch_immich_stats() -> dict:
    proc = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "--csv", "-c",
         """SELECT COUNT(*) FILTER (WHERE "deletedAt" IS NULL) AS active,
                   COUNT(*) FILTER (WHERE "deletedAt" IS NOT NULL) AS deleted
            FROM asset"""],
        capture_output=True, text=True, check=True,
    )
    rows = list(csv.reader(io.StringIO(proc.stdout)))[1:]
    return {"active": int(rows[0][0]), "deleted": int(rows[0][1])}


def fetch_db_immich_match() -> dict:
    """DB asset_id ↔ Immich originalPath stem 정확 매칭 (2026-05-08 P1-G 보강).

    이전 단순 카운트 비교는 cleanup_audit success → Immich.deletedAt 자산을
    "갭"으로 오인. 본 함수는 set 매칭으로 진짜 갭만 추출.

    Returns:
      db_in_active     — DB asset_id 中 Immich active 매칭 (정상)
      db_in_deleted    — DB asset_id 中 Immich deleted 매칭 (cleanup 처리됨)
      db_missing       — DB asset_id 中 Immich에 아예 없음 (orphan — 진짜 갭)
      immich_unclassified — Immich active 中 DB classification 없음 (분류 누락)
    """
    # DB asset_id 목록 → 임시 파일
    proc = subprocess.run(
        ["docker", "exec", "-i", "trading_postgres",
         "psql", "-U", "trading_user", "-d", "trading_db", "-t", "-A", "-c",
         "SELECT asset_id::text FROM photo.classification"],
        capture_output=True, text=True, check=True, timeout=60,
    )
    # docker cp 대용 — psql -c에 stdin으로 COPY
    asset_ids_payload = proc.stdout.strip()
    if not asset_ids_payload:
        return {"db_in_active": 0, "db_in_deleted": 0,
                "db_missing": 0, "immich_unclassified": 0}

    sql = """
    CREATE TEMP TABLE _db_ids (asset_id TEXT);
    COPY _db_ids FROM stdin;
    SELECT
      COUNT(*) FILTER (WHERE a."deletedAt" IS NULL) AS db_in_active,
      COUNT(*) FILTER (WHERE a."deletedAt" IS NOT NULL) AS db_in_deleted,
      COUNT(*) FILTER (WHERE a.id IS NULL) AS db_missing
    FROM _db_ids d
    LEFT JOIN asset a ON SPLIT_PART(
        REVERSE(SPLIT_PART(REVERSE(a."originalPath"), '/', 1)), '.', 1
    ) = d.asset_id;
    """
    full_input = sql.replace(
        "COPY _db_ids FROM stdin;",
        f"COPY _db_ids FROM stdin;\n{asset_ids_payload}\n\\.\n",
    )
    proc2 = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "--csv"],
        input=full_input, capture_output=True, text=True, timeout=120,
    )
    rows = list(csv.reader(io.StringIO(proc2.stdout)))
    # 헤더 + 결과 row 추출
    data_rows = [r for r in rows if r and r[0].isdigit()]
    if not data_rows:
        return {"db_in_active": 0, "db_in_deleted": 0,
                "db_missing": 0, "immich_unclassified": 0}
    a, d, m = (int(x) for x in data_rows[0][:3])

    # immich_unclassified = Immich active - db_in_active
    proc3 = subprocess.run(
        ["docker", "exec", "-i", "immich-postgres",
         "psql", "-U", "postgres", "-d", "immich", "-t", "-A", "-c",
         "SELECT COUNT(*) FROM asset WHERE \"deletedAt\" IS NULL"],
        capture_output=True, text=True, check=True, timeout=30,
    )
    immich_active_total = int(proc3.stdout.strip() or 0)
    return {
        "db_in_active": a, "db_in_deleted": d, "db_missing": m,
        "immich_unclassified": max(0, immich_active_total - a),
    }


def fetch_hdd_stats() -> dict:
    out = {}
    for g in GRADES:
        d = LIBRARY_HOST / g
        if not d.exists():
            out[g] = 0
            continue
        out[g] = sum(1 for _ in d.iterdir() if _.is_file())
    return out


def fetch_views_stats() -> dict:
    out = {"by_grade": {}, "broken": 0}
    for g in GRADES:
        d = VIEWS_HOST / g
        if not d.exists():
            out["by_grade"][g] = 0
            continue
        total = broken = 0
        for entry in d.iterdir():
            if entry.is_symlink():
                total += 1
                if not entry.exists():
                    broken += 1
        out["by_grade"][g] = total
        out["broken"] += broken
    return out


def fetch_audit_failures(hours: int = 48) -> dict:
    """최근 N시간 cleanup_audit 실패율. 2026-05-08 P1-G."""
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT reason_category,
                   COUNT(*) FILTER (WHERE NOT success) AS fail,
                   COUNT(*) AS total
            FROM photo.cleanup_audit
            WHERE reported_at > NOW() - (%s || ' hours')::interval
            GROUP BY reason_category
            ORDER BY 2 DESC
        """, (str(hours),))
        rows = cur.fetchall()
    return {r[0]: {"fail": r[1], "total": r[2]} for r in rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--telegram", action="store_true",
                        help="이상 발견 시 Telegram 알림")
    parser.add_argument("--strict", action="store_true",
                        help="갭 > 0 즉시 FAIL (관대 임계 무시). 2026-05-08 P1-G.")
    parser.add_argument("--exit-code", action="store_true",
                        help="이상 발견 시 exit 1 (CI/배포 검증용)")
    args = parser.parse_args()

    print("🔍 무결성 검증 시작 ...")
    if args.strict:
        print("   STRICT 모드 — 갭 > 0 즉시 FAIL\n")
    else:
        print()

    db = fetch_db_stats()
    immich = fetch_immich_stats()
    hdd = fetch_hdd_stats()
    views = fetch_views_stats()
    match = fetch_db_immich_match()  # 2026-05-08 P1-G 보강

    issues: list[str] = []
    warnings: list[str] = []  # strict 모드에서만 issue 승격

    # 1. DB ↔ Immich 정확 매칭 (단순 카운트 X — cleanup 처리 자산을 갭으로 오인 방지)
    print(f"📊 DB classification: {db['classified']}")
    print(f"   Immich active:    {immich['active']} / deleted: {immich['deleted']}")
    print(f"   DB↔Immich 매칭:")
    print(f"     active 매칭:   {match['db_in_active']:>6d}")
    print(f"     deleted 매칭:  {match['db_in_deleted']:>6d}  (cleanup 처리 — 정상)")
    print(f"     Immich 미발견: {match['db_missing']:>6d}  (orphan — 진짜 갭)")
    print(f"     분류 누락:     {match['immich_unclassified']:>6d}  (Immich active 中 DB X)")

    if match["db_missing"] > 0:
        issues.append(f"orphan {match['db_missing']}장 (DB에 있으나 Immich 미발견)")
    if match["immich_unclassified"] > 50:
        issues.append(
            f"분류 누락 {match['immich_unclassified']}장 — auto_classify_pending 실행"
        )
    elif match["immich_unclassified"] > 0:
        warnings.append(f"분류 누락 {match['immich_unclassified']}장 (다음 cron에서 처리)")

    # 2. cleanup queue processed = audit success
    if db["processed"] != db["audit_ok"]:
        issues.append(f"queue processed({db['processed']}) ≠ audit success({db['audit_ok']})")
    print(f"\n📋 cleanup: processed={db['processed']} audit_success={db['audit_ok']}")

    # 3. immich-views broken symlinks
    print(f"\n🔗 immich-views broken symlinks: {views['broken']}")
    if views["broken"] > 0:
        issues.append(f"broken symlinks {views['broken']}개")

    # 4. 등급별 정합 (DB vs views) — HDD는 legacy만이라 의미 X (정보용)
    # 임계: 일반 등급 50 / TRASH 1000 (orphan classification 자연 발생)
    print(f"\n📁 등급별 정합 (DB vs views; HDD=legacy library만):")
    print(f"   {'GRADE':10s} {'DB':>7s} {'HDD':>7s} {'views':>7s}  Δ(DB-views)")
    for g in GRADES:
        d_cnt = db["by_grade"].get(g, 0)
        h_cnt = hdd.get(g, 0)
        v_cnt = views["by_grade"].get(g, 0)
        diff = abs(d_cnt - v_cnt)
        # TRASH는 view symlink 미생성 정책 → diff = d_cnt 자연 발생
        if g == "TRASH":
            print(f"   {g:10s} {d_cnt:>7d} {h_cnt:>7d} {v_cnt:>7d}  (TRASH: view 미생성)")
            continue
        threshold = 50
        mark = " ⚠️" if diff > threshold else ""
        print(f"   {g:10s} {d_cnt:>7d} {h_cnt:>7d} {v_cnt:>7d}  {diff}{mark}")
        if diff > threshold:
            issues.append(f"{g}: DB={d_cnt} vs views={v_cnt} 차이 {diff}")
        elif diff > 0:
            warnings.append(f"{g}: view symlink 갭 {diff}장")

    # 5. cleanup_audit 실패율 (최근 48h) — 2026-05-08 P1-G 신규
    fails = fetch_audit_failures(hours=48)
    fail_categories = {k: v for k, v in fails.items() if v["fail"] > 0}
    if fail_categories:
        print(f"\n⚠️  최근 48h cleanup 실패 (reason_category):")
        total_fail = total_op = 0
        for cat, st in fail_categories.items():
            print(f"   {cat:25s} {st['fail']:>4d} fail / {st['total']:>4d} total")
            total_fail += st["fail"]
            total_op += st["total"]
        if total_op > 0 and total_fail / total_op > 0.20:
            issues.append(
                f"cleanup 실패율 {total_fail / total_op * 100:.1f}% "
                f"({total_fail}/{total_op}) — 임계 20% 초과"
            )

    # strict 모드 — warnings를 issues로 승격
    if args.strict and warnings:
        issues.extend(f"[strict] {w}" for w in warnings)

    print()
    if not issues:
        if warnings:
            print(f"✅ 무결성 PASS (strict X) — 경고 {len(warnings)}건:")
            for w in warnings:
                print(f"  · {w}")
        else:
            print("✅ 무결성 PASS — 모든 정합 정상")
    else:
        print(f"❌ 무결성 FAIL — 이상 {len(issues)}건:")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")

        if args.telegram:
            # idempotent flag — 같은 이상 7일 내 중복 알림 X (NSC-2)
            issue_hash = hashlib.md5(
                "\n".join(sorted(issues)).encode()
            ).hexdigest()[:12]
            flag = Path(f"scripts/_inventory/integrity_alert_{issue_hash}.flag")
            now = time.time()
            if flag.exists() and (now - flag.stat().st_mtime) < 7 * 86400:
                print(f"  (같은 이상 7일 내 알림됨 — skip: {flag.name})")
            else:
                body = "\n".join(f"- {i}" for i in issues)
                subprocess.run(
                    ["bash", "scripts/notify_telegram.sh",
                     "Photo 무결성 이상 감지", body],
                    check=False,
                )
                flag.touch()

    if args.exit_code and issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
