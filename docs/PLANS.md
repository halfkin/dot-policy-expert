# Dot - Verification & Cleanup Plan

## Assumptions & Risks
- Keys remain unrotated during verification and will be rotated after final GitHub push.
- LLM-provider outages are handled with soft-skip plus captured evidence.
- `sentence-transformers` can fail to initialize on some hosts; fallback embedding mode changes retrieval quality and should be treated as a risk, not silent pass.
- Rate limiting can distort eval outcomes unless `--request-delay-seconds` is used.
- Local path assumptions in docs/scripts can break cross-machine reproducibility.
- Eval outputs are schema-fragmented across tools (`run_evals.py` vs `verify_advanced.py`), so milestone checks use both artifacts.

## Milestone 1: Environment & Config Verification
### Files to inspect
- `.env`
- `.env.example`
- `.gitignore`
- `requirements.txt`
- `backend/app.py`
- `backend/embedder.py`

### Commands to run
- `.venv/bin/python` checks for env parity and blend sum.
- `rg` secret scan over tracked files (excluding `.env`).
- Dependency/import audit.
- Startup checks (offline + llm when reachable) and `/health`.

### Expected outputs
- Blend weights sum to `1.0`.
- `.env.example` structure matches runtime-required keys with placeholders/defaults.
- `.gitignore` protects `.env`, `logs/`, `.venv/`, `__pycache__/`.
- No hardcoded secrets in tracked code/docs.
- Startup logs show embedding dimensions and blend weights.

### Pass criteria
- Passed.
- Notes: LLM-mode checks were executed with live keys available; no soft-skip required during Milestone 1 run.

### Rollback notes
- N/A (verification-only).

## Milestone 2: Pipeline Integrity (Per Component)
### Files to inspect
- `backend/app.py`
- `backend/ravelin.py`
- `backend/conflict_detector.py`
- `backend/query_reformulator.py`
- `backend/embedder.py`
- `tests/test_ravelin.py`
- `tests/test_conflict_detector.py`

### Commands to run
- `PYTHONPATH=. ./.venv/bin/pytest -q`
- Focused endpoint probes for behavior buckets.

### Expected outputs
- All tests green.
- Prompt injection blocked.
- Conflict detector catches cross/within-document contradictions.
- Input validation, language detection, confidence mapping, feedback logging, and rate limiting behave correctly.

### Pass criteria
- Passed.
- Fix applied: `backend/conflict_detector.py` updated so generic refund-window questions trigger within-doc conflict scanning while tier-specific questions remain exempt.
- Result: `test_detects_within_doc_conflict_for_single_metric_question` now passes.

### Rollback notes
- If regression appears, revert only `backend/conflict_detector.py` hunk touching refund gating and re-run targeted test.

## Milestone 3: Frontend Verification
### Files to inspect
- `frontend/index.html`

### Commands to run
- Browser automation checks (Playwright) against local FastAPI.

### Expected outputs
- Correct rendering for normal/not_in_sources/blocked/conflict/unsupported_language/empty_input.
- Citations expand/collapse.
- Confidence and response time display.
- Suggestions, feedback controls, history, keyboard behavior, scroll, and mode badge work.

### Pass criteria
- Passed after fix.
- Fix applied: added missing badge mappings for `empty_input`, `input_too_long`, `rate_limited`.
- Result: frontend suite passed `20/20`.

### Rollback notes
- If badge rendering regresses, restore status-map additions in `frontend/index.html`.

## Milestone 4: Eval Suite Integrity
### Files to inspect
- `evals/questions.json`
- `evals/run_evals.py`
- `evals/verify_advanced.py`
- `evals/results/*.json`

### Commands to run
- `PYTHONPATH=. ./.venv/bin/python evals/run_evals.py --inprocess --skip-judge`
- HTTP run of `evals/run_evals.py`
- `verify_advanced.py` for both `--pipeline inprocess` and `--pipeline http`

### Expected outputs
- 75 questions, IDs 1..75, required fields, required categories.
- Expected behavior branches covered.
- Fingerprint contains commit/mode/pipeline/KB hash/questions hash/thresholds/embedding model/blend weights.
- Per-question trace includes retrieval query + retrieved/selected chunks plus decided behavior and failure bucket.

### Pass criteria
- Passed.
- `evals/verify_advanced.py` enhanced with:
- `kb_sha256`
- embedding model metadata (`name`, `dimensions`, `using_sentence_transformer`, `model_load_error`)
- `run_evals.py` explicitly handles additional disallowed buckets (`needs_clarification`, `empty_input`, `input_too_long`, `rate_limited`) in answer expectations.
- Verification outputs:
- `verify-advanced-offline-inprocess-m4.json` (temporary verification artifact) -> 22/27 (81.5%)
- `verify-advanced-offline-http-m4.json` (temporary verification artifact) -> 25/27 (92.6%)
- Canary guard passed in both.

### Rollback notes
- Revert eval script changes if downstream consumers depend on older schema/diagnostics behavior.

## Milestone 5: Docker Verification
### Files to inspect
- `Dockerfile`
- `docker-compose.yml`

### Commands to run
- `docker compose build`
- `docker compose up -d`
- `curl -s http://127.0.0.1:8000/health`
- `/chat` probes for normal/injection/conflict/non-English/empty
- `docker compose down`

### Expected outputs
- Build succeeds.
- Container serves healthy app.
- Startup logs show real embeddings and blend configuration.
- Runtime buckets match expected behavior.

### Pass criteria
- Passed.
- Startup log evidence included:
- `Embedding model: all-MiniLM-L6-v2 (384 dimensions)`
- `Retrieval blend weights: keyword=0.4, semantic=0.6`
- Runtime probes passed for all required behavior buckets.

### Rollback notes
- `docker compose down` already executed and cleanup confirmed.

## Milestone 6: README & Repo Polish
### Files to inspect
- `README.md`
- `.gitignore`
- repo root hygiene (`.DS_Store`, transient outputs)

### Commands to run
- README section check by inspection.
- Marker scan command (excluding eval result payloads).
- `git ls-files .env`
- `git log --oneline -n 12`

### Expected outputs
- README contains all required portfolio sections.
- No residual source markers.
- `.env` not tracked.
- Cleaner default ignore behavior for transient local artifacts.

### Pass criteria
- Passed.
- Applied edits:
- Added architecture diagram section.
- Added explicit failure-analysis subsection.
- Updated quick-start paths to current workspace root.
- Renamed future section to `What I'd Add Next`.
- Added `Author` section.
- Updated `.gitignore` to include `.DS_Store` and `output/`.
- Removed tracked `.DS_Store` files from repository index.

### Rollback notes
- README/.gitignore edits are isolated and reversible without affecting runtime behavior.

## Passover Checklist

| # | What | How | Expected | Pass? |
|---|------|-----|----------|-------|
| 1 | Grounding: factual answers cite KB chunks | POST `/chat` direct retrieval prompt | `citations` non-empty | PASS |
| 2 | Unknown: out-of-KB -> `Not in sources.` | POST off-topic question | answer starts with exact prefix | PASS |
| 3 | Safety: injection blocked | POST jailbreak prompt | `failure_bucket=prompt_injection_blocked` | PASS |
| 4 | Conflict: contradictions flagged | POST data-deletion question | `failure_bucket=conflict_in_sources` with dual evidence | PASS |
| 5 | Empty input handled | POST whitespace-only question | graceful response, no crash | PASS |
| 6 | Oversized input rejected | POST >10k characters | `input_too_long` or blocked | PASS |
| 7 | Non-English detected | POST French question | `failure_bucket=unsupported_language` | PASS |
| 8 | Follow-up works (LLM mode) | UI follow-up sequence | second answer uses prior context | PASS |
| 9 | Confidence populated | POST direct prompt | `confidence` in `high/medium/low` | PASS |
| 10 | Response-time populated | UI/API response metadata check | numeric response time shown | PASS |
| 11 | Suggestions on not_in_sources | POST off-topic question | suggestions array with doc/heading | PASS |
| 12 | Feedback logging | POST `/feedback` then inspect log | line appended to `logs/feedback.jsonl` | PASS |
| 13 | Rate limiting active | burst `/chat` requests | 429 after threshold | PASS |
| 14 | Embeddings active | startup logs | MiniLM `384 dimensions` line present | PASS |
| 15 | Blend weights correct | startup logs | `keyword=0.4, semantic=0.6` | PASS |
| 16 | No secrets in repo | `rg` secret patterns over tracked files | no key leaks in tracked code/docs | PASS |
| 17 | Docker works | `docker compose build/up` + probes | app healthy and behavior buckets correct | PASS |
| 18 | Eval suite runs | run `evals/run_evals.py` | completes with summary and results JSON | PASS |
| 19 | 75 questions present | parse `evals/questions.json` | count=75, IDs 1..75, unique | PASS |
| 20 | README completeness | manual section checklist | required portfolio sections present | PASS (after edits) |
| 21 | `run_evals.py` behavior contracts | inspect + execute | supports answer/not_in_sources/blocked/conflict | PASS |
| 22 | Failure bucket handling coverage | inspect eval logic | includes not_in_sources, blocked, conflict, unsupported_language, empty_input, input_too_long, rate_limited | PASS |
| 23 | Inprocess + HTTP pipeline support | run both pipelines | both complete without schema break | PASS |
| 24 | Fingerprint integrity | inspect verify outputs | commit/mode/pipeline/KB hash/questions hash/threshold/blend/embedding present | PASS |
| 25 | Per-question trace integrity | inspect verify results rows | `trace.retrieval_query`, `trace.retrieved`, `decided_behavior`, `failure_bucket` present | PASS |
| 26 | PromptArmor rename completeness | `rg` active paths | no active `PromptArmor/promptarmor` refs | PASS |
| 27 | `.env` not tracked | `git ls-files .env` | no output | PASS |
| 28 | Marker residue | marker scan over source/docs | no hits in active code/docs | PASS |
| 29 | Scratch artifact policy | inspect untracked dirs | transient output ignored by default | PASS (ignore rule added) |
