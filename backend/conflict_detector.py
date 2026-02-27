from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip()
_USE_LLM = os.getenv("USE_LLM", "0") == "1"

CONTEXT_STOPWORDS = {
    "the",
    "and",
    "for",
    "are",
    "is",
    "to",
    "in",
    "of",
    "a",
    "that",
    "it",
    "was",
    "this",
    "with",
    "from",
    "within",
    "into",
    "over",
    "under",
    "after",
    "before",
    "during",
    "customer",
    "customers",
    "employee",
    "employees",
    "policy",
}

DURATION_UNITS = "days?|hours?|minutes?|weeks?|months?|years?"
WORD_NUMBERS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}
TIER_TOKENS = {"standard", "pro", "business", "enterprise"}


def _chunk_tier(chunk: dict) -> str | None:
    """Extract plan tier from chunk heading/title metadata."""
    text = f"{chunk.get('heading', '')} {chunk.get('doc_title', '')}".lower()
    for tier in TIER_TOKENS:
        if re.search(rf"\b{tier}\b", text):
            return tier
    return None


@dataclass
class Fact:
    value: str
    kind: str
    context: set[str]
    tier: str | None = None
    raw_snippet: str = ""


def extract_numeric_facts(text: str) -> set[str]:
    patterns = [
        r"\$[\d,]+(?:\.\d+)?",
        r"\d+\.?\d*%",
        rf"\d+\.?\d*[-\s]*(?:{DURATION_UNITS})",
        rf"(?:{'|'.join(WORD_NUMBERS.keys())})\s+(?:{DURATION_UNITS})",
        r"\d+",
    ]
    facts = set()
    lower = (text or "").lower()
    for pattern in patterns:
        for match in re.findall(pattern, lower):
            facts.add(_normalize_fact(match))
    return facts


def _normalize_fact(raw: str) -> str:
    value = raw.lower().strip()
    value = value.replace(",", "")
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"(\d)\s*-\s*([a-z])", r"\1 \2", value)
    for word, num in WORD_NUMBERS.items():
        value = re.sub(rf"\b{word}\b", num, value)
    return value


def _window_context_tokens(text: str, start: int, end: int, radius: int = 100) -> set[str]:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = text[left:right].lower()
    tokens = re.findall(r"[a-z0-9]+", snippet)
    return {t for t in tokens if len(t) > 2 and t not in CONTEXT_STOPWORDS}


def _extract_fact_objects(text: str, chunk_tier: str | None = None) -> dict[str, list[Fact]]:
    source = text or ""
    lower = source.lower()
    patterns = [
        ("money", r"\$[\d,]+(?:\.\d+)?"),
        ("percent", r"\d+\.?\d*%"),
        ("duration", rf"\d+\.?\d*[-\s]*(?:{DURATION_UNITS})"),
        ("duration", rf"(?:{'|'.join(WORD_NUMBERS.keys())})\s+(?:{DURATION_UNITS})"),
    ]
    out: dict[str, list[Fact]] = {"money": [], "percent": [], "duration": []}
    for kind, pattern in patterns:
        for match in re.finditer(pattern, lower):
            normalized = _normalize_fact(match.group(0))
            ctx = _window_context_tokens(source, match.start(), match.end())
            snip_start = max(0, match.start() - 150)
            snip_end = min(len(source), match.end() + 150)
            raw_snippet = source[snip_start:snip_end].strip()
            out[kind].append(Fact(value=normalized, kind=kind, context=ctx, tier=chunk_tier, raw_snippet=raw_snippet))
    return out


def _value_set(facts: list[Fact]) -> set[str]:
    return {f.value for f in facts}


def _llm_verify_chunk_conflict(text_a: str, text_b: str, question: str) -> bool:
    """Ask LLM whether two full chunk texts contain contradictory info relevant to the question.

    Called once per query as a final-stage check when regex found numeric disagreements
    but Jaccard couldn't confirm. Fail-open: returns False on error.
    """
    if not _USE_LLM or not _OPENROUTER_API_KEY:
        return False

    start = time.time()
    try:
        resp = requests.post(
            _OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {_OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": _OPENROUTER_MODEL,
                "temperature": 0.0,
                "max_tokens": 80,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You detect data contradictions in policy documents. "
                            "First, identify what SPECIFIC RULE each excerpt states. "
                            "Then decide: do they contradict each other?\n\n"
                            "Answer format:\n"
                            "Excerpt 1 rule: [one-line summary]\n"
                            "Excerpt 2 rule: [one-line summary]\n"
                            "Contradiction: yes OR no\n\n"
                            "A contradiction means the EXACT SAME rule/guarantee/limit "
                            "is stated with DIFFERENT values.\n\n"
                            "NOT contradictions (answer no):\n"
                            "- Standard refund window (14 days) vs Enterprise satisfaction guarantee (30 days) — different policies\n"
                            "- Account deletion timeline vs account reactivation window — different processes\n"
                            "- Different plan tiers with different values (Pro 99.9% vs Enterprise 99.99%)\n"
                            "- Different severity levels with different response times (P1 15min vs P4 48hr)\n"
                            "- Eligibility period vs processing cutoff — different aspects of the same topic\n\n"
                            "ARE contradictions (answer yes):\n"
                            "- One doc says Pro uptime is 99.9%, another says ALL tiers get 99.99%\n"
                            "- One doc says refund window is 14 days, another says the same refund window is 30 days for the same tier\n"
                            "- One doc says data deletion takes 30 days, another says the same deletion process takes 45 days"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f'User question: "{question}"\n\n'
                            f"Excerpt 1:\n{text_a[:600]}\n\n"
                            f"Excerpt 2:\n{text_b[:600]}\n\n"
                            "Do these excerpts contain a direct contradiction relevant to the user's question?"
                        ),
                    },
                ],
            },
            timeout=10,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"].strip().lower()
        latency_ms = int((time.time() - start) * 1000)
        logger.info(
            "CONFLICT_LLM_VERIFY question=%r llm_result=%s latency_ms=%d",
            question[:60], answer, latency_ms,
        )
        return "contradiction: yes" in answer
    except Exception as exc:
        latency_ms = int((time.time() - start) * 1000)
        logger.warning(
            "CONFLICT_LLM_VERIFY_FAILED error=%s latency_ms=%d",
            str(exc)[:120], latency_ms,
        )
        return False


def _has_contextual_conflict(left: list[Fact], right: list[Fact]) -> bool:
    if not left or not right:
        return False
    left_values = _value_set(left)
    right_values = _value_set(right)
    if left_values == right_values:
        return False

    for lf in left:
        for rf in right:
            if lf.value == rf.value:
                continue
            if lf.tier and rf.tier and lf.tier != rf.tier:
                continue
            overlap = lf.context & rf.context
            if not overlap:
                continue
            union = lf.context | rf.context
            similarity = len(overlap) / len(union) if union else 0.0
            logger.info(
                "CONFLICT_SCORE doc_pair=%s|%s kind=%s values=%s|%s jaccard=%.3f overlap=%s",
                getattr(lf, '_doc_id', '?'), getattr(rf, '_doc_id', '?'),
                lf.kind, lf.value, rf.value, similarity, overlap,
            )
            if similarity >= 0.2:
                return True
    return False


def _question_tier(question: str) -> str | None:
    """Extract plan tier mentioned in the user's question."""
    q = question.lower()
    for tier in TIER_TOKENS:
        if re.search(rf"\b{tier}\b", q):
            return tier
    return None


def _snippet_tier(snippet: str) -> str | None:
    """Detect if a fact snippet mentions a specific tier."""
    lower = snippet.lower()
    for tier in TIER_TOKENS:
        if re.search(rf"\b{tier}\b", lower):
            return tier
    return None


def _pair_has_numeric_disagreement(chunk_a: dict, chunk_b: dict, qtier: str | None = None) -> bool:
    """Check if two chunks have facts of the same kind with different values and some context overlap.

    When qtier is set, narrows the comparison to facts whose snippet mentions that tier.
    Also excludes cross-tier comparisons at the snippet level — if one fact's snippet
    mentions "Enterprise" and another mentions "Standard", they're not comparable.
    """
    tier_a = _chunk_tier(chunk_a)
    tier_b = _chunk_tier(chunk_b)
    facts_a = _extract_fact_objects(chunk_a.get("text", ""), chunk_tier=tier_a)
    facts_b = _extract_fact_objects(chunk_b.get("text", ""), chunk_tier=tier_b)

    for kind in ("money", "percent", "duration"):
        left_facts = facts_a[kind]
        right_facts = facts_b[kind]

        if qtier:
            # Exclude facts whose snippet mentions a DIFFERENT tier
            filtered_a = [f for f in left_facts
                          if _snippet_tier(f.raw_snippet) in (None, qtier)]
            filtered_b = [f for f in right_facts
                          if _snippet_tier(f.raw_snippet) in (None, qtier)]
            if filtered_a:
                left_facts = filtered_a
            if filtered_b:
                right_facts = filtered_b

        for lf in left_facts:
            for rf in right_facts:
                if lf.value == rf.value:
                    continue
                if lf.tier and rf.tier and lf.tier != rf.tier:
                    continue
                # Snippet-level tier exclusion (catches cross-tier even without qtier)
                lf_st = _snippet_tier(lf.raw_snippet)
                rf_st = _snippet_tier(rf.raw_snippet)
                if lf_st and rf_st and lf_st != rf_st:
                    continue
                if len(lf.context & rf.context) >= 2:
                    return True
    return False


def _detect_pair_conflict(chunk_a: dict, chunk_b: dict, question: str = "") -> Optional[dict]:
    tier_a = _chunk_tier(chunk_a)
    tier_b = _chunk_tier(chunk_b)
    facts_a = _extract_fact_objects(chunk_a.get("text", ""), chunk_tier=tier_a)
    facts_b = _extract_fact_objects(chunk_b.get("text", ""), chunk_tier=tier_b)

    a_id = f"{chunk_a.get('doc_id', '?')}#{chunk_a.get('chunk_id', '?')}"
    b_id = f"{chunk_b.get('doc_id', '?')}#{chunk_b.get('chunk_id', '?')}"

    for kind in ("money", "percent", "duration"):
        a_vals = sorted(_value_set(facts_a[kind]))
        b_vals = sorted(_value_set(facts_b[kind]))
        if a_vals and b_vals and set(a_vals) != set(b_vals):
            # Log all Jaccard comparisons for this pair
            for lf in facts_a[kind]:
                for rf in facts_b[kind]:
                    if lf.value == rf.value:
                        continue
                    overlap = lf.context & rf.context
                    if not overlap:
                        continue
                    union = lf.context | rf.context
                    sim = len(overlap) / len(union) if union else 0.0
                    logger.info(
                        "CONFLICT_PAIR %s vs %s | kind=%s | %s vs %s | jaccard=%.3f | overlap=%s | a_ctx=%s | b_ctx=%s",
                        a_id, b_id, kind, lf.value, rf.value, sim, overlap, lf.context, rf.context,
                    )
        if _has_contextual_conflict(facts_a[kind], facts_b[kind]):
            a_vals = sorted(_value_set(facts_a[kind]))
            b_vals = sorted(_value_set(facts_b[kind]))
            return {
                "conflict": True,
                "conflict_type": kind,
                "sources": [
                    {
                        "doc_id": chunk_a["doc_id"],
                        "chunk_id": chunk_a["chunk_id"],
                        "facts": a_vals,
                    },
                    {
                        "doc_id": chunk_b["doc_id"],
                        "chunk_id": chunk_b["chunk_id"],
                        "facts": b_vals,
                    },
                ],
                "message": "I found conflicting information across our documents on this topic. Here are both sources - I'd recommend reaching out to our support team for clarification.",
            }
    return None


def _looks_multi_part_question(question: str | None) -> bool:
    q = (question or "").lower()
    if "; " in q or " also " in q:
        return True
    if " and " not in q:
        return False
    parts = q.split(" and ")
    question_words = {"what", "how", "when", "where", "why", "which", "can", "do", "does", "is", "are", "will"}
    clause_count = sum(1 for p in parts if p.strip() and p.strip().split()[0] in question_words)
    return clause_count >= 2


def _is_explicit_conflict_question(question: str | None) -> bool:
    q = (question or "").lower()
    if not q:
        return False

    cues = (
        "which is it",
        "contradict",
        "conflict",
        "one says",
        "another says",
        "i also saw",
        "reconcile",
    )
    if any(cue in q for cue in cues):
        return True

    percentage_mentions = re.findall(r"\d+\.?\d*%", q)
    if len(set(percentage_mentions)) >= 2:
        return True
    return False


def check_for_conflicts(chunks: list[dict], threshold: float = 0.3, question: str | None = None) -> Optional[dict]:
    if len(chunks) < 2:
        return None

    q = (question or "").lower()
    refund_query = "refund" in q
    top = chunks[0]
    top_text = (top.get("text", "") or "").lower()

    # First pass: cross-document conflicts.
    for other in chunks[1:]:
        if other["doc_id"] == top["doc_id"]:
            continue
        if other.get("score", 0.0) <= threshold:
            continue
        if refund_query:
            other_text = (other.get("text", "") or "").lower()
            if "refund" not in top_text or "refund" not in other_text:
                continue

        conflict = _detect_pair_conflict(top, other, question=question or "")
        if conflict:
            return conflict

    # Second pass: within-document conflicts for single-metric style questions.
    if _looks_multi_part_question(question) and not _is_explicit_conflict_question(question):
        return None

    for other in chunks[1:]:
        if other["doc_id"] != top["doc_id"]:
            continue
        if other.get("score", 0.0) <= threshold:
            continue
        if refund_query:
            other_text = (other.get("text", "") or "").lower()
            if "refund" not in top_text or "refund" not in other_text:
                continue

        conflict = _detect_pair_conflict(top, other, question=question or "")
        if conflict:
            return conflict

    # LLM fallback: regex found numeric disagreements but Jaccard couldn't confirm.
    # Send full chunk text to LLM once for the best candidate pair.
    if _USE_LLM and _OPENROUTER_API_KEY and question:
        qtier = _question_tier(question)
        for other in chunks[1:]:
            if other.get("score", 0.0) <= threshold:
                continue
            if not _pair_has_numeric_disagreement(top, other, qtier=qtier):
                continue
            if _llm_verify_chunk_conflict(
                top.get("text", ""), other.get("text", ""), question
            ):
                # Build conflict result from the pair
                tier_a = _chunk_tier(top)
                tier_b = _chunk_tier(other)
                facts_a = _extract_fact_objects(top.get("text", ""), chunk_tier=tier_a)
                facts_b = _extract_fact_objects(other.get("text", ""), chunk_tier=tier_b)
                for kind in ("money", "percent", "duration"):
                    a_vals = sorted(_value_set(facts_a[kind]))
                    b_vals = sorted(_value_set(facts_b[kind]))
                    if a_vals and b_vals and set(a_vals) != set(b_vals):
                        return {
                            "conflict": True,
                            "conflict_type": kind,
                            "sources": [
                                {
                                    "doc_id": top["doc_id"],
                                    "chunk_id": top["chunk_id"],
                                    "facts": a_vals,
                                },
                                {
                                    "doc_id": other["doc_id"],
                                    "chunk_id": other["chunk_id"],
                                    "facts": b_vals,
                                },
                            ],
                            "message": "I found conflicting information across our documents on this topic. Here are both sources - I'd recommend reaching out to our support team for clarification.",
                        }

    return None
