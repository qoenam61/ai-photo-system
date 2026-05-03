# Classify-service 외부 노출 — Cloudflare 터널 경유

iPhone iOS Shortcut에서 LTE 외부망에서도 cleanup_candidates 등을 호출하려면
Cloudflare Tunnel의 origin을 immich-server에서 immich-https(Caddy)로 변경.

Caddy가 path 기반으로 route:
- `/cleanup-api/*` → photo-classify:8000 (path 제거)
- 그 외 → immich-server:2283

## 사용자 측 1회 작업 (Cloudflare Dashboard)

1. https://one.dash.cloudflare.com → Networks → Tunnels
2. 사용 중 tunnel (token 9c88fe5d-...) 클릭
3. Public Hostname 탭
4. `photo.jwcloud.my` 호스트의 **Service** 수정:
   - 기존: `HTTP://immich-server:2283`
   - 변경: `HTTP://immich-https:2283`
5. 저장 → 30초 후 적용

## 검증

```bash
# 외부에서 cleanup-api 도달 확인
curl https://photo.jwcloud.my/cleanup-api/health
# → {"ok": true, "policy": "v3.12 ..."}

# 기존 immich 동작도 유지
curl https://photo.jwcloud.my/api/server/ping
# → {"res": "pong"}
```

## iOS Shortcut에서 사용

```
URL: https://photo.jwcloud.my/cleanup-api/cleanup_candidates?grades=NORMAL,TRASH,FOOD&min_age_days=14
Method: GET
(인증 없음 — classify-service는 LAN 가정. Phase 5 활성 직전 API key 추가 권장)
```

## 보안 강화 (다음 단계)

Phase 5 실삭제 활성 전:

1. classify-service에 X-API-Key 헤더 검증 추가
2. .env에 CLEANUP_API_KEY=<random 32-byte>
3. iOS Shortcut Headers에 `x-api-key: $CLEANUP_API_KEY` 추가
4. Cloudflare Access 정책 (선택) — Google 계정 기반 외부 접근 제어

## 롤백

문제 발생 시 Cloudflare Dashboard에서:
- Service URL → `HTTP://immich-server:2283` 로 되돌리면 즉시 복구
- Caddy 컨테이너 stop: `docker compose stop immich-https`
