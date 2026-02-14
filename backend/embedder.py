from __future__ import annotations

from typing import List, Optional
import hashlib
import re

try:
    import numpy as np
    HAS_NUMPY = True
except Exception:
    np = None  # type: ignore[assignment]
    HAS_NUMPY = False

try:
    from sentence_transformers import SentenceTransformer
    HAS_SENTENCE_TRANSFORMERS = True
except Exception:
    SentenceTransformer = None  # type: ignore[assignment]
    HAS_SENTENCE_TRANSFORMERS = False

_model = None
_model_load_attempted = False
_model_load_error: Optional[str] = None

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384


def _dot(a, b) -> float:
    if HAS_NUMPY:
        return float(np.dot(a, b))
    return float(sum(float(x) * float(y) for x, y in zip(a, b)))


def _normalize(vec):
    if HAS_NUMPY:
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 0 else vec
    norm = sum(float(v) * float(v) for v in vec) ** 0.5
    if norm == 0:
        return vec
    return [float(v) / norm for v in vec]


def _load_model_once() -> None:
    global _model, _model_load_error
    try:
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    except Exception as exc:
        _model = None
        _model_load_error = f"{type(exc).__name__}: {exc}"


def _get_model():
    global _model_load_attempted, _model_load_error
    if _model_load_attempted:
        return _model

    if not HAS_SENTENCE_TRANSFORMERS:
        return None

    _model_load_attempted = True
    _load_model_once()
    return _model


def _fallback_embed(text: str, dim: int = EMBEDDING_DIMENSIONS):
    """
    Hash-based normalized embedding fallback when sentence-transformers is unavailable.
    Keeps semantic scoring path available in constrained environments.
    """
    vec = np.zeros(dim, dtype=np.float32) if HAS_NUMPY else [0.0] * dim
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        vec[idx] += 1.0
    return _normalize(vec)


def embed_text(text: str):
    model = _get_model()
    if model is not None:
        emb = model.encode(text, normalize_embeddings=True)
        if HAS_NUMPY:
            return np.asarray(emb, dtype=np.float32)
        return list(emb)
    return _fallback_embed(text)


def embed_chunks(chunks: List[dict]) -> List[dict]:
    texts = [c.get("text", "") for c in chunks]
    model = _get_model()
    if model is not None and texts:
        embeddings = model.encode(texts, normalize_embeddings=True)
        for chunk, emb in zip(chunks, embeddings):
            chunk["embedding"] = np.asarray(emb, dtype=np.float32) if HAS_NUMPY else list(emb)
        return chunks

    for chunk in chunks:
        chunk["embedding"] = _fallback_embed(chunk.get("text", ""))
    return chunks


def semantic_search(query: str, chunks: List[dict], top_k: int = 3) -> List[dict]:
    query_emb = embed_text(query)
    scored = []
    for chunk in chunks:
        embedding = chunk.get("embedding")
        if embedding is None:
            embedding = _fallback_embed(chunk.get("text", ""))
        if HAS_NUMPY:
            similarity = float(np.dot(query_emb, np.asarray(embedding, dtype=np.float32)))
        else:
            similarity = _dot(query_emb, embedding)
        scored.append({**chunk, "semantic_score": similarity})
    scored.sort(key=lambda x: x["semantic_score"], reverse=True)
    return scored[:top_k]


def get_embedding_runtime_info() -> dict:
    model = _get_model()
    return {
        "using_sentence_transformer": model is not None,
        "model_name": EMBEDDING_MODEL_NAME if model is not None else None,
        "dimensions": EMBEDDING_DIMENSIONS,
        "has_sentence_transformers": HAS_SENTENCE_TRANSFORMERS,
        "has_numpy": HAS_NUMPY,
        "model_load_error": _model_load_error,
    }
