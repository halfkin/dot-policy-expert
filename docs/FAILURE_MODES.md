# Failure Mode Catalog

How Dot fails, what the user sees, and what to do about it.

## Runtime Failures

| Failure Mode | User Sees | Root Cause | Operator Action |
|---|---|---|---|
| OpenRouter API down | Offline-quality answers (template-based, no synthesis) | Upstream provider outage | Monitor; auto-fallback to offline mode works automatically |
| Lakera API down | Ravelin Layer 3 skipped, Layer 2 regex still active | Upstream provider outage | Fail-open by design — legitimate questions pass, only LLM consensus layer is lost |
| Embedding model fails to load | Keyword-only retrieval (lower recall on paraphrased queries) | Missing `sentence-transformers` dependency or corrupt model cache | Check install: `pip install sentence-transformers`; delete `~/.cache/huggingface` and restart |
| Rate limit hit | "Too many requests. Please wait a moment." | Burst traffic from single IP (>20/min) | Adjust `slowapi` limit in `app.py` or add IP allowlisting for trusted clients |
| `.env` not loaded | Server starts in offline mode; no LLM synthesis, no query reformulation | `python-dotenv` not loading, or server started from wrong directory | Run `source .env` before starting, or use `run.sh` |

## Retrieval Failures

| Failure Mode | User Sees | Root Cause | Operator Action |
|---|---|---|---|
| No chunks above threshold | "Not in sources." with suggestions | Query too vague or topic genuinely not in KB | Check suggestions — if relevant docs exist, lower threshold or improve chunking |
| Wrong chunks ranked highest | Incorrect or partially relevant answer | Keyword/embedding blend not tuned for this query type | Review retrieval trace in eval output; consider adjusting blend weights or adding synonym expansion |
| Single-word query misses relevant docs | "Not in sources." or partial answer | Too few tokens for embedding similarity to differentiate | Query reformulation (LLM mode) mitigates this; offline mode remains vulnerable |
| Multi-intent query only answers one part | Partial answer covering 1 of 2+ topics | Top-k chunks all come from same document | Doc diversity selection mitigates this; increase `top_k` for complex queries |

## Answer Generation Failures

| Failure Mode | User Sees | Root Cause | Operator Action |
|---|---|---|---|
| Citation dump instead of synthesis | Raw chunk text listed instead of natural answer | System prompt not loaded or LLM ignoring synthesis instruction | Verify system prompt in `app.py`; check that LLM mode is active |
| Hallucinated answer (not grounded in chunks) | Answer that doesn't match any KB content | LLM using outside knowledge despite instruction | Review system prompt grounding rules; add eval question to catch this pattern |
| Conflict not flagged | Normal answer when sources contradict | Conflict detector didn't find numeric/factual mismatch | Check conflict detector thresholds; add explicit conflict cues to detection |
| False conflict triggered | "Conflicting information" on a non-conflict question | Conflict detector over-matched on similar numbers | Review conflict gating logic; ensure tier-specific questions are exempt |

## Security Failures

| Failure Mode | User Sees | Root Cause | Operator Action |
|---|---|---|---|
| Prompt injection succeeds | LLM follows injected instruction | Ravelin layers all bypassed | Review failed input; add pattern to Layer 2 regex or retrain Layer 3 |
| Legitimate question blocked | "I can't process that request" on a normal question | Ravelin false positive (Layer 2 regex too broad or Layer 3 classifiers disagree) | Check which layer blocked; adjust regex pattern or consensus threshold |
| Oversized input crashes server | 500 error | Input validation not reached | Verify `MAX_INPUT_LENGTH` check runs before any processing |

## Infrastructure Failures

| Failure Mode | User Sees | Root Cause | Operator Action |
|---|---|---|---|
| Docker container won't start | Service unavailable | Missing dependency, port conflict, or model download failure | Check `docker compose logs`; ensure Dockerfile pre-downloads embedding model |
| Eval results not reproducible | Different pass rates on same questions | Mode/pipeline/config mismatch between runs | Compare fingerprints — commit hash, mode, pipeline, KB hash, blend weights must all match |
| Feedback not logging | Thumbs up/down clicks silently fail | `logs/` directory missing or permissions issue | Create `logs/` directory; check write permissions |

## Diagnosis Workflow

When something fails:

1. Check the **failure_bucket** in the response — this tells you which stage failed
2. If `retrieval_failed` → check retrieval trace for what chunks were found and their scores
3. If `generation_failure` → the right chunks were found but the LLM answered wrong — check the system prompt
4. If `prompt_injection_blocked` → check which Ravelin layer triggered and whether it's a true or false positive
5. If `conflict_in_sources` → verify both conflicting sources and whether the conflict is real
6. Run the eval suite with `--request-delay-seconds 3.5` to get a full diagnostic across all 75 questions
