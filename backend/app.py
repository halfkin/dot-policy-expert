from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Literal, Optional, Tuple, cast
from pathlib import Path
from contextlib import asynccontextmanager
from collections import deque
from functools import wraps
import logging
import os
import json
import time
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from backend.ravelin import scan_input
from backend.conflict_detector import check_for_conflicts
from backend.embedder import get_embedding_runtime_info
from backend.query_reformulator import reformulate_query
from backend.reranker import (
    RERANKER_ENABLED,
    RERANKER_MODEL,
    rerank_with_diversity,
    reranker_active,
)
from backend.kb_loader import get_kb_chunks_cached
from backend.retrieval import (
    blended_search,
    select_top_sources,
    build_suggestions,
    tokenize,
    score_chunk,
    short_quote,
    not_in_sources_answer,
    extract_query_phrases,
    get_query_anchors,
    get_confidence,
    retrieval_threshold,
    BLEND_KEYWORD_WEIGHT,
    BLEND_SEMANTIC_WEIGHT,
    TOP_K,
    INITIAL_RETRIEVAL_TOP_K,
)
from backend.llm_client import call_openrouter
from backend.language import check_language, translate_to_english, SUPPORTED_LANGUAGES

logger = logging.getLogger(__name__)

try:
    from slowapi import Limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address
    HAS_SLOWAPI = True
except Exception:
    HAS_SLOWAPI = False

    class RateLimitExceeded(Exception):
        pass

    def get_remote_address(request: Request) -> str:
        client = getattr(request, "client", None)
        return getattr(client, "host", "unknown") or "unknown"

    class Limiter:
        def __init__(self, key_func):
            self.key_func = key_func
            self._hits: Dict[str, deque] = {}

        def limit(self, spec: str):
            if spec != "20/minute":
                raise ValueError(f"Unsupported limiter spec: {spec}")
            max_calls = 20
            window_seconds = 60

            def decorator(func):
                @wraps(func)
                def wrapper(*args, **kwargs):
                    request_obj = kwargs.get("request")
                    if request_obj is None:
                        for arg in args:
                            if isinstance(arg, Request):
                                request_obj = arg
                                break

                    if request_obj is not None:
                        key = self.key_func(request_obj)
                        now = time.time()
                        q = self._hits.setdefault(key, deque())
                        while q and (now - q[0]) > window_seconds:
                            q.popleft()
                        if len(q) >= max_calls:
                            raise RateLimitExceeded()
                        q.append(now)

                    return func(*args, **kwargs)

                return wrapper

            return decorator

@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    warm_kb_embeddings()
    yield


app = FastAPI(lifespan=lifespan)
@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    if request.url.path in ("/health", "/"):
        return await call_next(request)

    api_key = request.headers.get("X-API-Key")
    expected_key = os.getenv("DOT_API_KEY")

    if not api_key or api_key != expected_key:
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})

    return await call_next(request)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# ---- LLM Mode (optional) ----
# Default is OFF to keep things fully offline.
USE_LLM = os.getenv("USE_LLM", "0") == "1"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
COMPANY_NAME = os.getenv("COMPANY_NAME", "Loomo")
BOT_NAME = os.getenv("BOT_NAME", "Dot")
SUPPORT_LINE = os.getenv("SUPPORT_LINE", "our support team")
CUSTOMER_SUPPORT_LINE = f"I'd recommend reaching out to {SUPPORT_LINE} for clarification."
NOT_IN_SOURCES_PREFIX = "Not in sources."
MAX_INPUT_LENGTH = 10_000
SHOW_DEBUG = os.getenv("SHOW_DEBUG", "false").strip().lower() == "true"
FEEDBACK_LOG_PATH = Path("logs/feedback.jsonl")
FOLLOWUP_SIGNALS = [
    "what about",
    "how about",
    "and for",
    "compared to",
    "the same",
    "what if",
    "how does that",
]
PRONOUNS = ["it", "that", "this", "those", "them", "they"]

# ----- Request/Response Types -----

class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class ChatRequest(BaseModel):
    question: str
    history: Optional[List[ConversationTurn]] = None

class Citation(BaseModel):
    doc_id: str
    chunk_id: str
    quote: str  # <= 25 words

class Suggestion(BaseModel):
    doc_id: str
    heading: str

class FeedbackRequest(BaseModel):
    question: str
    answer: str
    rating: Literal["positive", "negative"]
    timestamp: str
    confidence: Optional[Literal["high", "medium", "low"]] = None
    failure_bucket: Optional[str] = None

class FeedbackResponse(BaseModel):
    ok: bool

class ChatResponse(BaseModel):
    answer: str
    citations: List[Citation]
    confidence: Literal["high", "medium", "low"]
    failure_bucket: Literal[
        "none",
        "not_in_sources",
        "retrieval_failed",
        "conflict_in_sources",
        "needs_clarification",
        "prompt_injection_blocked",
        "unsupported_language",
        "empty_input",
        "input_too_long",
        "rate_limited",
    ]
    blocked_by: Optional[Literal["layer_0", "layer_1", "layer_2", "layer_3"]] = None
    conflict_details: Optional[dict] = None
    suggestions: List[Suggestion] = Field(default_factory=list)
    response_time_seconds: float
    detected_language: Optional[str] = None
    translated_from: Optional[Literal["fr", "es"]] = None
    original_query: Optional[str] = None
    retrieval_query: Optional[str] = None
    reranker_active: bool = False
    debug: Optional[dict] = None

# ----- Helpers -----

def is_likely_followup(question: str, history: List[ConversationTurn]) -> bool:
    if not history:
        return False
    q = (question or "").lower().strip()
    if len(q.split()) > 8:
        return False
    return any(signal in q for signal in FOLLOWUP_SIGNALS) or any(word in q.split() for word in PRONOUNS)


def get_last_user_message(history: List[ConversationTurn]) -> Optional[str]:
    for turn in reversed(history):
        if turn.role == "user":
            content = (turn.content or "").strip()
            if content:
                return content
    return None

# ----- Routes -----

def warm_kb_embeddings() -> None:
    get_kb_chunks_cached(refresh=True)
    reranker_active()  # eagerly load cross-encoder at startup
    logger.info("Reranker: %s (%s)", "enabled" if RERANKER_ENABLED else "disabled", RERANKER_MODEL)
    embedding_info = get_embedding_runtime_info()
    if embedding_info["using_sentence_transformer"]:
        print(
            f"Embedding model: {embedding_info['model_name']} "
            f"({embedding_info['dimensions']} dimensions)"
        )
    else:
        print(
            "WARNING: Using hash-based fallback embeddings — install sentence-transformers for real semantic search."
        )
        if embedding_info.get("model_load_error"):
            print(f"Embedding model load error: {embedding_info['model_load_error']}")

    semantic_weight_source = "env" if os.getenv("BLEND_SEMANTIC_WEIGHT") is not None else "default"
    print(
        f"Retrieval blend weights: keyword={BLEND_KEYWORD_WEIGHT}, "
        f"semantic={BLEND_SEMANTIC_WEIGHT} (BLEND_SEMANTIC_WEIGHT source={semantic_weight_source})"
    )
    total_weight = BLEND_KEYWORD_WEIGHT + BLEND_SEMANTIC_WEIGHT
    print(f"Retrieval blend weight sum: {total_weight:.3f}")
    if HAS_SLOWAPI:
        print("Rate limiting backend: slowapi (20/minute)")
    else:
        print("Rate limiting backend: built-in fallback (20/minute)")


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    del request, exc
    return JSONResponse(
        status_code=429,
        content={
            "answer": "Too many requests. Please wait a moment.",
            "citations": [],
            "confidence": "low",
            "failure_bucket": "rate_limited",
            "blocked_by": None,
            "conflict_details": None,
            "suggestions": [],
            "response_time_seconds": 0.0,
            "detected_language": None,
            "translated_from": None,
            "original_query": None,
            "retrieval_query": None,
            "reranker_active": False,
            "debug": None,
        },
    )

@app.get("/", response_class=HTMLResponse)
def index():
    return Path("frontend/index.html").read_text(encoding="utf-8")

@app.get("/health")
def health():
    chunks = get_kb_chunks_cached()
    embedding_info = get_embedding_runtime_info()
    return {
        "ok": True,
        "message": "server is running",
        "mode": "llm" if USE_LLM else "offline",
        "kb_chunks": len(chunks),
        "kb_files": len({c["doc_id"] for c in chunks}),
        "embedding_model": embedding_info.get("model_name") or "fallback",
        "reranker": reranker_active(),
    }

@app.post("/chat", response_model=ChatResponse)
@limiter.limit("20/minute")
def chat(request: Request, req: ChatRequest):
    del request
    started_at = time.perf_counter()
    raw_question = req.question or ""
    q = raw_question.strip()
    history = req.history or []
    request_translated_from: Optional[Literal["fr", "es"]] = None
    request_original_query: Optional[str] = None
    request_retrieval_query: Optional[str] = None

    def make_response(
        *,
        answer: str,
        citations: List[Citation],
        confidence: Literal["high", "medium", "low"],
        failure_bucket: Literal[
            "none",
            "not_in_sources",
            "retrieval_failed",
            "conflict_in_sources",
            "needs_clarification",
            "prompt_injection_blocked",
            "unsupported_language",
            "empty_input",
            "input_too_long",
            "rate_limited",
        ],
        blocked_by: Optional[Literal["layer_0", "layer_1", "layer_2", "layer_3"]] = None,
        conflict_details: Optional[dict] = None,
        suggestions: Optional[List[Suggestion]] = None,
        detected_language: Optional[str] = None,
        translated_from: Optional[Literal["fr", "es"]] = None,
        original_query: Optional[str] = None,
        retrieval_query: Optional[str] = None,
        reranker_active_flag: bool = False,
        debug: Optional[dict] = None,
    ) -> ChatResponse:
        elapsed = round(time.perf_counter() - started_at, 2)
        resolved_translated_from = (
            translated_from if translated_from is not None else request_translated_from
        )
        resolved_original_query = (
            original_query if original_query is not None else request_original_query
        )
        resolved_retrieval_query = (
            retrieval_query if retrieval_query is not None else request_retrieval_query
        )
        return ChatResponse(
            answer=answer,
            citations=citations,
            confidence=confidence,
            failure_bucket=failure_bucket,
            blocked_by=blocked_by,
            conflict_details=conflict_details,
            suggestions=suggestions or [],
            response_time_seconds=elapsed,
            detected_language=detected_language,
            translated_from=resolved_translated_from,
            original_query=resolved_original_query,
            retrieval_query=resolved_retrieval_query,
            reranker_active=reranker_active_flag,
            debug=debug if SHOW_DEBUG else None,
        )

    if not q:
        return make_response(
            answer=f"Please enter a question about {COMPANY_NAME}'s policies.",
            citations=[],
            confidence="low",
            failure_bucket="empty_input",
        )

    if len(raw_question) > MAX_INPUT_LENGTH:
        return make_response(
            answer="Your message is too long. Please keep questions under 10,000 characters.",
            citations=[],
            confidence="low",
            failure_bucket="input_too_long",
        )

    detected_language = check_language(q)
    if detected_language and detected_language != "en":
        if detected_language not in SUPPORTED_LANGUAGES:
            return make_response(
                answer=(
                    "I currently support English, plus French and Spanish in LLM mode. "
                    f"Please rephrase your question in English. {CUSTOMER_SUPPORT_LINE}"
                ),
                citations=[],
                confidence="low",
                failure_bucket="unsupported_language",
                detected_language=detected_language,
            )

        if not USE_LLM or not OPENROUTER_API_KEY:
            return make_response(
                answer=(
                    "French and Spanish input requires LLM mode with translation enabled. "
                    f"Please rephrase your question in English. {CUSTOMER_SUPPORT_LINE}"
                ),
                citations=[],
                confidence="low",
                failure_bucket="unsupported_language",
                detected_language=detected_language,
            )

        try:
            translated_query = translate_to_english(q, detected_language)
        except Exception as e:
            print(f"[Translate] Translation failed: {type(e).__name__}: {e}")
            return make_response(
                answer=(
                    "I couldn't translate that request right now. "
                    f"Please ask in English. {CUSTOMER_SUPPORT_LINE}"
                ),
                citations=[],
                confidence="low",
                failure_bucket="unsupported_language",
                detected_language=detected_language,
            )

        request_translated_from = cast(Literal["fr", "es"], detected_language)
        request_original_query = q
        q = translated_query.strip()
        request_retrieval_query = q

    scan_result = scan_input(q, use_llm_judge=USE_LLM)
    if scan_result["status"] == "BLOCKED":
        return make_response(
            answer=(
                "I can't process that request as written. "
                f"Please rephrase your question about {COMPANY_NAME} policies. {CUSTOMER_SUPPORT_LINE}"
            ),
            citations=[],
            confidence="low",
            failure_bucket="prompt_injection_blocked",
            blocked_by=scan_result["blocked_by"],
            detected_language=detected_language,
        )

    if detected_language and detected_language != "en" and not q:
        return make_response(
            answer=(
                "I couldn't translate that request right now. "
                f"{CUSTOMER_SUPPORT_LINE}"
            ),
            citations=[],
            confidence="low",
            failure_bucket="unsupported_language",
            detected_language=detected_language,
        )

    chunks = get_kb_chunks_cached()
    if not chunks:
        return make_response(
            answer=(
                "I don't have policy sources available right now, so I can't answer yet. "
                f"{CUSTOMER_SUPPORT_LINE}"
            ),
            citations=[],
            confidence="low",
            failure_bucket="retrieval_failed",
        )

    retrieval_query = q
    if request_translated_from:
        request_retrieval_query = retrieval_query
    if USE_LLM and is_likely_followup(q, history):
        prev_question = get_last_user_message(history)
        if prev_question:
            retrieval_query = f"{prev_question} {q}"
            if request_translated_from:
                request_retrieval_query = retrieval_query

    if USE_LLM:
        retrieval_query = reformulate_query(retrieval_query, use_llm=True)
        if request_translated_from:
            request_retrieval_query = retrieval_query

    debug_info = {
        "original_query": request_original_query or q,
        "retrieval_query": retrieval_query,
    }
    if request_translated_from:
        debug_info["translated_from"] = request_translated_from

    raw_q_tokens = tokenize(retrieval_query)
    q_tokens = raw_q_tokens
    query_phrases = extract_query_phrases(retrieval_query)
    if not q_tokens:
        return make_response(
            answer=(
                "I couldn't find enough policy context in that request. "
                "Please rephrase with specific policy terms like refunds, billing, time off, or security. "
                f"{CUSTOMER_SUPPORT_LINE}"
            ),
            citations=[],
            confidence="low",
            failure_bucket="needs_clarification",
            debug=debug_info,
        )

    keyword_scored: List[Tuple[float, dict]] = []
    for chunk in chunks:
        score = score_chunk(q_tokens, query_phrases, chunk)
        if score > 0:
            keyword_scored.append((score, chunk))
    keyword_scored.sort(reverse=True, key=lambda x: x[0])
    best_keyword_score = float(keyword_scored[0][0]) if keyword_scored else 0.0

    scored = blended_search(retrieval_query, chunks, keyword_scored, top_k=INITIAL_RETRIEVAL_TOP_K)
    scored.sort(reverse=True, key=lambda x: x[0])

    if not scored:
        return make_response(
            answer=not_in_sources_answer(),
            citations=[],
            confidence="low",
            failure_bucket="not_in_sources",
            suggestions=[],
            debug=debug_info,
        )

    best_score, _ = scored[0]
    suggestion_dicts = build_suggestions(scored, max_score=float(best_score))
    suggestions = [Suggestion(doc_id=s["doc_id"], heading=s["heading"]) for s in suggestion_dicts]
    minimum_threshold = retrieval_threshold(float(best_score))
    thresholded_scored = [(s, chunk) for s, chunk in scored if s >= minimum_threshold]

    if not thresholded_scored:
        return make_response(
            answer=not_in_sources_answer(),
            citations=[],
            confidence="low",
            failure_bucket="not_in_sources",
            suggestions=suggestions,
            debug=debug_info,
        )

    max_score = float(best_score)
    unknown_tier_tokens = {"starter", "basic", "ultimate", "premiumplus", "gold"}
    if any(token in raw_q_tokens for token in unknown_tier_tokens):
        if not any(token in chunk["search_text"] for token in unknown_tier_tokens for _, chunk in scored[:12]):
            return make_response(
                answer=not_in_sources_answer(),
                citations=[],
                confidence="low",
                failure_bucket="not_in_sources",
                suggestions=suggestions,
                debug=debug_info,
            )

    initial_selected_scored = select_top_sources(
        thresholded_scored,
        q,
        top_k=INITIAL_RETRIEVAL_TOP_K,
    )
    chunk_by_id = {chunk["chunk_id"]: chunk for _, chunk in initial_selected_scored}
    rerank_input = [
        (chunk["doc_id"], chunk["chunk_id"], chunk["text"], float(score))
        for score, chunk in initial_selected_scored
    ]
    reranked_candidates = rerank_with_diversity(retrieval_query, rerank_input, top_k=TOP_K)
    reranker_used = reranker_active()
    selected_scored: List[Tuple[float, dict]] = []
    selected_seen = set()
    for doc_id, chunk_id, _text, score in reranked_candidates:
        if chunk_id in selected_seen:
            continue
        chunk = chunk_by_id.get(chunk_id)
        if not chunk:
            continue
        if chunk.get("doc_id") != doc_id:
            continue
        selected_scored.append((float(score), chunk))
        selected_seen.add(chunk_id)

    if not selected_scored:
        selected_scored = initial_selected_scored[:TOP_K]

    selected_scores_only = [float(score) for score, _ in selected_scored]
    selected_max_score = max(selected_scores_only) if selected_scores_only else 0.0
    selected_min_score = min(selected_scores_only) if selected_scores_only else 0.0
    selected_score_range = selected_max_score - selected_min_score

    def normalize_selected_score(score: float) -> float:
        if selected_score_range > 0.0:
            return (float(score) - selected_min_score) / selected_score_range
        return 1.0 if selected_max_score > 0.0 else 0.0

    conflict_pool = initial_selected_scored[:16]
    conflict_scores = [float(score) for score, _ in conflict_pool]
    conflict_max = max(conflict_scores) if conflict_scores else 0.0
    conflict_min = min(conflict_scores) if conflict_scores else 0.0
    conflict_range = conflict_max - conflict_min

    def normalize_conflict_score(score: float) -> float:
        if conflict_range > 0.0:
            return (float(score) - conflict_min) / conflict_range
        return 1.0 if conflict_max > 0.0 else 0.0

    top_conflict_candidates = [
        {
            "doc_id": chunk["doc_id"],
            "chunk_id": chunk["chunk_id"],
            "text": chunk["text"],
            "heading": chunk.get("heading", ""),
            "doc_title": chunk.get("doc_title", ""),
            "score": normalize_conflict_score(float(s)),
        }
        for s, chunk in conflict_pool
    ]

    conflict = check_for_conflicts(top_conflict_candidates, question=q)
    if conflict:
        text_by_source = {(chunk["doc_id"], chunk["chunk_id"]): chunk["text"] for chunk in chunks}
        conflict_citations: List[Citation] = []
        for src in conflict.get("sources", []):
            src_key = (src["doc_id"], src["chunk_id"])
            quote = short_quote(text_by_source.get(src_key, ""))
            conflict_citations.append(
                Citation(
                    doc_id=src["doc_id"],
                    chunk_id=src["chunk_id"],
                    quote=quote,
                )
            )

        return make_response(
            answer=conflict["message"],
            citations=conflict_citations,
            confidence="low",
            failure_bucket="conflict_in_sources",
            conflict_details=conflict,
            reranker_active_flag=reranker_used,
            debug=debug_info,
        )

    selected_search_blob = " ".join(chunk["search_text"] for _, chunk in selected_scored)

    if best_keyword_score <= 2.0 and best_score < 0.99:
        return make_response(
            answer=not_in_sources_answer(),
            citations=[],
            confidence="low",
            failure_bucket="not_in_sources",
            suggestions=suggestions,
            reranker_active_flag=reranker_used,
            debug=debug_info,
        )

    crypto_terms = ("crypto", "cryptocurrency", "bitcoin", "ethereum")
    if any(term in retrieval_query.lower() for term in crypto_terms) and not any(term in selected_search_blob for term in crypto_terms):
        return make_response(
            answer=not_in_sources_answer(),
            citations=[],
            confidence="low",
            failure_bucket="not_in_sources",
            suggestions=suggestions,
            reranker_active_flag=reranker_used,
            debug=debug_info,
        )

    strict_off_topic_terms = (
        "stock",
        "ceo",
        "programming",
        "language",
        "languages",
        "framework",
        "super bowl",
        "civil code",
        "statutory damages",
        "what model",
        "student discount",
        "hubspot",
        "zendesk",
    )
    strict_hits = [term for term in strict_off_topic_terms if term in retrieval_query.lower() or term in raw_question.lower()]
    if strict_hits and not any(term in selected_search_blob for term in strict_hits):
        return make_response(
            answer=not_in_sources_answer(),
            citations=[],
            confidence="low",
            failure_bucket="not_in_sources",
            suggestions=suggestions,
            reranker_active_flag=reranker_used,
            debug=debug_info,
        )

    # Guardrail: if no specific query anchors are present in selected chunks, refuse.
    anchors = get_query_anchors(raw_q_tokens)
    covered_anchors = {
        anchor
        for anchor in anchors
        if any(anchor in chunk["search_text"] for _, chunk in selected_scored)
    }
    if anchors and not covered_anchors and best_keyword_score < 6.0 and best_score < 0.80:
        return make_response(
            answer=not_in_sources_answer(),
            citations=[],
            confidence="low",
            failure_bucket="not_in_sources",
            suggestions=suggestions,
            reranker_active_flag=reranker_used,
            debug=debug_info,
        )

    # Use selected top-k thresholded chunks for LLM context and citations.
    top_sources = [
        (chunk["doc_id"], chunk["chunk_id"], chunk["text"])
        for _, chunk in selected_scored
    ]
    top_sources_with_scores = [
        (
            normalize_selected_score(float(s)),
            chunk["doc_id"],
            chunk["chunk_id"],
            chunk["text"],
        )
        for s, chunk in selected_scored
    ]

    citations = [
        Citation(doc_id=d, chunk_id=cid, quote=short_quote(ct, max_words=25))
        for d, cid, ct in top_sources
    ]

    # Default offline answer uses all retrieved top-k chunks above threshold.
    if len(top_sources) == 1:
        answer = "Based on the policy text, here is the most relevant information:\n\n" + top_sources[0][2]
    else:
        sections = [f"{i}. [{doc_id} | {chunk_id}]\n{text}" for i, (doc_id, chunk_id, text) in enumerate(top_sources, start=1)]
        answer = f"Based on {COMPANY_NAME} policy documents, here are the most relevant details:\n\n" + "\n\n".join(sections)

    confidence = get_confidence(float(best_score))

    # Optional LLM mode (requires key)
    if USE_LLM:
        if not OPENROUTER_API_KEY:
            return make_response(
                answer=(
                    "I can't use LLM mode right now due to a configuration issue. "
                    "I can continue in offline policy mode. "
                    f"{CUSTOMER_SUPPORT_LINE}"
                ),
                citations=[],
                confidence="low",
                failure_bucket="retrieval_failed",
                reranker_active_flag=reranker_used,
                debug=debug_info,
            )
        try:
            llm_answer = call_openrouter(q, top_sources_with_scores, history=history)
            if llm_answer.startswith(NOT_IN_SOURCES_PREFIX):
                return make_response(
                    answer=not_in_sources_answer(),
                    citations=[],
                    confidence="low",
                    failure_bucket="not_in_sources",
                    suggestions=suggestions,
                    reranker_active_flag=reranker_used,
                    debug=debug_info,
                )
            # We still return our citations (grounded in KB chunks)
            answer = llm_answer
        except Exception as e:
            print(f"[LLM] OpenRouter call failed: {type(e).__name__}: {e}")
            # Fall back to offline answer if the call fails
            confidence = "medium"

    return make_response(
        answer=answer,
        citations=citations,
        confidence=confidence,
        failure_bucket="none",
        reranker_active_flag=reranker_used,
        debug=debug_info,
    )


@app.post("/feedback", response_model=FeedbackResponse)
def feedback(req: FeedbackRequest):
    FEEDBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record: Dict[str, Any] = {
        "question": req.question,
        "answer": req.answer,
        "rating": req.rating,
        "timestamp": req.timestamp,
        "confidence": req.confidence,
        "failure_bucket": req.failure_bucket,
    }
    with FEEDBACK_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=True) + "\n")
    return FeedbackResponse(ok=True)
