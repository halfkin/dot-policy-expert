from backend.app import (
    TOP_K,
    ConversationTurn,
    build_suggestions,
    check_language,
    get_confidence,
    is_likely_followup,
    score_chunk,
    select_top_sources,
    tokenize,
)


REFUND_CHUNK = {
    "doc_id": "refunds.md",
    "chunk_id": "refunds.md#standard-refund-eligibility-window",
    "text": "Standard Refund Eligibility Window Customers are eligible for a full refund within 14 days of their initial purchase.",
    "heading": "Standard Refund Eligibility Window",
    "doc_title": "Refunds",
    "search_text": "refunds standard refund eligibility window customers are eligible for a full refund within 14 days of their initial purchase",
}

BILLING_CHUNK = {
    "doc_id": "billing.md",
    "chunk_id": "billing.md#invoice-schedule",
    "text": "Invoice Schedule Invoices are generated on the 1st of each month and payment is due within 15 days.",
    "heading": "Invoice Schedule",
    "doc_title": "Billing",
    "search_text": "billing invoice schedule invoices are generated on the 1st of each month and payment is due within 15 days",
}

ACCOUNTS_CHUNK = {
    "doc_id": "accounts.md",
    "chunk_id": "accounts.md#account-suspension-policy",
    "text": "Accounts with overdue balances are suspended after 30 days of non-payment.",
    "heading": "Account Suspension Policy",
    "doc_title": "Accounts",
    "search_text": "accounts account suspension policy accounts with overdue balances are suspended after 30 days of non-payment",
}


def test_tokenize_basic_stopwords_and_refund():
    tokens = tokenize("What is the refund policy?")
    assert "what" not in tokens
    assert "is" not in tokens
    assert "the" not in tokens
    assert "refund" in tokens


def test_tokenize_plural_and_ss_behavior():
    assert "refund" in tokenize("refunds")
    assert "access" in tokenize("access")


def test_tokenize_mixed_alphanumeric_and_short_tokens():
    tokens = tokenize("401k x a")
    assert "401" in tokens
    assert "k" not in tokens
    assert "x" not in tokens
    assert "a" not in tokens



def test_score_chunk_refund_beats_billing_for_refund_question():
    question_tokens = tokenize("refund policy")
    phrases = ["refund policy"]
    refund_score = score_chunk(question_tokens, phrases, REFUND_CHUNK)
    billing_score = score_chunk(question_tokens, phrases, BILLING_CHUNK)
    assert refund_score > billing_score


def test_score_chunk_heading_boost():
    question_tokens = tokenize("standard")
    phrases = []
    heading_match_chunk = dict(REFUND_CHUNK)
    no_heading_match_chunk = dict(REFUND_CHUNK)
    no_heading_match_chunk["heading"] = "Eligibility Window"
    boosted = score_chunk(question_tokens, phrases, heading_match_chunk)
    not_boosted = score_chunk(question_tokens, phrases, no_heading_match_chunk)
    assert boosted > not_boosted


def test_score_chunk_irrelevant_is_zero():
    question_tokens = tokenize("stock price and ticker")
    phrases = ["stock price"]
    assert score_chunk(question_tokens, phrases, REFUND_CHUNK) == 0.0


def test_score_chunk_phrase_match_boost():
    question_tokens = tokenize("refund policy")
    no_phrase = score_chunk(question_tokens, [], REFUND_CHUNK)
    with_phrase = score_chunk(question_tokens, ["refund eligibility window"], REFUND_CHUNK)
    assert with_phrase > no_phrase


def test_get_confidence_thresholds():
    assert get_confidence(0.71) == "high"
    assert get_confidence(0.70) == "medium"
    assert get_confidence(0.41) == "medium"
    assert get_confidence(0.40) == "low"


def test_is_likely_followup_cases():
    history = [ConversationTurn(role="user", content="What is refund window?")]
    assert is_likely_followup("what about enterprise?", history) is True
    assert is_likely_followup("what about enterprise?", []) is False
    assert (
        is_likely_followup(
            "can you explain the enterprise refund policy in detail now please",
            history,
        )
        is False
    )
    assert is_likely_followup("it", history) is True


def test_check_language_english_or_none_and_short_none():
    english = check_language("What is the refund policy?")
    assert english in (None, "en")
    assert check_language("refund?") is None


def test_select_top_sources_caps_to_top_k():
    scored = [
        (0.95, REFUND_CHUNK),
        (0.90, BILLING_CHUNK),
        (0.85, ACCOUNTS_CHUNK),
        (0.80, {**REFUND_CHUNK, "chunk_id": "refunds.md#automated-refund-processing-cutoff"}),
        (0.75, {**BILLING_CHUNK, "chunk_id": "billing.md#accepted-payment-methods"}),
    ]
    selected = select_top_sources(scored, question="billing policy details", top_k=TOP_K)
    assert len(selected) <= TOP_K


def test_select_top_sources_prefers_doc_diversity_for_multipart():
    scored = [
        (0.95, REFUND_CHUNK),
        (0.90, {**REFUND_CHUNK, "chunk_id": "refunds.md#enterprise-satisfaction-guarantee-window"}),
        (0.85, BILLING_CHUNK),
        (0.80, ACCOUNTS_CHUNK),
    ]
    selected = select_top_sources(scored, question="billing and pto policy details", top_k=TOP_K)
    selected_docs = [chunk["doc_id"] for _, chunk in selected]
    assert len(selected) == TOP_K
    assert len(set(selected_docs)) == TOP_K


def test_build_suggestions_dedup_threshold_and_limit():
    scored = [
        (1.0, REFUND_CHUNK),
        (0.95, {**REFUND_CHUNK, "chunk_id": "refunds.md#standard-refund-eligibility-window-2"}),
        (0.09, BILLING_CHUNK),
        (0.10, ACCOUNTS_CHUNK),
        (0.70, {**BILLING_CHUNK, "heading": "Accepted Payment Methods", "chunk_id": "billing.md#accepted-payment-methods"}),
    ]
    suggestions = build_suggestions(scored, max_score=1.0, limit=2)
    assert len(suggestions) == 2
    assert suggestions[0].doc_id == "refunds.md"
    assert suggestions[0].heading == "Standard Refund Eligibility Window"
    assert all(s.heading != "Account Suspension Policy" for s in suggestions)
