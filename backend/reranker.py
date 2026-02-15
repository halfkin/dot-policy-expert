from __future__ import annotations

import logging
import os
from typing import List, Tuple

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


def reranker_active() -> bool:
    return get_reranker() is not None
