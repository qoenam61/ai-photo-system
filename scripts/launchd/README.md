# launchd 설정 — Mac 자동 정리

## com.photo.cleanup-mac.plist

매일 04:15 KST 실행 — `cleanup_photos_mac.py`가 Photos.app TRASH 자산 정리.

### 설치

```bash
cp scripts/launchd/com.photo.cleanup-mac.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.photo.cleanup-mac.plist
launchctl list | grep com.photo.cleanup-mac
```

### 정지

```bash
launchctl unload -w ~/Library/LaunchAgents/com.photo.cleanup-mac.plist
```

### 수동 실행

```bash
launchctl start com.photo.cleanup-mac
```

### 권한 (첫 실행 시)

시스템 설정 → 개인정보 보호 및 보안 → 자동화 → osascript → 사진 ON

### 로그

`scripts/_inventory/cleanup_photos_mac.log` (성공 기록)
`scripts/_inventory/cleanup_photos_mac.stderr` (에러 기록)
