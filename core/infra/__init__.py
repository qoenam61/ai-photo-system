"""Infrastructure layer — cross-cutting (모든 레이어에서 사용).

설계: architecture_review.md §9.4
- logger.py: JSON 로그 + trace_id 전파 (structlog)
- error_handler.py: 표준 에러 분류 (E_CONVERT_FAIL_DECODE 등)
- retry.py: exp backoff + circuit breaker (tenacity 기반)
- queue.py: Redis Streams 추상
- lock.py: Postgres advisory lock
- healthcheck.py: 컨테이너 healthcheck
- metrics.py: Prometheus exporter (선택)
"""
