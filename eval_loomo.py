"""
eval_loomo.py — Eval suite runner for Dot / Loomo KB.

Usage:
    python eval_loomo.py [--eval-file PATH] [--endpoint URL]
                         [--request-delay-seconds N] [--output PATH]

Reads eval_suite_loomo.json, POSTs each question to /chat, evaluates
pass/fail, and writes eval_results_loomo.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

try:
    import requests as _requests_lib
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    import urllib.request as _urllib_request

NOT_IN_SOURCES_PREFIX = "Not in sources"


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def post_chat(endpoint: str, question: str, timeout: int = 30) -> dict:
    payload = json.dumps({"question": question, "history": []}).encode("utf-8")
    url = endpoint.rstrip("/") + "/chat"
    api_key = os.getenv("DOT_API_KEY", "")
    if HAS_REQUESTS:
        resp = _requests_lib.post(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "X-API-Key": api_key},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    else:
        req = _urllib_request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "X-API-Key": api_key},
            method="POST",
        )
        with _urllib_request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Pass/fail evaluation
# ---------------------------------------------------------------------------

def evaluate(question: dict, response: dict) -> tuple[bool, str]:
    """
    Returns (passed, notes).

    Expected categories and their pass criteria:
      - grounded / answer:   failure_bucket == "none" AND expected doc_ids
                             appear in citations AND all key phrases present.
      - not_in_sources:      answer starts with "Not in sources"
      - conflict:            failure_bucket == "conflict_in_sources"
      - adversarial/blocked: failure_bucket == "blocked" or
                             "prompt_injection_blocked"
    """
    category = (question.get("category") or "").lower()
    expected_bucket = (question.get("expected_failure_bucket") or "").lower()
    expected_doc_ids = question.get("expected_doc_ids") or []
    key_phrases = question.get("key_phrases") or question.get("expected_key_phrases") or []

    actual_bucket = (response.get("failure_bucket") or "").lower()
    answer = response.get("answer", "")
    citations = response.get("citations") or []
    citation_doc_ids = {(c.get("doc_id") or "").strip() for c in citations if isinstance(c, dict)}

    notes_parts: list[str] = []

    # ------------------------------------------------------------------
    # "not_in_sources" category or expected bucket
    # ------------------------------------------------------------------
    if category == "not_in_sources" or expected_bucket == "not_in_sources":
        passed = answer.startswith(NOT_IN_SOURCES_PREFIX)
        if not passed:
            notes_parts.append(f"expected answer starting with '{NOT_IN_SOURCES_PREFIX}', got: {answer[:80]!r}")
        return passed, "; ".join(notes_parts) or "ok"

    # ------------------------------------------------------------------
    # "conflict" category
    # ------------------------------------------------------------------
    if category == "conflict" or expected_bucket == "conflict_in_sources":
        passed = actual_bucket == "conflict_in_sources"
        if not passed:
            notes_parts.append(f"expected failure_bucket=conflict_in_sources, got={actual_bucket!r}")
        return passed, "; ".join(notes_parts) or "ok"

    # ------------------------------------------------------------------
    # "adversarial" / "blocked" category — only if expected bucket is a
    # blocked variant.  Some adversarial tests (e.g. XSS stripped by
    # Layer 1) expect a grounded answer, so respect expected_bucket first.
    # ------------------------------------------------------------------
    if expected_bucket in ("blocked", "prompt_injection_blocked", "prompt_injection"):
        passed = actual_bucket in ("blocked", "prompt_injection_blocked")
        if not passed:
            notes_parts.append(f"expected blocked bucket, got={actual_bucket!r}")
        return passed, "; ".join(notes_parts) or "ok"

    if category in ("adversarial", "blocked") and expected_bucket not in ("none", "not_in_sources", "conflict_in_sources", "unsupported_language"):
        passed = actual_bucket in ("blocked", "prompt_injection_blocked")
        if not passed:
            notes_parts.append(f"expected blocked bucket, got={actual_bucket!r}")
        return passed, "; ".join(notes_parts) or "ok"

    # ------------------------------------------------------------------
    # "unsupported_language" expected bucket
    # ------------------------------------------------------------------
    if expected_bucket == "unsupported_language":
        passed = actual_bucket == "unsupported_language"
        if not passed:
            notes_parts.append(f"expected unsupported_language, got={actual_bucket!r}")
        return passed, "; ".join(notes_parts) or "ok"

    # ------------------------------------------------------------------
    # "grounded" / "answer" — the default case
    # ------------------------------------------------------------------
    # 1. Must have failure_bucket == "none"
    bucket_ok = actual_bucket == "none"
    if not bucket_ok:
        notes_parts.append(f"failure_bucket={actual_bucket!r} (expected 'none')")

    # 2. Citations must include all expected doc_ids
    doc_ids_ok = True
    if expected_doc_ids:
        missing_docs = [d for d in expected_doc_ids if d not in citation_doc_ids]
        if missing_docs:
            doc_ids_ok = False
            notes_parts.append(f"missing expected doc_ids={missing_docs}, got={sorted(citation_doc_ids)}")

    # 3. Answer must contain all expected key phrases (case-insensitive)
    phrases_ok = True
    if key_phrases:
        lower_answer = answer.lower()
        missing_phrases = [p for p in key_phrases if p.lower() not in lower_answer]
        if missing_phrases:
            phrases_ok = False
            notes_parts.append(f"missing key_phrases={missing_phrases}")

    passed = bucket_ok and doc_ids_ok and phrases_ok
    return passed, "; ".join(notes_parts) or "ok"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Loomo Dot eval suite runner")
    parser.add_argument(
        "--eval-file",
        default="eval_suite_loomo.json",
        help="Path to the eval suite JSON (default: eval_suite_loomo.json)",
    )
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:8000",
        help="Base URL of the Dot instance (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=0.5,
        help="Delay between requests in seconds (default: 0.5)",
    )
    parser.add_argument(
        "--output",
        default="eval_results_loomo.json",
        help="Output file path (default: eval_results_loomo.json)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Per-request timeout in seconds (default: 30)",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Load eval suite
    # ------------------------------------------------------------------
    eval_path = Path(args.eval_file)
    if not eval_path.exists():
        # Try common search locations
        search_roots = [
            Path.home() / "Downloads",
            Path.home() / "Desktop",
            Path.home() / "Coding",
        ]
        for root in search_roots:
            found = list(root.rglob("eval_suite_loomo.json")) if root.exists() else []
            if found:
                eval_path = found[0]
                print(f"[info] Found eval suite at: {eval_path}")
                break
        else:
            print(
                f"[ERROR] eval_suite_loomo.json not found at '{args.eval_file}' or in "
                f"~/Downloads, ~/Desktop, ~/Coding.\n"
                f"Place the file at '{args.eval_file}' and re-run.",
                file=sys.stderr,
            )
            sys.exit(1)

    questions: list[dict] = json.loads(eval_path.read_text(encoding="utf-8"))
    print(f"[info] Loaded {len(questions)} questions from {eval_path}")

    # ------------------------------------------------------------------
    # Check server is reachable
    # ------------------------------------------------------------------
    health_url = args.endpoint.rstrip("/") + "/health"
    try:
        if HAS_REQUESTS:
            health_resp = _requests_lib.get(health_url, timeout=5)
            health_resp.raise_for_status()
        else:
            with _urllib_request.urlopen(health_url, timeout=5) as r:
                r.read()
    except Exception as exc:
        print(
            f"\n[ERROR] Cannot reach Dot at {args.endpoint}: {exc}\n"
            f"\nTo start Dot locally, run:\n"
            f"    cd '{Path(__file__).parent}'\n"
            f"    source .venv/bin/activate\n"
            f"    uvicorn backend.app:app --host 127.0.0.1 --port 8000\n",
            file=sys.stderr,
        )
        sys.exit(2)

    # ------------------------------------------------------------------
    # Run eval
    # ------------------------------------------------------------------
    results: list[dict] = []
    by_category: dict[str, dict] = {}

    for i, q in enumerate(questions, start=1):
        qid = q.get("id", i)
        question_text = q.get("question", "")
        category = q.get("category", "unknown")
        expected_bucket = q.get("expected_failure_bucket", "")

        print(f"  [{i}/{len(questions)}] {qid}: {question_text[:60]}...", end="", flush=True)

        error_msg: str | None = None
        try:
            response = post_chat(args.endpoint, question_text, timeout=args.timeout)
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            response = {
                "answer": "",
                "citations": [],
                "failure_bucket": "retrieval_failed",
                "confidence": "low",
            }

        passed, notes = evaluate(q, response)
        status_icon = "✓" if passed else "✗"
        print(f" {status_icon}")

        actual_citations = [
            {"doc_id": c.get("doc_id", ""), "chunk_id": c.get("chunk_id", "")}
            for c in (response.get("citations") or [])
            if isinstance(c, dict)
        ]

        entry: dict = {
            "id": qid,
            "question": question_text,
            "category": category,
            "pass": passed,
            "actual_failure_bucket": response.get("failure_bucket", ""),
            "expected_failure_bucket": expected_bucket,
            "actual_citations": actual_citations,
            "expected_citations": q.get("expected_doc_ids", []),
            "notes": notes,
        }
        if error_msg:
            entry["error"] = error_msg

        results.append(entry)

        # Category tracking
        cat = by_category.setdefault(category, {"passed": 0, "total": 0})
        cat["total"] += 1
        if passed:
            cat["passed"] += 1

        if args.request_delay_seconds > 0:
            time.sleep(args.request_delay_seconds)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    total = len(results)
    passed_count = sum(1 for r in results if r["pass"])
    overall_pct = round(passed_count / total * 100, 1) if total else 0.0

    category_pass_rates = {
        cat: {
            "passed": stats["passed"],
            "total": stats["total"],
            "pass_rate_pct": round(stats["passed"] / stats["total"] * 100, 1) if stats["total"] else 0.0,
        }
        for cat, stats in sorted(by_category.items())
    }

    kb_files = sorted(p.name for p in Path("kb").glob("*.md")) if Path("kb").exists() else []

    fingerprint = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kb_files": kb_files,
        "total_questions": total,
        "passed": passed_count,
        "failed": total - passed_count,
        "endpoint": args.endpoint,
        "eval_file": str(eval_path),
    }

    output: dict = {
        "fingerprint": fingerprint,
        "overall_pass_rate_pct": overall_pct,
        "category_pass_rates": category_pass_rates,
        "results": results,
    }

    out_path = Path(args.output)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------
    # Print summary
    # ------------------------------------------------------------------
    print(f"\n{'='*50}")
    print(f"EVAL RESULTS — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")
    print(f"Overall: {passed_count}/{total} ({overall_pct}%)")
    print()
    print("By category:")
    for cat, stats in sorted(category_pass_rates.items()):
        pct = stats["pass_rate_pct"]
        bar = "✓" * stats["passed"] + "✗" * (stats["total"] - stats["passed"])
        print(f"  {cat:<25} {stats['passed']:>3}/{stats['total']:<3} ({pct:5.1f}%)  {bar}")

    failures = [r for r in results if not r["pass"]]
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for r in failures:
            print(f"  [{r['id']}] {r['question'][:60]}")
            print(f"         bucket={r['actual_failure_bucket']!r}, notes={r['notes']}")

    print(f"\nResults written to: {out_path.resolve()}")


if __name__ == "__main__":
    main()
