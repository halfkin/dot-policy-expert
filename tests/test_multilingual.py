from starlette.requests import Request

import backend.app as app_module


def _build_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/chat",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "query_string": b"",
    }
    return Request(scope)


def _kb_chunks() -> list[dict]:
    return [
        {
            "doc_id": "refunds.md",
            "chunk_id": "refunds.md#standard-refund-eligibility-window",
            "text": "Standard customers are eligible for a full refund within 14 days of purchase.",
            "heading": "Standard Refund Eligibility Window",
            "doc_title": "Refunds",
            "search_text": "refunds standard refund eligibility window standard customers eligible full refund within 14 days purchase",
        },
        {
            "doc_id": "refunds.md",
            "chunk_id": "refunds.md#enterprise-satisfaction-guarantee-window",
            "text": "Enterprise customers are eligible for a full refund within 30 days of purchase.",
            "heading": "Enterprise Satisfaction Guarantee Window",
            "doc_title": "Refunds",
            "search_text": "refunds enterprise satisfaction guarantee window enterprise customers eligible full refund within 30 days purchase",
        },
        {
            "doc_id": "accounts.md",
            "chunk_id": "accounts.md#shared-login-policy",
            "text": "Shared logins are prohibited. Each user must have an individual account.",
            "heading": "Shared Login Policy",
            "doc_title": "Accounts",
            "search_text": "accounts shared login policy shared logins prohibited each user must have individual account",
        },
    ]


def _configure_llm_happy_path(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "USE_LLM", True)
    monkeypatch.setattr(app_module, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        app_module,
        "scan_input",
        lambda _text, use_llm_judge=False: {"status": "CLEAN", "blocked_by": None},
    )
    monkeypatch.setattr(app_module, "get_kb_chunks_cached", lambda: _kb_chunks())
    monkeypatch.setattr(app_module, "reformulate_query", lambda question, use_llm=True: question)
    monkeypatch.setattr(app_module, "check_for_conflicts", lambda _chunks, question="": None)
    monkeypatch.setattr(
        app_module,
        "call_openrouter",
        lambda question, sources, history=None: "You can request a refund based on plan-specific policy windows.",
    )


def test_french_input_translates_and_answers_in_llm_mode(monkeypatch):
    _configure_llm_happy_path(monkeypatch)
    monkeypatch.setattr(app_module, "check_language", lambda _text: "fr")

    calls: dict[str, str] = {}

    def fake_translate(text: str, source_lang: str) -> str:
        calls["text"] = text
        calls["source_lang"] = source_lang
        return "What is the refund policy for the Standard plan?"

    monkeypatch.setattr(app_module, "translate_to_english", fake_translate)

    response = app_module.chat(
        _build_request(),
        app_module.ChatRequest(question="Quelle est la politique de remboursement pour le plan Standard?"),
    )

    assert response.failure_bucket == "none"
    assert response.translated_from == "fr"
    assert response.original_query == "Quelle est la politique de remboursement pour le plan Standard?"
    assert "refund policy" in (response.retrieval_query or "").lower()
    assert calls == {
        "text": "Quelle est la politique de remboursement pour le plan Standard?",
        "source_lang": "fr",
    }


def test_spanish_input_translates_and_answers_in_llm_mode(monkeypatch):
    _configure_llm_happy_path(monkeypatch)
    monkeypatch.setattr(app_module, "check_language", lambda _text: "es")
    monkeypatch.setattr(
        app_module,
        "translate_to_english",
        lambda text, source_lang: "How many days do I have to get a refund on the Enterprise plan?",
    )

    response = app_module.chat(
        _build_request(),
        app_module.ChatRequest(question="¿Cuántos días tengo para obtener un reembolso en el plan Enterprise?"),
    )

    assert response.failure_bucket == "none"
    assert response.translated_from == "es"
    assert response.original_query == "¿Cuántos días tengo para obtener un reembolso en el plan Enterprise?"
    assert "enterprise" in (response.retrieval_query or "").lower()


def test_korean_input_is_rejected(monkeypatch):
    monkeypatch.setattr(app_module, "USE_LLM", True)
    monkeypatch.setattr(app_module, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(app_module, "check_language", lambda _text: "ko")

    response = app_module.chat(
        _build_request(),
        app_module.ChatRequest(question="이것은 한국어 질문입니다"),
    )

    assert response.failure_bucket == "unsupported_language"
    assert response.translated_from is None


def test_french_input_is_rejected_in_offline_mode(monkeypatch):
    monkeypatch.setattr(app_module, "USE_LLM", False)
    monkeypatch.setattr(app_module, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(app_module, "check_language", lambda _text: "fr")

    response = app_module.chat(
        _build_request(),
        app_module.ChatRequest(question="Je voudrais un remboursement"),
    )

    assert response.failure_bucket == "unsupported_language"
    assert response.translated_from is None


def test_translation_failure_rejects_gracefully(monkeypatch):
    monkeypatch.setattr(app_module, "USE_LLM", True)
    monkeypatch.setattr(app_module, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(app_module, "check_language", lambda _text: "fr")
    monkeypatch.setattr(
        app_module,
        "translate_to_english",
        lambda text, source_lang: (_ for _ in ()).throw(RuntimeError("translation failed")),
    )

    response = app_module.chat(
        _build_request(),
        app_module.ChatRequest(question="Je voudrais un remboursement"),
    )

    assert response.failure_bucket == "unsupported_language"
    assert "translate" in response.answer.lower()
