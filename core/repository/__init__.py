"""Repository layer — DB 접근 표준 (Repository 패턴).

설계: architecture_review.md §9.4
- classification_repo.py: photo_classification CRUD + UPSERT
- conversion_repo.py: photo_conversion_log
- feedback_repo.py: photo_feedback
- queue_repo.py: cleanup_queue, cloud_sync_queue
- outbox_repo.py: Outbox pattern (Layer 5)
- archive_repo.py: 1년+ archiving
"""
