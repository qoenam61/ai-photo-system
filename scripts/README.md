# Scripts

운영·마이그레이션·복구 스크립트. Phase별로 추가.

## 작성 예정 Scripts

### Phase 0
| 파일 | 설명 |
|---|---|
| `phase0_inventory.sh` | 사진 총 용량·HEIC 비율·SSD 가용량 측정 |

### Phase 0-LLM
| 파일 | 설명 |
|---|---|
| `phase0_llm_install.sh` | Ollama + Qwen2.5-VL 7B + Whisper-small 설치 |
| `phase0_llm_benchmark.py` | 100장 정확도·속도 측정 |

### Phase 3 (마이그레이션)
| 파일 | 설명 |
|---|---|
| `osxphotos_export.sh` | iPhone iCloud → SSD vault export |
| `galaxy_extract.sh` | Galaxy USB MTP → SSD vault |
| `phase3_convert_batch.sh` | 일괄 Layer 0.5 변환 (4 worker) |

### Phase 6 (HDD 마이그레이션)
| 파일 | 설명 |
|---|---|
| `migrate_paths.sh` | SSD → HDD 마이그레이션 + originalPath 일괄 치환 |
| `verify_migration.sh` | SHA256 + 무작위 50장 검증 |

### Phase 7 (운영)
| 파일 | 설명 |
|---|---|
| `rollback.sh` | 이미지 tag 기반 즉시 롤백 |
| `reconcile.sh` | 주간 FS↔DB 일치 검증 |
| `ccc_clone.sh` | 주간 시스템 클론 (Carbon Copy Cloner CLI) |
| `deploy-verify.sh` | 배포 후 검증 (SDLC deploy-protocol.md 준수) |

모든 스크립트는 SDLC sdlc-core.md TC-First 원칙 준수. 도메인 안전 영역(사진 삭제·HDD)은 정식 TC 파일 필수.
