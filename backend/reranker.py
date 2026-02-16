from __future__ import annotations

import logging
import os
from typing import List, Set, Tuple

try:
    from sentence_transformers import CrossEncoder
    HAS_CROSS_ENCODER = True
except Exception:
    CrossEncoder = None  # type: ignore[assignment]
    HAS_CROSS_ENCODER = False

logger = logging.getLogger(__name__)

RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RERANKER_ENABLED = os.getenv("RERANKER_ENABLED", "true").strip().lower() == "true"

_model = None
_model_load_attempted = False

ChunkTuple = Tuple[str, str, str, float]


def get_reranker():
    global _model, _model_load_attempted
    if _model_load_attempted:
        return _model

    _model_load_attempted = True
    if not RERANKER_ENABLED:
        return None
    if not HAS_CROSS_ENCODER:
        logger.warning("sentence-transformers CrossEncoder unavailable; reranking disabled.")
        return None

    try:
        _model = CrossEncoder(RERANKER_MODEL)
        logger.info("Cross-encoder loaded: %s", RERANKER_MODEL)
    except Exception as exc:
        _model = None
        logger.warning("Cross-encoder failed to load: %s. Reranking disabled.", exc)
    return _model


def rerank(query: str, chunks: List[ChunkTuple], top_k: int = 3) -> List[ChunkTuple]:
    """
    Re-rank retrieved chunks using a cross-encoder.

    Args:
        query: The user's question (or reformulated query)
        chunks: List of (doc_id, chunk_id, text, score) tuples from blended retrieval
        top_k: Number of chunks to return after re-ranking

    Returns:
        Re-ranked list of (doc_id, chunk_id, text, cross_encoder_score) tuples.
        Falls back to original ranking if reranker is disabled/unavailable.
    """
    model = get_reranker()

    if model is None or not chunks:
        return chunks[:top_k]

    pairs = [(query, chunk[2]) for chunk in chunks]
    scores = model.predict(pairs)

    scored = list(zip(chunks, scores))
    scored.sort(key=lambda x: float(x[1]), reverse=True)

    reranked: List[ChunkTuple] = []
    for (doc_id, chunk_id, text, _original_score), ce_score in scored[:top_k]:
        reranked.append((doc_id, chunk_id, text, float(ce_score)))
    return reranked


def _apply_doc_diversity(scored_chunks: List[ChunkTuple], top_k: int) -> List[ChunkTuple]:
    if not scored_chunks or top_k <= 0:
        return []

    remaining = list(scored_chunks)
    selected: List[ChunkTuple] = [remaining.pop(0)]
    selected_docs: Set[str] = {selected[0][0]}

    while remaining and len(selected) < top_k:
        diverse_index = None
        for idx, candidate in enumerate(remaining):
            doc_id = candidate[0]
            if doc_id in selected_docs:
                continue
            diverse_index = idx
            break

        if diverse_index is None:
            next_candidate = remaining.pop(0)
        else:
            next_candidate = remaining.pop(diverse_index)
        selected.append(next_candidate)
        selected_docs.add(next_candidate[0])

    return selected[:top_k]


def rerank_with_diversity(query: str, chunks: List[ChunkTuple], top_k: int = 3) -> List[ChunkTuple]:
    """
    Re-rank with cross-encoder scores, then enforce document diversity in final top-k.

    Selection policy:
      1) keep the highest-ranked chunk
      2) for each remaining slot, prefer highest-scoring chunk from a new document
      3) if no new document remains, fall back to highest remaining score
    """
    model = get_reranker()
    if model is None or not chunks:
        # Fail-open behavior: preserve original blended ranking when reranker is unavailable.
        return chunks[:top_k]

    pairs = [(query, chunk[2]) for chunk in chunks]
    scores = model.predict(pairs)
    scored = [
        (doc_id, chunk_id, text, float(ce_score))
        for (doc_id, chunk_id, text, _original_score), ce_score in zip(chunks, scores)
    ]
    scored.sort(key=lambda x: x[3], reverse=True)
    return _apply_doc_diversity(scored, top_k=top_k)


def reranker_active() -> bool:
    return get_reranker() is not None
