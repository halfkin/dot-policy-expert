# Progress — Dot Policy Chatbot

## Current State (2026-02-26)
- **Eval:** 54/58 (93.1%) on Loomo KB
- **Branch:** chore/codebase-cleanup
- **Last major work:** Full codebase cleanup — module split, eval consolidation, env var extraction, deployment config

## Remaining Eval Failures
- CF-02 (retrieval gap), CF-03 (tier filtering), EC-06 (intermittent), 1 multilingual edge case

## What's Next
- VPS migration (n8n self-hosted + Dot deployment)
- Portfolio packaging (LinkedIn, resume, demo video)
- API key rotation

## Recent Changelog
- Codebase cleanup: module split (1326→793 lines), eval consolidation, env var extraction, deployment config
- Phase 5: Chain-of-thought conflict prompt (93.1%, 54/58)
- Phase 4: LLM conflict verifier (91.4%, 53/58)
- Phase 3: Heading-based tier extraction (89.7%, 52/58)
- Phase 2: Tier-aware conflict detection (85%)
- Phase 1: Multilingual regex expansion (83%)
