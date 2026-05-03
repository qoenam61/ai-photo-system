# Layer 6 — MacroDroid 가이드 (eunju Galaxy)

> 사용자가 직접 Galaxy에서 MacroDroid 앱으로 매크로 4개 구성. 코드 작성 없음.
>
> 목적: Immich 백업 완료 + 등급 결정 + 백업 검증 PASS 후 Galaxy에서 EVENT/BEST/MEMORY+ 외 자산 삭제.
>
> ⚠️ **도메인 안전 영역**. 매크로는 dry-run 모드로 14일 검증 후 실삭제 활성.

## 사전 조건

- [x] Galaxy Immich 모바일 앱 백업 활성 (충전 시 — 무제한 요금제로 Wi-Fi 조건 제외)
- [x] Immich 서버 도달 가능 (https://photo.jwcloud.my)
- [x] photo-classify-service `/cleanup-api/*` 외부 노출 (Caddy + Cloudflare)
- [x] MacroDroid 5.x 무료 버전 (또는 Pro)
- [ ] Phase 5 dry-run 14일 정상 누적
- [ ] 사용자 명시 승인 (실삭제 활성)

## 매크로 4개 구성

### 매크로 #1: Cleanup Trigger

```
이름: Photo Cleanup Trigger (eunju)
조건: 모든 다음 충족
  - 시간: 매일 04:00
  - 배터리 수준 ≥ 80%
  - 충전 중
  (Wi-Fi 조건 제외 — 무제한 요금제)
액션:
  1. HTTP Request GET
     URL: https://photo.jwcloud.my/cleanup-api/cleanup_candidates?grades=NORMAL,TRASH,FOOD&min_age_days=14
     응답 → 변수 cleanup_response (JSON)
  2. 디바이스 변수 저장:
     items_count = {{$cleanup_response.verified_safe}}
     items = {{$cleanup_response.items}}
  3. If items_count > 0
     → 매크로 #2 트리거
     Else → 알림 "정리 대상 없음"
```

### 매크로 #2: Cleanup Loop (실삭제 — Phase 5 활성 후)

```
이름: Photo Cleanup Loop
트리거: 매크로 #1에서 호출
액션:
  Loop For Each (var: item, list: items)
    1. 변수 추출:
       asset_id = {{$item.asset_id}}
       immich_id = {{$item.immich_id}}
       sha256 = {{$item.sha256}}
       size_bytes = {{$item.file_size_bytes}}

    2. **Phase 5 활성 전 (dry-run)**:
       알림 표시 "[DRY-RUN] 삭제 예정: {asset_id}"
       매크로 #3 호출 (success=false, reason="dry_run")

    3. **Phase 5 활성 후 (실삭제)**:
       a. MediaStore 조회: filename = {{$asset_id}}.{ext}
          → File URI 획득
       b. File Operations → Delete File (URI)
          → 결과 변수 deletion_ok
       c. MEDIA_SCANNER broadcast (Galaxy Photos 갱신)
       d. 매크로 #3 호출 (success={{$deletion_ok}})
  EndLoop
  알림 "정리 완료: {{$items_count}}장"
```

### 매크로 #3: Cleanup Result POST (감사)

```
이름: Photo Cleanup Result Reporter
트리거: 매크로 #2에서 호출
액션:
  HTTP Request POST
    URL: https://photo.jwcloud.my/cleanup-api/cleanup_result
    Headers: Content-Type: application/json
    Body:
      {
        "asset_id": "{{$asset_id}}",
        "immich_id": "{{$immich_id}}",
        "device": "galaxy-eunju",
        "success": {{$deletion_ok}},
        "reason": "{{$reason}}",
        "reclaimed_bytes": {{$size_bytes}},
        "device_deleted_at": "{{ISO_DATETIME}}"
      }
```

### 매크로 #4: Backup Restore (♥ 자산 다운로드)

```
이름: Photo Backup Restore
트리거: 매크로 #2 완료 직후 (또는 별도 시간)
액션:
  1. HTTP Request GET
     URL: https://photo.jwcloud.my/api/albums?albumName=◆ MEMORY+
     → ♥ + MEMORY+ 자산 ID 목록 획득
  2. Loop:
     - GET /api/assets/{asset_id}/download
     - Save to /sdcard/DCIM/PhotoSystemBackup/
  3. MEDIA_SCANNER broadcast → Galaxy Cloud 자동 동기화
```

## 다층 안전 메커니즘 (jw.son iPhone과 동일)

| 게이트 | 위치 | 동작 |
|---|---|---|
| **3중 백업 검증** | classify-service `/verify_backup` | DB sha256 + 파일 + 실 SHA256 + Immich 등록 모두 PASS 시에만 cleanup_candidates에 포함 |
| **14일 등급 안정화** | `cleanup_candidates(min_age_days=14)` | 분류 직후 자산 보호 |
| **단계적 limit** | progressive=true | 1주차 20장 / 2주차 100장 / 3주차+ 200장 |
| **사용자 보호 표시** | `photo.feedback feedback_type='protect'` | 표시 자산 cleanup_candidates 자동 제외 |
| **Galaxy 휴지통** | Samsung Gallery 30일 보관 | 즉시 복구 가능 |
| **dry-run 14일** | 매크로 #2 [알림] 단계 | 실삭제 활성 전 검토 |

## 자동화 트리거 등록

```
MacroDroid 앱:
  Macros 탭 → + 추가
  Trigger: Time/Date → 매일 04:00
  Constraints: Charging + Battery ≥ 80% (Wi-Fi 조건 제외)
  Actions: Run Macro "Photo Cleanup Trigger (eunju)"
```

## 검증 시나리오 (Phase 5 진입 전)

1. dry-run 모드로 7일 실행 → 매일 알림으로 매칭 자산 수 확인
2. cleanup_audit table에서 dry-run 결과 누적 확인 (`device='galaxy-eunju'`)
3. Galaxy Cloud / Immich 자산 수 일치 검증
4. 사용자가 보호하고 싶은 사진 1~2장 → POST /feedback/protect → 7일 후 dry-run에서 미포함 확인
5. Phase 5 활성 승인 → 매크로 #2의 [알림] → [Delete File] 활성

## 롤백

문제 발생 시:
1. MacroDroid → 해당 매크로 비활성화
2. Galaxy Gallery → 휴지통에서 사진 복구 (30일 이내)
3. classify-service 로그 확인: `docker logs photo-classify --tail 50`
4. cleanup_audit table 조회: `SELECT * FROM photo.cleanup_audit WHERE device='galaxy-eunju' AND success=false LIMIT 20;`

## 관련 문서

- `runbooks/layer6_ios_shortcut.md` — jw.son iPhone 동일 흐름
- `wiki/03-pdca/active/report/TC-phase5-backup-verifier.md` — 검증 게이트 TC
- `runbooks/cloudflare_external_classify.md` — `/cleanup-api/*` 외부 노출 설정
