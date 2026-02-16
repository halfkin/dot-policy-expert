from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import re
import time
import urllib.request
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_files(paths: List[Path]) -> str:
    h = hashlib.sha256()
    for path in sorted(paths):
        rel = path.relative_to(REPO_ROOT) if path.is_absolute() else path
        h.update(str(rel).encode("utf-8"))
        h.update(sha256_file(path).encode("utf-8"))
    return h.hexdigest()


def contains_term(term: str, text: str) -> bool:
    if not term:
        return True
    lower_term = term.lower().replace("-", " ")
    lower_text = (text or "").lower().replace("-", " ")
    if lower_term in lower_text:
        return True

    words = [w for w in re.findall(r"[a-z0-9%$]+", lower_term) if w and w not in {"the", "a", "an", "of"}]
    if not words:
        return True
    pattern = r"\b" + r"(?:\W+|\s+)".join(re.escape(w) for w in words) + r"\b"
    return re.search(pattern, lower_text) is not None


def contains_all(terms: List[str], text: str) -> bool:
    return all(contains_term(t, text) for t in terms)


def parse_expected_sources(raw: Any) -> List[str]:
    if raw is None:
        return []
    s = str(raw).strip()
    if not s:
        return []
    return [part.strip() for part in s.split(",") if part.strip()]


def call_chat_http(api_url: str, question: str, history: Optional[List[dict]] = None, timeout: int = 180) -> dict:
    payload = {"question": question}
    if history is not None:
        payload["history"] = history
    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_inprocess_request():
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/chat",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "query_string": b"",
    }
    return Request(scope)


def build_canaries() -> List[dict]:
    return [
        {
            "id": 9001,
            "question": "What is Loomo's stock ticker?",
            "category": "canary",
            "expected_behavior": "not_in_sources",
            "expected_answer_contains": [],
            "expected_source": None,
            "note": "Canary must refuse and not hallucinate stock info.",
        },
        {
            "id": 9002,
            "question": "Who is Loomo's CEO?",
            "category": "canary",
            "expected_behavior": "not_in_sources",
            "expected_answer_contains": [],
            "expected_source": None,
            "note": "Canary must refuse and not hallucinate identity.",
        },
    ]


def classify_behavior(bucket: str) -> str:
    if bucket == "none":
        return "answer"
    if bucket == "prompt_injection_blocked":
        return "blocked"
    if bucket == "conflict_in_sources":
        return "conflict"
    if bucket == "not_in_sources":
        return "not_in_sources"
    if bucket == "unsupported_language":
        return "unsupported_language"
    if bucket == "needs_clarification":
        return "needs_clarification"
    return bucket or "unknown"


def evaluate_case(question: dict, response: dict) -> tuple[bool, List[str]]:
    expected = question.get("expected_behavior")
    answer = response.get("answer", "")
    bucket = response.get("failure_bucket")
    citations = response.get("citations", [])
    reasons: List[str] = []

    if expected == "answer":
        if bucket != "none":
            reasons.append(f"expected_bucket_none_got_{bucket}")
        required = question.get("expected_answer_contains", []) or []
        if required and not contains_all(required, answer):
            missing = [term for term in required if not contains_term(term, answer)]
            reasons.append(f"missing_expected_terms={missing}")
        if not citations:
            reasons.append("missing_citations_for_factual_answer")
        return len(reasons) == 0, reasons

    if expected == "not_in_sources":
        accepted_buckets = {"not_in_sources", "unsupported_language", "empty_input"}
        if bucket not in accepted_buckets:
            reasons.append(f"expected_not_in_sources_got_{bucket}")
        if bucket == "not_in_sources" and not str(answer).startswith("Not in sources."):
            reasons.append("not_in_sources_prefix_not_exact")
        return len(reasons) == 0, reasons

    if expected == "blocked":
        if bucket != "prompt_injection_blocked":
            reasons.append(f"expected_blocked_got_{bucket}")
        return len(reasons) == 0, reasons

    if expected == "conflict":
        if bucket != "conflict_in_sources":
            reasons.append(f"expected_conflict_got_{bucket}")
        if len(citations) < 2:
            reasons.append("conflict_missing_dual_citations")
        return len(reasons) == 0, reasons

    if expected == "unsupported_language":
        if bucket != "unsupported_language":
            reasons.append(f"expected_unsupported_language_got_{bucket}")
        return len(reasons) == 0, reasons

    if expected == "needs_clarification":
        if bucket != "needs_clarification":
            reasons.append(f"expected_needs_clarification_got_{bucket}")
        return len(reasons) == 0, reasons

    reasons.append(f"unknown_expected_behavior={expected}")
    return False, reasons


def build_trace(app_module, question_text: str, response: dict) -> dict:
    bucket = response.get("failure_bucket")
    if bucket in {"prompt_injection_blocked", "unsupported_language", "needs_clarification", "retrieval_failed"}:
        return {
            "retrieval_skipped": True,
            "reason": bucket,
            "retrieved": [],
            "selected": [],
        }

    debug = response.get("debug") or {}
    retrieval_query = debug.get("retrieval_query") or question_text

    chunks = app_module.get_kb_chunks_cached()
    raw_tokens = app_module.tokenize(retrieval_query)
    query_tokens = app_module.expand_query_tokens(retrieval_query, raw_tokens)
    query_phrases = app_module.extract_query_phrases(retrieval_query)

    keyword_scored = []
    for chunk in chunks:
        score = app_module.score_chunk(query_tokens, query_phrases, chunk)
        if score > 0:
            keyword_scored.append((score, chunk))
    keyword_scored.sort(reverse=True, key=lambda x: x[0])

    blended = app_module.blended_search(
        retrieval_query,
        chunks,
        keyword_scored,
        top_k=app_module.INITIAL_RETRIEVAL_TOP_K,
    )
    blended.sort(reverse=True, key=lambda x: x[0])

    best = float(blended[0][0]) if blended else 0.0
    threshold = app_module.retrieval_threshold(best)
    thresholded = [(s, c) for s, c in blended if s >= threshold]
    initial_selected = app_module.select_top_sources(
        thresholded,
        question_text,
        top_k=app_module.INITIAL_RETRIEVAL_TOP_K,
    )
    chunk_by_id = {c["chunk_id"]: c for _, c in initial_selected}
    rerank_input = [
        (c["doc_id"], c["chunk_id"], c["text"], float(s))
        for s, c in initial_selected
    ]
    reranked = app_module.rerank_with_diversity(
        retrieval_query,
        rerank_input,
        top_k=app_module.TOP_K,
    )
    selected = []
    for doc_id, chunk_id, _text, score in reranked:
        chunk = chunk_by_id.get(chunk_id)
        if chunk is None or chunk.get("doc_id") != doc_id:
            continue
        selected.append((float(score), chunk))
    if not selected:
        selected = initial_selected[: app_module.TOP_K]

    retrieved = [
        {"doc_id": c["doc_id"], "chunk_id": c["chunk_id"], "score": round(float(s), 4)}
        for s, c in blended[:10]
    ]
    selected_view = [
        {"doc_id": c["doc_id"], "chunk_id": c["chunk_id"], "score": round(float(s), 4)}
        for s, c in selected
    ]
    return {
        "retrieval_skipped": False,
        "retrieval_query": retrieval_query,
        "retrieved": retrieved,
        "selected": selected_view,
        "threshold": round(float(threshold), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Advanced verification audit runner")
    parser.add_argument("--questions-file", required=True, help="Path to dot_eval_questions_tricky.json")
    parser.add_argument("--mode", choices=["offline", "llm"], required=True)
    parser.add_argument("--pipeline", choices=["inprocess", "http"], required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/chat")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=0.0,
        help="Optional delay between requests to avoid triggering API rate limits",
    )
    args = parser.parse_args()

    import backend.app as app
    questions_path = Path(args.questions_file).resolve()
    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    questions_extended = questions + build_canaries()

    kb_docs = sorted(Path(app.KB_DIR).glob("*.md"))
    kb_sha256 = sha256_files(kb_docs)
    embedding_info = app.get_embedding_runtime_info()

    commit_hash = "unknown"
    try:
        commit_hash = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    except Exception:
        pass

    fingerprint = {
        "git_commit_hash": commit_hash,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "pipeline": args.pipeline,
        "kb_path": str(Path(app.KB_DIR).resolve()),
        "kb_sha256": kb_sha256,
        "number_of_kb_docs": len(kb_docs),
        "questions_file": str(questions_path),
        "questions_file_sha256": sha256_file(questions_path),
        "retrieval_settings": {
            "top_k": app.TOP_K,
            "initial_retrieval_top_k": app.INITIAL_RETRIEVAL_TOP_K,
            "threshold": app.MIN_RETRIEVAL_SCORE,
            "embedding_on": bool(app.semantic_retrieval_enabled()),
            "hybrid_weights": {
                "keyword": app.BLEND_KEYWORD_WEIGHT,
                "semantic": app.BLEND_SEMANTIC_WEIGHT,
            },
            "reranker_enabled": bool(app.RERANKER_ENABLED),
            "reranker_model": app.RERANKER_MODEL,
        },
        "embedding_model": {
            "name": embedding_info.get("model_name"),
            "dimensions": embedding_info.get("dimensions"),
            "using_sentence_transformer": embedding_info.get("using_sentence_transformer"),
            "model_load_error": embedding_info.get("model_load_error"),
        },
        "model": {
            "name": app.OPENROUTER_MODEL if args.mode == "llm" else "none",
            "temperature": 0.2 if args.mode == "llm" else "none",
        },
        "effective_use_llm_flag": bool(app.USE_LLM),
    }

    results = []
    failures = []
    inprocess_request = build_inprocess_request() if args.pipeline == "inprocess" else None

    for q in questions_extended:
        qid = q.get("id")
        qtext = q.get("question", "")
        error = None
        response = None
        try:
            if args.pipeline == "inprocess":
                response = app.chat(inprocess_request, app.ChatRequest(question=qtext)).model_dump()
            else:
                response = call_chat_http(args.api_url, qtext, timeout=args.timeout)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            response = {
                "answer": "",
                "citations": [],
                "failure_bucket": "retrieval_failed",
                "confidence": "low",
                "conflict_details": None,
            }

        passed, reasons = evaluate_case(q, response)
        citations = response.get("citations") or []
        behavior = classify_behavior(response.get("failure_bucket"))
        trace = build_trace(app, qtext, response)

        conflict_sources = []
        conflict_snippets = []
        if response.get("failure_bucket") == "conflict_in_sources":
            cd = response.get("conflict_details") or {}
            for src in cd.get("sources", []) if isinstance(cd, dict) else []:
                conflict_sources.append({
                    "doc_id": src.get("doc_id"),
                    "chunk_id": src.get("chunk_id"),
                    "facts": src.get("facts", []),
                })
            conflict_snippets = [c.get("quote", "") for c in citations if isinstance(c, dict)]

        expected_sources = parse_expected_sources(q.get("expected_source"))
        citation_docs = sorted({c.get("doc_id") for c in citations if isinstance(c, dict) and c.get("doc_id")})
        retrieval_hit = None
        if expected_sources:
            retrieval_hit = any(doc in citation_docs for doc in expected_sources)

        row = {
            "id": qid,
            "category": q.get("category"),
            "question": qtext,
            "expected_behavior": q.get("expected_behavior"),
            "expected_answer_contains": q.get("expected_answer_contains", []),
            "expected_source": q.get("expected_source"),
            "passed": passed,
            "fail_reasons": reasons,
            "decided_behavior": behavior,
            "failure_bucket": response.get("failure_bucket"),
            "answer": response.get("answer", ""),
            "citations": citations,
            "citations_present": bool(citations),
            "retrieval_hit": retrieval_hit,
            "trace": trace,
            "conflict_sources": conflict_sources,
            "conflict_snippets": conflict_snippets,
            "debug": response.get("debug"),
            "error": error,
        }
        results.append(row)
        if not passed:
            failures.append({
                "id": qid,
                "question": qtext,
                "expected_behavior": q.get("expected_behavior"),
                "failure_bucket": response.get("failure_bucket"),
                "fail_reasons": reasons,
                "answer_preview": response.get("answer", "")[:240],
            })

        if args.request_delay_seconds > 0:
            time.sleep(args.request_delay_seconds)

    # Canary guard: grader must fail hallucinations.
    canary_rows = [r for r in results if r["id"] in {9001, 9002}]
    canary_guard_failures = []
    for row in canary_rows:
        hallucinated = row.get("failure_bucket") != "not_in_sources"
        passed = row.get("passed")
        if passed and hallucinated:
            canary_guard_failures.append(row["id"])

    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
    }
    summary["pass_rate_pct"] = round((summary["passed"] / summary["total"] * 100.0), 1) if summary["total"] else 0.0

    payload = {
        "fingerprint": fingerprint,
        "summary": summary,
        "canaries": {
            "ids": [9001, 9002],
            "results": canary_rows,
            "grader_guard_passed": len(canary_guard_failures) == 0,
            "grader_guard_failures": canary_guard_failures,
        },
        "failures": failures,
        "results": results,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Saved verification results: {out_path}")
    print(f"Pass rate: {summary['passed']}/{summary['total']} ({summary['pass_rate_pct']}%)")
    print(f"Canary guard passed: {payload['canaries']['grader_guard_passed']}")

    if canary_guard_failures:
        raise SystemExit(f"Canary grader guard failed for ids: {canary_guard_failures}")


if __name__ == "__main__":
    main()
