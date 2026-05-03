# Layer 6 — iOS Shortcut 가이드 (jw.son iPhone)

> 사용자가 직접 iPhone에서 Shortcut 앱으로 만들기. 코드 작성 없음.
>
> 목적: Immich 백업 완료 + 등급 결정 후 iPhone에서 EVENT/BEST/MEMORY+ 외 자산 삭제.
>
> ⚠️ **도메인 안전 영역**. Shortcut은 dry-run 모드로 14일 검증 후 실삭제 활성.

## 사전 조건

- [x] iPhone Immich 모바일 앱 백업 활성 (Wi-Fi + 충전 시)
- [x] Immich 서버 도달 가능 (https://photo.jwcloud.my)
- [x] photo-classify-service 가동 (M4 Mac mini)
- [ ] Phase 5 dry-run 14일 정상 누적
- [ ] 사용자 명시 승인 (실삭제 활성)

## Shortcut 구성 (단계별)

### Shortcut 이름: `Photo Cleanup (jw.son)`

```
[1] Get Current Date
    Output → Today
[2] If [Day of Week is Sunday]
    → Continue (주 1회만 실행)
    Else → Stop
[3] Get Time Component (Today, Hour)
    If [Hour ≥ 3 AND Hour ≤ 5]
    → Continue (03:00~05:00 윈도)
    Else → Stop
[4] Get Battery Level
    If [Charging State is true AND Level ≥ 80%]
    → Continue (Wi-Fi 조건 X — 무제한 요금제)
    Else → Stop
```

### 4단계 — 분류 결과 + 백업 검증 통과 자산 조회

```
[6] Get Contents of URL
    URL: https://photo.jwcloud.my/cleanup_candidates?grades=NORMAL,TRASH,FOOD&min_age_days=14&limit=200
    Method: GET
    (classify-service 8765 → Cloudflare 터널 외부 노출 필요. 임시로 LAN 내부 IP 사용 가능)

    Response: {
      "verified_safe": N,
      "items": [
        {"asset_id":"...", "immich_id":"...", "immich_path":"...",
         "grade":"TRASH", "sha256":"...", "file_size_bytes":...}
      ]
    }
```

⚠️ **이 엔드포인트는 verify_asset() 3중 검증 (DB + 파일 + SHA256 + Immich 등록)을
   통과한 자산만 반환**. 검증 실패 자산은 응답에서 자동 제외됨.

### 5단계 — 디바이스에서 매칭 사진 삭제 (DRY-RUN)

```
[7] Find Photos where [Filename matches asset_list[i].originalPath stem]
    Output → matched_photos
[8] Show Notification
    "Cleanup dry-run: matched_photos.count 장이 삭제될 예정"
    (실삭제 X — Phase 5 활성화 후 [Delete Photos] 노드로 교체)
```

### 6단계 (Phase 5 활성화 시) — 실삭제

```
[8'] Delete Photos (matched_photos)
    Show Notification: "Cleanup 완료 — N장 삭제, 디스크 X MB 회수"
    Append to Log:
      Photo Cleanup Log.txt
      <date> <user> <count> <reclaimed_mb>
```

## 자동화 트리거

```
Settings → Automation → Create Personal Automation
  Trigger: Time of Day = 04:00, Daily, Run Immediately (no notification)
  Action: Run Shortcut "Photo Cleanup (jw.son)"
```

## 안전 메커니즘 (다층 게이트)

| 게이트 | 구현 위치 | 동작 |
|---|---|---|
| **3중 백업 검증** | `core/service/backup_verifier.py` | DB sha256 + 파일 존재 + 실 SHA256 + Immich 등록 모두 PASS 시에만 cleanup_candidates에 포함 |
| **14일 등급 안정화** | `cleanup_candidates(min_age_days=14)` | 분류 직후 자산 보호 |
| **사용자 보호 표시** | `photo.feedback feedback_type='protect'` (가동 중) | 표시 자산 cleanup_candidates 자동 제외, verify_asset 우회 (DB 단계에서 차단) |
| **실수 복구** | iCloud "Recently Deleted" | 30일 보관 — 즉시 복구 가능 |
| **백업 미완료 시 자동 skip** | verify_asset의 Immich 등록 체크 | originalPath 미등록 자산 자동 제외 |
| **dry-run 14일 누적** | Shortcut [Show Notification] 단계 | Phase 5 활성 전 사용자 검토 |

## 사용자 보호 (Photo Cleanup 제외) 사용법

### 특정 사진을 cleanup 대상에서 제외하기

```bash
# 보호 표시
curl -X POST http://photo-classify:8000/feedback/protect \
  -H "Content-Type: application/json" \
  -d '{"asset_id":"<UUID>"}'

# 보호 목록 확인
curl http://photo-classify:8000/feedback/protect

# 보호 해제
curl -X DELETE http://photo-classify:8000/feedback/protect/<UUID>
```

### iOS Shortcut에서 즐겨찾기 → 자동 보호 (선택)

Photos 앱의 ♥ 즐겨찾기를 photo.feedback 보호로 자동 동기화하는 별도 Shortcut:

```
Trigger: When favorite is added/removed
Action: HTTP POST /feedback/protect (추가) or DELETE /feedback/protect/{id} (해제)
```

이렇게 하면 사용자가 ♥ 누르는 즉시 cleanup 대상에서 제외됨.

## eunju Galaxy (참조용)

eunju Galaxy는 MacroDroid 사용 — 별도 가이드 (`runbooks/layer6_macrodroid.md`, 미작성).

핵심 차이:
- Shortcut → MacroDroid (Galaxy 자동화 앱)
- Find Photos → Folder Browser + Filename 매칭
- Delete Photos → File Operations (Move to Trash)

## 검증 시나리오 (Phase 5 진입 전)

1. dry-run 모드로 7일 실행 → 알림으로 매일 매칭 자산 수 확인
2. iCloud 사진 / Immich 자산 수 일치 검증
3. 사용자가 보호하고 싶은 사진 1~2장을 보호 표시 → 7일 후 dry-run 결과에 미포함 확인
4. Phase 5 활성 승인 → 8단계 [Delete Photos] 활성

## 롤백

문제 발생 시:
1. Settings → Automation → Photo Cleanup → 비활성화
2. iCloud "Recently Deleted" → 사진 복구 (30일 이내)
3. classify-service 로그 확인 (`docker logs photo-classify`)

## 관련 문서

- `photo_system_design_v3.md` §5.6 Layer 6 기기 정리
- `scripts/phase5_dryrun_report.py` — 실삭제 후보 보고서
- `runbooks/disaster_recovery.md` — 잘못 삭제 시 복구 (미작성)
