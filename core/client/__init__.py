"""Client layer — 외부 시스템 wrapper.

설계: architecture_review.md §9.4
- immich_client.py: Immich API (assets, albums, exif)
- ollama_client.py: Ollama API + 프롬프트 로딩 (prompts/*.md)
- tailscale_client.py: ACL 관리
- notifier.py: Telegram + Mac push 통합
"""
