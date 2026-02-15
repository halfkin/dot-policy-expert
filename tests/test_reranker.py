import backend.reranker as reranker_module


def _sample_chunks() -> list[tuple[str, str, str, float]]:
    return [
        ("billing.md", "billing.md#invoice-schedule", "Invoices are due within 15 days.", 0.99),
        ("accounts.md", "accounts.md#shared-login-policy", "Shared logins are prohibited.", 0.95),
        (
            "refunds.md",
            "refunds.md#enterprise-satisfaction-guarantee-window",
            "Enterprise customers are eligible for a full refund within 30 days of purchase.",
            0.70,
        ),
        ("sla.md", "sla.md#uptime-commitment", "The SLA uptime target is 99.9%.", 0.65),
    ]


def test_reranker_improves_paraphrased_ranking(monkeypatch):
    class FakeModel:
        def predict(self, pairs):
            assert len(pairs) == 4
            return [0.12, 0.20, 0.98, 0.10]

    monkeypatch.setattr(reranker_module, "get_reranker", lambda: FakeModel())
    chunks = _sample_chunks()
    reranked = reranker_module.rerank(
        "What is the money-back window for enterprise customers?",
        chunks,
        top_k=3,
    )

    assert len(reranked) == 3
    assert reranked[0][1] == "refunds.md#enterprise-satisfaction-guarantee-window"


def test_reranker_fail_open(monkeypatch):
    monkeypatch.setattr(reranker_module, "get_reranker", lambda: None)
    chunks = _sample_chunks()
    reranked = reranker_module.rerank("refund policy", chunks, top_k=3)

    assert reranked == chunks[:3]


def test_reranker_disabled(monkeypatch):
    called = {"cross_encoder_called": False}

    def _cross_encoder_should_not_run(_model_name):
        called["cross_encoder_called"] = True
        raise AssertionError("CrossEncoder should not be initialized when reranker is disabled")

    monkeypatch.setattr(reranker_module, "RERANKER_ENABLED", False)
    monkeypatch.setattr(reranker_module, "HAS_CROSS_ENCODER", True)
    monkeypatch.setattr(reranker_module, "CrossEncoder", _cross_encoder_should_not_run)
    monkeypatch.setattr(reranker_module, "_model", None)
    monkeypatch.setattr(reranker_module, "_model_load_attempted", False)

    model = reranker_module.get_reranker()
    assert model is None
    assert called["cross_encoder_called"] is False


def test_reranker_preserves_good_rankings(monkeypatch):
    class FakeModel:
        def predict(self, pairs):
            assert len(pairs) == 4
            return [0.99, 0.35, 0.30, 0.15]

    monkeypatch.setattr(reranker_module, "get_reranker", lambda: FakeModel())
    chunks = _sample_chunks()
    reranked = reranker_module.rerank("When are invoices due?", chunks, top_k=3)

    assert len(reranked) == 3
    assert reranked[0][1] == "billing.md#invoice-schedule"
