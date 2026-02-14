from copy import deepcopy

from backend.embedder import EMBEDDING_DIMENSIONS, embed_chunks, embed_text, semantic_search


REFUND_CHUNK = {
    "doc_id": "refunds.md",
    "chunk_id": "refunds.md#standard-refund-eligibility-window",
    "text": "Refund refund refund policy. Standard customers can request a refund within fourteen days.",
    "heading": "Standard Refund Eligibility Window",
    "doc_title": "Refunds",
    "search_text": "refund standard refund eligibility window refund policy fourteen days",
}

BILLING_CHUNK = {
    "doc_id": "billing.md",
    "chunk_id": "billing.md#invoice-schedule",
    "text": "Invoices are generated monthly and payment is due within fifteen days.",
    "heading": "Invoice Schedule",
    "doc_title": "Billing",
    "search_text": "billing invoice schedule monthly payment due fifteen days",
}

ONBOARDING_CHUNK = {
    "doc_id": "onboarding.md",
    "chunk_id": "onboarding.md#getting-started-checklist",
    "text": "Complete setup checklist and training during your first week.",
    "heading": "Getting Started Checklist",
    "doc_title": "Onboarding",
    "search_text": "onboarding getting started checklist setup training first week",
}


def _to_list(vec):
    if hasattr(vec, "tolist"):
        return vec.tolist()
    return list(vec)


def test_embed_text_dimensions_and_empty_input():
    emb = embed_text("refund policy")
    empty_emb = embed_text("")
    assert len(emb) == EMBEDDING_DIMENSIONS
    assert len(empty_emb) == EMBEDDING_DIMENSIONS


def test_embed_text_is_deterministic_for_identical_input():
    emb1 = _to_list(embed_text("same text every time"))
    emb2 = _to_list(embed_text("same text every time"))
    assert emb1 == emb2


def test_semantic_search_sorted_and_top_k():
    chunks = embed_chunks(deepcopy([REFUND_CHUNK, BILLING_CHUNK, ONBOARDING_CHUNK]))
    results = semantic_search("refund", chunks, top_k=2)
    assert len(results) == 2
    assert results[0]["semantic_score"] >= results[1]["semantic_score"]


def test_semantic_search_ranks_refund_chunk_above_billing():
    chunks = embed_chunks(deepcopy([REFUND_CHUNK, BILLING_CHUNK]))
    results = semantic_search("refund", chunks, top_k=2)
    assert results[0]["doc_id"] == "refunds.md"
