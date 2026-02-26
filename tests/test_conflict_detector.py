from backend.conflict_detector import check_for_conflicts, extract_numeric_facts


def test_extract_numeric_facts_handles_word_durations():
    facts = extract_numeric_facts("Employees may roll over one week of PTO and 5 days of sick leave.")
    assert "1 week" in facts
    assert "5 days" in facts


def test_detects_cross_doc_conflict():
    chunks = [
        {
            "doc_id": "privacy.md",
            "chunk_id": "privacy.md#right-to-be-forgotten-deletion-sla",
            "text": "Upon receiving a formal deletion request, Loomo will purge data within 30 days.",
            "score": 1.0,
        },
        {
            "doc_id": "accounts.md",
            "chunk_id": "accounts.md#account-deletion-soft-delete-period",
            "text": "Accounts marked for deletion enter soft-delete for 45 days before permanent scrubbing.",
            "score": 0.8,
        },
    ]
    conflict = check_for_conflicts(chunks, question="How long until account deletion completes?")
    assert conflict is not None
    assert conflict["conflict"] is True
    assert conflict["sources"][0]["doc_id"] != conflict["sources"][1]["doc_id"]


def test_detects_within_doc_conflict_for_single_metric_question():
    chunks = [
        {
            "doc_id": "refunds.md",
            "chunk_id": "refunds.md#standard-refund-eligibility-window",
            "text": "Customers are eligible for a full refund within 14 days of purchase.",
            "score": 1.0,
        },
        {
            "doc_id": "refunds.md",
            "chunk_id": "refunds.md#enterprise-satisfaction-guarantee-window",
            "text": "Enterprise-tier customers have a 30-day satisfaction guarantee window for a full refund.",
            "score": 0.9,
        },
    ]
    conflict = check_for_conflicts(chunks, question="What is the refund window?")
    assert conflict is not None
    assert conflict["conflict"] is True


def test_tier_specific_refund_window_is_not_treated_as_conflict():
    chunks = [
        {
            "doc_id": "refunds.md",
            "chunk_id": "refunds.md#standard-refund-eligibility-window",
            "text": "Standard customers are eligible for a full refund within 14 days of purchase.",
            "score": 1.0,
        },
        {
            "doc_id": "refunds.md",
            "chunk_id": "refunds.md#enterprise-satisfaction-guarantee-window",
            "text": "Enterprise-tier customers have a 30-day satisfaction guarantee window for a full refund.",
            "score": 0.9,
        },
    ]
    conflict = check_for_conflicts(chunks, question="What is the refund window for Enterprise plan customers?")
    assert conflict is None


def test_skips_within_doc_conflict_for_multi_part_questions():
    chunks = [
        {
            "doc_id": "sla.md",
            "chunk_id": "sla.md#p1-escalation-policy",
            "text": "If a P1 incident is not resolved within 4 hours, the CTO must be paged directly.",
            "score": 1.0,
        },
        {
            "doc_id": "sla.md",
            "chunk_id": "sla.md#post-mortem-requirement",
            "text": "A post-mortem is required for P1 incidents within 72 hours of resolution.",
            "score": 0.9,
        },
    ]
    conflict = check_for_conflicts(
        chunks,
        question="If a P1 incident isn't resolved in 4 hours, what happens and what documentation is required afterward?",
    )
    assert conflict is None
