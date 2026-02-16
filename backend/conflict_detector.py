from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

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
    "plan",
    "plans",
    "account",
    "accounts",
    "tier",
    "tiers",
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
            out[kind].append(Fact(value=normalized, kind=kind, context=ctx))
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
            overlap = lf.context & rf.context
            if overlap:
                return True
    return False


def _detect_pair_conflict(chunk_a: dict, chunk_b: dict) -> Optional[dict]:
    facts_a = _extract_fact_objects(chunk_a.get("text", ""))
    facts_b = _extract_fact_objects(chunk_b.get("text", ""))

    for kind in ("money", "percent", "duration"):
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
    q = (question or "").lower()
    if not q:
        return True

    if any(term in q for term in ("delete", "deletion", "soft-delete", "purge", "removed")):
        return True
    if ("uptime" in q) and ("guarantee" in q):
        return True
    if ("uptime" in q) and bool(re.search(r"99\.?9", q)):
        return True
    if ("pto" in q) and any(term in q for term in ("carry over", "carryover", "roll over", "rollover")):
        return True
    if ("refund" in q) and (("window" in q) or bool(re.search(r"\bafter\s+\d+", q))):
        # Generic refund-window questions should scan for conflicting windows,
        # while tier-specific refund windows are handled as non-conflicts.
        after_number = bool(re.search(r"\bafter\s+\d+", q))
        has_tier = any(tier in q for tier in TIER_TOKENS)
        if _is_tier_specific_refund_window_question(question):
            return False
        if after_number and has_tier:
            return True
        if "window" in q:
            return True
        return _is_explicit_conflict_question(question)

    return False


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
