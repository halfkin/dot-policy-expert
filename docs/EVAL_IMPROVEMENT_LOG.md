# Eval Improvement Log: 81% → 91.4%

**Branches:** `fix/conflict-detection-multilingual` → `feat/llm-conflict-verifier`
**Date:** 2026-02-26
**Baseline:** 47/58 (81.0%) — commit `9658cc0`
**Phase 3 Final:** 52/58 (89.7%) — commit `e96df45`
**Phase 4 Final:** 53/58 (91.4%) — commit `d63a503`

---

## Category Scores

| Category | Baseline (81%) | Phase 3 (89.7%) | Phase 4 (91.4%) | Net Change |
|----------|----------------|-----------------|-----------------|------------|
| Direct retrieval | 73.3% (11/15) | **100% (15/15)** | **100% (15/15)** | +4 |
| Cross-document | 87.5% (7/8) | **100% (8/8)** | **100% (8/8)** | +1 |
| Adversarial | 100% (7/7) | **100% (7/7)** | **100% (7/7)** | — |
| Multilingual | 100% (4/4) | **100% (4/4)** | 75% (3/4) | -1 |
| Paraphrased | 100% (5/5) | **100% (5/5)** | 80% (4/5) | -1 |
| Not in sources | 66.7% (2/3) | **100% (3/3)** | **100% (3/3)** | +1 |
| Reasoning | 100% (3/3) | **100% (3/3)** | **100% (3/3)** | — |
| Edge case | 100% (8/8) | 87.5% (7/8) | 87.5% (7/8) | -1 |
| Conflict detection | 0% (0/5) | 0% (0/5) | **60% (3/5)** | +3 |

6 of 9 categories at 100%. Conflict detection moved from 0% to 60%.

---

## What Changed

### Phase 1: Multilingual Regex (`aa0f942`)

**File:** `backend/app.py`

**Problem:** The `HAS_LANGDETECT` fallback regex in `check_language()` was too narrow. French questions with words like "est-ce", "quelle", "rgpd", "conforme" fell through as English. German had no regex at all.

**Fix:**
- Expanded the French regex with common stopwords and content words
- Added a German regex block so German queries detect as `"de"` and get rejected as `unsupported_language` (German is not in `SUPPORTED_LANGUAGES`)

**Tests fixed:** ML-03 (French RGPD question), ML-04 (German refund question)

### Phase 2: Tier-Aware Conflict Detection (`72139c5`)

**File:** `backend/conflict_detector.py`

**Problem:** The conflict detector couldn't distinguish "two chunks about different plan tiers with different numbers" (not a conflict) from "two chunks about the same thing with different numbers" (real conflict). This caused DR-08, DR-10, CD-01, PP-02 to false-positive as `conflict_in_sources`.

**Fix:**
- Removed tier-discriminating words (`plan`, `plans`, `account`, `accounts`, `tier`, `tiers`) from `CONTEXT_STOPWORDS` so Jaccard similarity can see them
- Added `tier: str | None` field to the `Fact` dataclass
- Added tier bypass in `_has_contextual_conflict()`: if both facts have different tiers, skip the comparison

### Phase 3: Heading-Based Tier Extraction (`def8273`)

**Files:** `backend/conflict_detector.py`, `backend/app.py`

**Problem:** Phase 2's per-number window tier scanning (50 chars around each number) was fragile. Numbers far from tier keywords got `tier=None`, bypassing the tier guard. "business days" falsely matched as the Business tier. Section headings like "Business Plan Features" were 300+ chars from the actual numbers.

**Key insight:** Every chunk already carries `heading` and `doc_title` metadata from indexing. Headings like "Pro Plan Support" or "Business Plan Features" contain the tier. Extract tier from the chunk's heading once, and every Fact from that chunk inherits it.

**Fix:**
- Added `_chunk_tier(chunk)` helper that extracts tier from chunk heading/doc_title using word-boundary regex (avoids "pro" matching "product")
- Changed `_extract_fact_objects()` to accept `chunk_tier` parameter — all facts inherit the chunk's tier
- Updated `_detect_pair_conflict()` to extract tier from chunk metadata and pass it through
- Passed `heading` and `doc_title` through the conflict candidate pool in `app.py`
- Deleted `_is_tier_specific_refund_window_question` and its calls (was blocking real conflicts)
- Fixed `_looks_multi_part_question` to require actual question-word clauses on both sides of "and" (was blocking CF-03 because "customer **and** I purchased" triggered the gate)
- Increased context radius from 70 to 100 tokens

**Tests fixed:** DR-08, DR-10, CD-01, PP-02 (false positives eliminated), NIS-01 (student discount)

### Phase 4: LLM-Verified Conflict Detection (`d63a503`)

**File:** `backend/conflict_detector.py`

**Problem:** All 5 conflict detection tests (CF-01 through CF-05) failed because real conflicts have Jaccard similarity of 0.03–0.06 — far below the 0.2 confirmation threshold. Lowering the threshold creates false positives. The vocabulary is too different for token overlap to work.

**Key insight:** Use an LLM as a final-stage verifier. Cheap checks first (regex + Jaccard), expensive LLM only when regex found candidate pairs with different numeric values but Jaccard couldn't confirm. Same tiered cost philosophy as the Ravelin role-play detection.

**Architecture (three tiers):**
1. **Fast path:** Jaccard ≥ 0.2 confirms conflict immediately (unchanged)
2. **Tier pre-filter:** `_question_tier()` extracts tier from user's question, `_snippet_tier()` detects tier in each fact's context window. Cross-tier pairs are skipped. Question-tier filtering narrows facts to only those relevant to the asked-about tier.
3. **LLM verification:** `_llm_verify_chunk_conflict()` sends full chunk text (up to 600 chars each) + user question to GPT-4o-mini via OpenRouter. Binary yes/no — "Is there a DIRECT CONTRADICTION relevant to the user's question?"

**Implementation details:**
- `_pair_has_numeric_disagreement(chunk_a, chunk_b, qtier)` — pre-screens chunk pairs for same-kind facts with different values, applying tier filtering at both chunk-heading and snippet level
- `_llm_verify_chunk_conflict(text_a, text_b, question)` — OpenRouter call, temperature 0.0, max_tokens 5, 10s timeout
- Fail-open: LLM errors → no conflict flagged, logged as `CONFLICT_LLM_VERIFY_FAILED`
- Gated by `USE_LLM=1` env var and non-empty `OPENROUTER_API_KEY`
- LLM prompt includes concrete examples of what IS and ISN'T a contradiction (different tiers ≠ conflict, different policies ≠ conflict)

**Prompt engineering journey (5 iterations):**
1. Inner-loop "same metric?" prompt → 8 new false positives (47/58)
2. Question-aware snippet prompt → still too aggressive (47/58)
3. Full chunk text at top level → right composition but new regressions (52/58)
4. Added tier pre-filtering → fixed DR-12 but broke CF-03 with `break` (mixed)
5. Snippet-level tier exclusion + concrete contradiction examples → **53/58 stable**

**Tests fixed:** CF-01 (Pro uptime 99.9% vs 99.99%), CF-04 (data deletion 45 days vs 30 days), CF-05 (cross-plan uptime guarantees)

**Regressions introduced:** ML-01 (French refund question triggers LLM false positive on 14-day vs 30-day refund chunks), PP-02 (account lockout question triggers LLM false positive on deletion/reactivation chunks)

---

## Remaining Failures (5)

### Conflict Detection False Negatives (CF-02, CF-03)

Two conflict tests still fail. The LLM catches the obvious conflicts (CF-01, CF-04, CF-05) but misses these:

- **CF-02:** "Our Business plan SLA says 99.95% but your marketing says 99.99%. Which is correct?" — The promo chunk sometimes doesn't get retrieved alongside the SLA chunk. When both are present, the LLM is non-deterministic about calling this a contradiction (the promo explicitly upgrades all tiers, which could be read as superseding rather than contradicting).
- **CF-03:** "I'm an Enterprise customer and I purchased 20 days ago. Can I still get a full refund?" — The 30-day Enterprise Satisfaction Guarantee vs 14-day standard window. The tier filtering correctly narrows to Enterprise facts, but the 14-day fact doesn't mention "Enterprise" in its snippet, so it gets filtered out before the LLM sees it.

### LLM False Positives (ML-01, PP-02)

- **ML-01:** French refund question "Quelle est la politique de remboursement?" — Standard 14-day eligibility chunk vs 30-day automated processing cutoff chunk. These are different policies (eligibility vs processing) but the LLM sees "14 days" vs "30 days" in refund context and calls it a contradiction.
- **PP-02:** "My boss is locked out, how do we fix this?" — Account deletion (45-day scrubbing) vs account reactivation (90-day window). Different processes, but LLM intermittently flags as contradictory.

### Edge Case (EC-06)

EC-06 "I deleted my account 3 days ago. Can I recover it?" — Still intermittently returns `conflict_in_sources`. Same root cause as before (Jaccard borderline) now compounded by LLM occasionally agreeing with the false positive.

---

## Commits

| Commit | Message |
|--------|---------|
| `aa0f942` | fix(lang): expand French regex, add German detection for ML-03/ML-04 |
| `72139c5` | fix(conflict): add tier-awareness to prevent false positives on cross-tier facts |
| `def8273` | fix(conflict): heading-based tier extraction + remove tier-refund bypass |
| `e96df45` | eval: 89.7% (52/58) — heading-based tier approach |
| `d63a503` | feat(conflict): add LLM-verified conflict detection for low-Jaccard pairs |
