"""Pipeline layer — 8레이어 (얇은 orchestration).

설계 §5 전체 파이프라인 + architecture_review.md §9.4
- layer0_upload.py: Immich Webhook 수신
- layer05_convert.py: 미디어 변환
- layer1_preprocess.py: 전처리 (CLIP, OpenCV)
- layer2_content.py: 콘텐츠 분석 (Qwen2.5-VL)
- layer3_grade.py: 등급 판정
- layer4_local_llm.py: Vision 보조 재분류
- layer5_album.py: 앨범 배정
- layer6_cleanup.py: 기기 정리
- layer7_feedback.py: 검증·피드백
"""
