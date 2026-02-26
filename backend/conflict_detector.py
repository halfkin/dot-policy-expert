from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

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


@dataclass
class Fact:
    value: str
    kind: str
    context: set[str]
    tier: str | None = None


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


def _window_context_tokens(text: str, start: int, end: int, radius: int = 70) -> set[str]:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = text[left:right].lower()
    tokens = re.findall(r"[a-z0-9]+", snippet)
    return {t for t in tokens if len(t) > 2 and t not in CONTEXT_STOPWORDS}


def _extract_fact_objects(text: str) -> dict[str, list[Fact]]:
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
            tier_window = lower[max(0, match.start() - 50):min(len(lower), match.end() + 50)]
            detected_tier = None
            for t in TIER_TOKENS:
                if t in tier_window:
                    if t == "business" and re.search(r"business\s+days?", tier_window):
                        if not re.search(r"business\s+plan", tier_window):
                            continue
                    detected_tier = t
                    break
            out[kind].append(Fact(value=normalized, kind=kind, context=ctx, tier=detected_tier))
    return out


def _value_set(facts: list[Fact]) -> set[str]:
    return {f.value for f in facts}


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


def _detect_pair_conflict(chunk_a: dict, chunk_b: dict) -> Optional[dict]:
    facts_a = _extract_fact_objects(chunk_a.get("text", ""))
    facts_b = _extract_fact_objects(chunk_b.get("text", ""))

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
    return (" and " in q) or ("; " in q) or (" also " in q)


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


def _is_tier_specific_refund_window_question(question: str | None) -> bool:
    q = (question or "").lower()
    if "refund" not in q or "window" not in q:
        return False
    has_tier = any(tier in q for tier in TIER_TOKENS)
    has_after_number = bool(re.search(r"\bafter\s+\d+", q))
    return has_tier and not has_after_number


def _should_attempt_conflict_scan(question: str | None) -> bool:
    if _is_tier_specific_refund_window_question(question):
        return False
    return True


def check_for_conflicts(chunks: list[dict], threshold: float = 0.3, question: str | None = None) -> Optional[dict]:
    if len(chunks) < 2:
        return None

    if _is_tier_specific_refund_window_question(question):
        return None

    if not _should_attempt_conflict_scan(question):
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

        conflict = _detect_pair_conflict(top, other)
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

        conflict = _detect_pair_conflict(top, other)
        if conflict:
            return conflict

    return None
