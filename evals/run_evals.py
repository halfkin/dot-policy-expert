from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys
import time
import urllib.request
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from evals.llm_judge import judge_response
except Exception:
    def judge_response(question: str, expected_answer: str, actual_answer: str) -> dict:  # type: ignore[no-redef]
        return {"score": -1, "reasoning": "Judge unavailable"}


_INPROCESS_CHAT = None
_INPROCESS_REQUEST = None
_INPROCESS_HTTP_REQUEST = None


def _build_inprocess_request():
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


def call_chat(api_url: str, question: str, timeout: int = 20, inprocess: bool = False) -> dict:
    if inprocess:
        global _INPROCESS_CHAT, _INPROCESS_REQUEST, _INPROCESS_HTTP_REQUEST
        if _INPROCESS_CHAT is None or _INPROCESS_REQUEST is None or _INPROCESS_HTTP_REQUEST is None:
            from backend.app import chat as inprocess_chat, ChatRequest  # local import for CLI startup speed
            _INPROCESS_CHAT = inprocess_chat
            _INPROCESS_REQUEST = ChatRequest
            _INPROCESS_HTTP_REQUEST = _build_inprocess_request()
        response_obj = _INPROCESS_CHAT(_INPROCESS_HTTP_REQUEST, _INPROCESS_REQUEST(question=question))
        return response_obj.model_dump()

    payload = json.dumps({"question": question}).encode("utf-8")
    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def _normalize_text(text: str) -> str:
    lower = (text or "").lower().replace("-", " ")
    lower = re.sub(r"\bone\b", "1", lower)
    lower = re.sub(r"\bof\b", " ", lower)
    lower = re.sub(r"\bdays\b", "day", lower)
    lower = re.sub(r"\bweeks\b", "week", lower)
    lower = re.sub(r"\bmonths\b", "month", lower)
    lower = re.sub(r"\byears\b", "year", lower)
    lower = re.sub(r"\s+", " ", lower).strip()
    return lower


def _term_match(term: str, haystack: str) -> bool:
    if not term:
        return True
    norm_term = _normalize_text(term)
    norm_hay = _normalize_text(haystack)

    if norm_term in norm_hay:
        return True

    words = [
        w
        for w in re.findall(r"[a-z0-9%$]+", norm_term)
        if w and w not in {"of", "the", "a", "an", "every"}
    ]
    if not words:
        return True

    glue = r"(?:\W+|(?:\s+(?:of|the|a|an|every)\s+))+"
    pattern = r"\b" + glue.join(re.escape(w) for w in words) + r"\b"
    return re.search(pattern, norm_hay) is not None


def _contains_all(text: str, required_terms: list[str]) -> bool:
    return all(_term_match(term, text) for term in required_terms)


def evaluate_result(question: dict, response: dict) -> tuple[bool, list[str]]:
    expected = question.get("expected_behavior")
    answer = response.get("answer", "")
    bucket = response.get("failure_bucket")
    required_terms = question.get("expected_answer_contains", [])
    diagnostics: list[str] = []

    if expected == "answer":
        has_required_terms = _contains_all(answer, required_terms)
        if not has_required_terms:
            missing = [term for term in required_terms if not _term_match(term, answer)]
            diagnostics.append(f"missing_expected_terms={missing}")

        disallowed_buckets = {
            "not_in_sources",
            "prompt_injection_blocked",
            "blocked",
            "conflict_in_sources",
            "retrieval_failed",
            "unsupported_language",
            "needs_clarification",
            "empty_input",
            "input_too_long",
            "rate_limited",
        }
        if bucket in disallowed_buckets:
            diagnostics.append(f"unexpected_failure_bucket={bucket}")

        return has_required_terms and bucket not in disallowed_buckets, diagnostics

    if expected == "not_in_sources":
        bucket_match = bucket in {"not_in_sources", "unsupported_language", "empty_input"}
        if not bucket_match:
            diagnostics.append("expected_not_in_sources_behavior")
        return bucket_match, diagnostics

    if expected == "blocked":
        passed = bucket == "prompt_injection_blocked"
        if not passed:
            diagnostics.append(f"expected_prompt_injection_blocked_got={bucket}")
        return passed, diagnostics

    if expected == "conflict":
        bucket_match = bucket == "conflict_in_sources"
        if not bucket_match:
            diagnostics.append(f"expected_conflict_in_sources_got={bucket}")

        conflict_details = response.get("conflict_details")
        citations = response.get("citations", [])

        evidence_parts = [answer]
        if isinstance(conflict_details, dict):
            evidence_parts.append(json.dumps(conflict_details))
        if isinstance(citations, list):
            evidence_parts.extend((c.get("quote", "") for c in citations if isinstance(c, dict)))
            evidence_parts.extend((c.get("chunk_id", "") for c in citations if isinstance(c, dict)))
        evidence_text = " ".join(evidence_parts)

        has_required_terms = _contains_all(evidence_text, required_terms)
        if not has_required_terms:
            missing = [term for term in required_terms if not _term_match(term, evidence_text)]
            diagnostics.append(f"missing_expected_terms={missing}")

        source_facts = []
        if isinstance(conflict_details, dict):
            for source in conflict_details.get("sources", []):
                if isinstance(source, dict):
                    source_facts.extend(source.get("facts", []))

        distinct_facts = {str(f).strip().lower() for f in source_facts if str(f).strip()}
        has_structured_conflict = len(distinct_facts) >= 2
        return bucket_match and (has_required_terms or has_structured_conflict), diagnostics

    if expected == "needs_clarification":
        passed = bucket in {"needs_clarification", "empty_input"}
        if not passed:
            diagnostics.append(f"expected_needs_clarification_got={bucket}")
        return passed, diagnostics

    if expected == "unsupported_language":
        passed = bucket == "unsupported_language"
        if not passed:
            diagnostics.append(f"expected_unsupported_language_got={bucket}")
        return passed, diagnostics

    diagnostics.append(f"unknown_expected_behavior={expected}")
    return False, diagnostics


def build_breakdown(entries: list[dict], field: str) -> dict:
    grouped: dict[str, dict] = {}
    counts = defaultdict(lambda: {"total": 0, "passed": 0})

    for entry in entries:
        key = entry.get(field, "unknown")
        counts[key]["total"] += 1
        if entry.get("answer_correct"):
            counts[key]["passed"] += 1

    for key, value in sorted(counts.items()):
        total = value["total"]
        passed = value["passed"]
        grouped[key] = {
            "passed": passed,
            "total": total,
            "pct": round((passed / total * 100.0), 1) if total else 0.0,
        }
    return grouped


def build_judge_breakdown(entries: list[dict], field: str) -> dict:
    grouped: dict[str, dict] = {}
    sums = defaultdict(lambda: {"count": 0, "score_total": 0.0})

    for entry in entries:
        score = entry.get("llm_judge", {}).get("score", -1)
        if score < 0:
            continue
        key = entry.get(field, "unknown")
        sums[key]["count"] += 1
        sums[key]["score_total"] += float(score)

    for key, value in sorted(sums.items()):
        count = value["count"]
        avg = (value["score_total"] / count) if count else 0.0
        grouped[key] = {
            "count": count,
            "avg_score": round(avg, 2),
        }
    return grouped


def save_results(repo_root: Path, payload: dict) -> tuple[Path, Path]:
    results_dir = repo_root / "evals" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_path = results_dir / f"eval-{timestamp}.json"
    run_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    latest_path = results_dir / "latest.json"
    if latest_path.exists() or latest_path.is_symlink():
        latest_path.unlink()
    latest_path.symlink_to(run_path.name)

    return run_path, latest_path


def _parse_expected_sources(question: dict) -> list[str]:
    raw = str(question.get("expected_source", "") or "")
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def _retrieval_hit(question: dict, response: dict) -> bool | None:
    expected_sources = _parse_expected_sources(question)
    if not expected_sources:
        return None

    citations = response.get("citations", [])
    citation_doc_ids = {
        c.get("doc_id", "").strip()
        for c in citations
        if isinstance(c, dict)
    }
    return any(source in citation_doc_ids for source in expected_sources)


def _diagnose(retrieval_hit: bool | None, answer_correct: bool) -> str:
    if retrieval_hit is None:
        return "not_applicable"
    if retrieval_hit and answer_correct:
        return "working_perfectly"
    if retrieval_hit and not answer_correct:
        return "generation_failure"
    if (not retrieval_hit) and answer_correct:
        return "lucky_guess"
    return "retrieval_failure"


def print_summary(
    summary: dict,
    by_behavior: dict,
    by_category: dict,
    failures: list[dict],
    run_path: Path,
    latest_path: Path,
    judge_summary: dict,
    judge_by_category: dict,
    failure_analysis: dict,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=== DOT EVAL RESULTS ===")
    print(f"Run: {now}")

    print("\nKEYWORD MATCH SCORING:")
    print(f"  Overall: {summary['passed']}/{summary['total']} ({summary['pct']}%)")
    print("  By expected_behavior:")
    for behavior, stats in by_behavior.items():
        print(f"    - {behavior}: {stats['passed']}/{stats['total']} ({stats['pct']}%)")
    print("  By category:")
    for category, stats in by_category.items():
        print(f"    - {category}: {stats['passed']}/{stats['total']} ({stats['pct']}%)")

    print("\nLLM JUDGE SCORING:")
    if judge_summary["count"] == 0:
        print("  Judge skipped or unavailable (no valid scores).")
    else:
        print(f"  Average score: {judge_summary['avg_score']}/3.0")
        d = judge_summary["distribution"]
        print(f"  Score distribution: 0={d.get(0,0)}, 1={d.get(1,0)}, 2={d.get(2,0)}, 3={d.get(3,0)}")
        if judge_by_category:
            print("  By category (avg):")
            for category, stats in judge_by_category.items():
                print(f"    - {category}: {stats['avg_score']} (n={stats['count']})")

    print("\nFAILURE ANALYSIS:")
    print(f"  Retrieval failures:  {failure_analysis['retrieval_failures']}")
    print(f"  Generation failures: {failure_analysis['generation_failures']}")
    print(f"  Lucky guesses:       {failure_analysis['lucky_guesses']}")

    if failures:
        print("\nDETAILED FAILURES:")
        for failure in failures:
            print(f"  #{failure['id']} [{failure['category']}] \"{failure['question']}\"")
            print(f"    Keyword match: FAIL ({', '.join(failure.get('diagnostics', [])) or 'no diagnostics'})")
            judge = failure.get("llm_judge", {})
            if judge:
                print(f"    LLM judge: {judge.get('score')}/3 ({judge.get('reasoning')})")
            print(f"    Retrieval: {'HIT' if failure.get('retrieval_hit') else 'MISS'}")
            print(f"    Diagnosis: {failure.get('diagnosis', 'unknown').upper()}")
            print(f"    Answer: {failure.get('answer_preview')}")
    else:
        print("\nDETAILED FAILURES:\n  none")

    print(f"\nSaved results: {run_path}")
    print(f"Updated latest symlink: {latest_path} -> {run_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run policy chatbot evals against /chat")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/chat", help="Chat endpoint URL")
    parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout seconds")
    parser.add_argument("--skip-judge", action="store_true", help="Skip LLM judge pass")
    parser.add_argument("--inprocess", action="store_true", help="Call backend.app chat in-process instead of HTTP")
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=0.0,
        help="Optional delay between requests to avoid tripping API rate limits",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    questions_path = repo_root / "evals" / "questions.json"
    questions = json.loads(questions_path.read_text(encoding="utf-8"))

    results: list[dict] = []
    failures: list[dict] = []

    for question in questions:
        qid = question["id"]
        qtext = question["question"]

        error = None
        try:
            response = call_chat(args.api_url, qtext, timeout=args.timeout, inprocess=args.inprocess)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            response = {
                "answer": "",
                "citations": [],
                "confidence": "low",
                "failure_bucket": "retrieval_failed",
            }

        answer_correct, diagnostics = evaluate_result(question, response)
        retrieval_hit = _retrieval_hit(question, response)
        diagnosis = _diagnose(retrieval_hit, answer_correct)

        expected_answer = ", ".join(question.get("expected_answer_contains", [])) or str(question.get("expected_behavior", ""))
        if args.skip_judge:
            llm_judge = {"score": -1, "reasoning": "Judge skipped by flag"}
        else:
            llm_judge = judge_response(qtext, expected_answer, response.get("answer", ""))

        entry = {
            "id": qid,
            "category": question.get("category"),
            "expected_behavior": question.get("expected_behavior"),
            "question": qtext,
            "expected_answer_contains": question.get("expected_answer_contains", []),
            "expected_source": question.get("expected_source"),
            "answer_correct": answer_correct,
            "retrieval_hit": retrieval_hit,
            "diagnosis": diagnosis,
            "failure_bucket": response.get("failure_bucket"),
            "answer": response.get("answer", ""),
            "citations": response.get("citations", []),
            "conflict_details": response.get("conflict_details"),
            "diagnostics": diagnostics,
            "llm_judge": llm_judge,
            "debug": response.get("debug"),
        }
        if error:
            entry["error"] = error

        results.append(entry)

        if not answer_correct:
            failures.append(
                {
                    "id": qid,
                    "category": question.get("category"),
                    "expected_behavior": question.get("expected_behavior"),
                    "question": qtext,
                    "expected_answer_contains": question.get("expected_answer_contains", []),
                    "failure_bucket": response.get("failure_bucket"),
                    "diagnostics": diagnostics,
                    "error": error,
                    "answer_preview": (response.get("answer", "")[:300] if not error else ""),
                    "retrieval_hit": retrieval_hit,
                    "diagnosis": diagnosis,
                    "llm_judge": llm_judge,
                }
            )

        if args.request_delay_seconds > 0:
            time.sleep(args.request_delay_seconds)

    total = len(results)
    passed = sum(1 for row in results if row["answer_correct"])
    summary = {
        "passed": passed,
        "total": total,
        "pct": round((passed / total * 100.0), 1) if total else 0.0,
    }

    by_behavior = build_breakdown(results, "expected_behavior")
    by_category = build_breakdown(results, "category")

    judge_valid_scores = [row["llm_judge"]["score"] for row in results if row.get("llm_judge", {}).get("score", -1) >= 0]
    judge_distribution = defaultdict(int)
    for score in judge_valid_scores:
        judge_distribution[int(score)] += 1
    judge_summary = {
        "count": len(judge_valid_scores),
        "avg_score": round(sum(judge_valid_scores) / len(judge_valid_scores), 2) if judge_valid_scores else -1,
        "distribution": dict(judge_distribution),
    }
    judge_by_category = build_judge_breakdown(results, "category")

    failure_analysis = {
        "retrieval_failures": sum(1 for row in results if row.get("diagnosis") == "retrieval_failure"),
        "generation_failures": sum(1 for row in results if row.get("diagnosis") == "generation_failure"),
        "lucky_guesses": sum(1 for row in results if row.get("diagnosis") == "lucky_guess"),
    }

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "api_url": "inprocess://backend.app.chat" if args.inprocess else args.api_url,
        "summary": summary,
        "by_expected_behavior": by_behavior,
        "by_category": by_category,
        "judge_summary": judge_summary,
        "judge_by_category": judge_by_category,
        "failure_analysis": failure_analysis,
        "failures": failures,
        "results": results,
        "config": {
            "skip_judge": args.skip_judge,
            "inprocess": args.inprocess,
            "openrouter_key_present": bool(os.getenv("OPENROUTER_API_KEY", "").strip()),
        },
    }

    run_path, latest_path = save_results(repo_root, payload)
    print_summary(
        summary,
        by_behavior,
        by_category,
        failures,
        run_path,
        latest_path,
        judge_summary,
        judge_by_category,
        failure_analysis,
    )


if __name__ == "__main__":
    main()
