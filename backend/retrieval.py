"""Search, scoring, and retrieval logic."""
from __future__ import annotations

import os
import re
from typing import List, Literal, Optional, Tuple

from backend.embedder import semantic_search, get_embedding_runtime_info

STOPWORDS = {
    "the","a","an","and","or","to","of","in","on","for","with","is","are","was","were",
    "what","how","when","where","who","why","do","does","did","can","could","should",
    "i","you","we","they","it","this","that",
    "have","policy","policies"
}

TIME_TOKENS = {"long", "within", "day", "days", "week", "weeks", "time", "duration"}
TOP_K = 3
INITIAL_RETRIEVAL_TOP_K = 20
MIN_RETRIEVAL_SCORE = 0.18
BLEND_KEYWORD_WEIGHT = float(os.getenv("BLEND_KEYWORD_WEIGHT", "0.4"))
BLEND_SEMANTIC_WEIGHT = float(os.getenv("BLEND_SEMANTIC_WEIGHT", "0.6"))
SEMANTIC_CANDIDATE_POOL = int(os.getenv("SEMANTIC_CANDIDATE_POOL", "24"))

COMPANY_NAME = os.getenv("COMPANY_NAME", "Loomo")
GENERIC_ANCHOR_TOKENS = {
    COMPANY_NAME.lower(),
    "hub",
    "company",
    "policy",
    "policies",
    "customer",
    "customers",
    "question",
    "information",
    "about",
    "team",
    "support",
    "need",
    "online",
    "together",
}


def tokenize(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for w in words:
        mixed_parts = re.findall(r"\d+|[a-z]+", w)
        if len(mixed_parts) > 1:
            for part in mixed_parts:
                if part in STOPWORDS:
                    continue
                if len(part) < 2 and not part.isdigit():
                    continue
                out.append(part)
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        if w in STOPWORDS:
            continue
        if len(w) < 2:
            continue
        out.append(w)
    return out


def get_confidence(top_score: float) -> Literal["high", "medium", "low"]:
    if top_score > 0.70:
        return "high"
    if top_score > 0.40:
        return "medium"
    return "low"


def score_chunk(question_tokens: List[str], query_phrases: List[str], chunk: dict) -> float:
    search_text = chunk["search_text"]
    chunk_tokens = set(tokenize(search_text))
    heading_tokens = set(tokenize(f"{chunk['doc_title']} {chunk['heading']}"))

    token_hits = sum(1 for t in question_tokens if t in chunk_tokens)
    heading_hits = sum(1 for t in question_tokens if t in heading_tokens)
    phrase_hits = sum(1 for phrase in query_phrases if phrase in search_text)

    if token_hits == 0 and heading_hits == 0 and phrase_hits == 0:
        return 0.0

    score = float(token_hits)
    score += float(heading_hits) * 2.0
    score += float(phrase_hits) * 3.0

    if any(t in TIME_TOKENS for t in question_tokens) and re.search(r"\b\d+\.?\d*\b", search_text):
        score += 1.0

    return score


def short_quote(text: str, max_words: int = 25) -> str:
    words = text.replace("\n", " ").split()
    return " ".join(words[:max_words])


def extract_query_phrases(question: str, max_phrases: int = 8) -> List[str]:
    words = re.findall(r"[a-z0-9]+", question.lower())
    phrases: List[str] = []
    seen = set()

    for n in (4, 3, 2):
        for i in range(len(words) - n + 1):
            slice_words = words[i : i + n]
            if all(w in STOPWORDS for w in slice_words):
                continue
            phrase = " ".join(slice_words).strip()
            if len(phrase) < 8:
                continue
            if phrase in seen:
                continue
            seen.add(phrase)
            phrases.append(phrase)
            if len(phrases) >= max_phrases:
                return phrases
    return phrases


def get_query_anchors(raw_tokens: List[str]) -> List[str]:
    anchors = []
    for t in raw_tokens:
        if len(t) < 4:
            continue
        if t in GENERIC_ANCHOR_TOKENS:
            continue
        if t in TIME_TOKENS:
            continue
        if t.isdigit():
            continue
        anchors.append(t)
    return sorted(set(anchors))


def is_multi_part_question(question: str) -> bool:
    q = (question or "").lower()
    return (" and " in q) or (" also " in q) or (" both " in q)


def retrieval_threshold(best_score: float) -> float:
    del best_score
    return MIN_RETRIEVAL_SCORE


def semantic_retrieval_enabled() -> bool:
    if BLEND_SEMANTIC_WEIGHT <= 0.0 or SEMANTIC_CANDIDATE_POOL <= 0:
        return False
    embedding_info = get_embedding_runtime_info()
    return bool(embedding_info.get("using_sentence_transformer"))


def not_in_sources_answer() -> str:
    from backend.app import NOT_IN_SOURCES_PREFIX, CUSTOMER_SUPPORT_LINE
    return f"{NOT_IN_SOURCES_PREFIX} {CUSTOMER_SUPPORT_LINE}"


def select_top_sources(
    thresholded_scored: List[Tuple[float, dict]],
    question: str,
    top_k: int = TOP_K,
) -> List[Tuple[float, dict]]:
    if len(thresholded_scored) <= top_k:
        selected = thresholded_scored[:]
    elif not is_multi_part_question(question):
        selected = thresholded_scored[:top_k]
    else:
        selected = []
        seen_docs = set()
        for item in thresholded_scored:
            _, chunk = item
            if chunk["doc_id"] in seen_docs:
                continue
            selected.append(item)
            seen_docs.add(chunk["doc_id"])
            if len(selected) >= top_k:
                break

        for item in thresholded_scored:
            if len(selected) >= top_k:
                break
            if item in selected:
                continue
            selected.append(item)

    return selected[:top_k]


def build_suggestions(scored: List[Tuple[float, dict]], max_score: float, limit: int = 3) -> list:
    """Returns list of dicts with doc_id and heading keys."""
    suggestions: list = []
    seen = set()
    for score, chunk in scored:
        normalized = (float(score) / max_score) if max_score else 0.0
        if normalized <= 0.1:
            continue
        key = (chunk["doc_id"], chunk["heading"])
        if key in seen:
            continue
        seen.add(key)
        suggestions.append({"doc_id": chunk["doc_id"], "heading": chunk["heading"]})
        if len(suggestions) >= limit:
            break
    return suggestions


def blended_search(
    query: str,
    chunks: List[dict],
    keyword_scored: List[Tuple[float, dict]],
    top_k: Optional[int] = None,
) -> List[Tuple[float, dict]]:
    if not chunks:
        return []

    keyword_scores = {
        chunk["chunk_id"]: float(score)
        for score, chunk in keyword_scored
    }

    semantic_limit = min(
        len(chunks),
        max(SEMANTIC_CANDIDATE_POOL, (top_k or TOP_K) * 8),
    )
    semantic_results = semantic_search(query, chunks, top_k=semantic_limit)
    semantic_scores = {
        chunk["chunk_id"]: float(chunk.get("semantic_score", 0.0))
        for chunk in semantic_results
    }

    max_kw = max(keyword_scores.values()) if keyword_scores else 0.0
    max_sem = max(semantic_scores.values()) if semantic_scores else 0.0
    id_to_chunk = {chunk["chunk_id"]: chunk for chunk in chunks}
    all_chunk_ids = sorted(set(keyword_scores.keys()) | set(semantic_scores.keys()))

    blended: List[Tuple[float, dict]] = []
    for chunk_id in all_chunk_ids:
        chunk = id_to_chunk.get(chunk_id)
        if not chunk:
            continue
        kw_norm = (keyword_scores.get(chunk_id, 0.0) / max_kw) if max_kw > 0 else 0.0
        sem_norm = (semantic_scores.get(chunk_id, 0.0) / max_sem) if max_sem > 0 else 0.0
        score = BLEND_KEYWORD_WEIGHT * kw_norm + BLEND_SEMANTIC_WEIGHT * sem_norm
        if score > 0:
            blended.append((score, chunk))

    blended.sort(key=lambda x: (-x[0], x[1]["chunk_id"]))
    if top_k is not None:
        return blended[:top_k]
    return blended
