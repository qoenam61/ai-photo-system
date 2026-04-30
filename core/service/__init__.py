"""Service layer — 도메인 로직.

설계: architecture_review.md §9.4
- metadata_service.py: EXIF/GPS/시각/timezone 추출·검증
- conversion_service.py: HEIC→JPEG, HEVC→H.264 (ffmpeg, sips)
- similarity_service.py: CLIP cosine, pHash, 그룹핑
- grading_service.py: 8등급 판정 (점수 가산제, domain.grade 사용)
- album_service.py: Immich 앨범 + 공유 EVENT 매칭
- storage_service.py: HDD 등급 폴더 이동 + 뷰 심볼릭 (옵션 D, v3.7)
- cleanup_service.py: 24h grace, cleanup_queue 관리
- cloud_sync_service.py: iCloud/Galaxy Cloud 검증
- llm_service.py: Qwen2.5-VL 호출 추상 (§15 확장 통합)
"""

from core.service.storage_service import StorageService

__all__ = ["StorageService"]
