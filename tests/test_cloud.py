import pytest

from onboarding import Decision
from onboarding.agents import TemplateDrafter
from onboarding.cloud import BedrockDrafter, KnowledgeBase, build_orchestrator
from onboarding.tools import prepare_documentation

DOCS = prepare_documentation("cuenta_ahorros", {})["required_documents"]


class FakeRuntime:
    def __init__(self, text=None, stop_reason="end_turn", error=None):
        self.text, self.stop_reason, self.error = text, stop_reason, error
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"stopReason": self.stop_reason, "output": {"message": {"content": [{"text": self.text}]}}}


class FakeAgentRuntime:
    def __init__(self, error=None):
        self.error = error

    def retrieve(self, **kwargs):
        if self.error:
            raise self.error
        return {"retrievalResults": [{"content": {"text": "Aprobado: informar aprobación preliminar."}}]}


def drafter(runtime, kb=None):
    return BedrockDrafter(runtime, "amazon.nova-lite-v1:0", "gr-123", "1", kb)


def draft(d, decision=Decision.APROBADO, docs=DOCS):
    return d.draft(decision, "Juan", "cuenta_ahorros", docs)


def good_text(docs=DOCS):
    return "¡Hola Juan! Tu cuenta de ahorros fue aprobada. Trae: " + "; ".join(docs)


@pytest.mark.parametrize("decision", list(Decision))
@pytest.mark.parametrize("product", ["cuenta_ahorros", "cuenta_corriente", "tarjeta_credito"])
def test_deterministic_template_always_passes_its_own_safety_check(decision, product):
    # The orchestrator only prepares documents for APROBADO / REQUIERE_INFO.
    with_docs = decision in (Decision.APROBADO, Decision.REQUIERE_INFO)
    docs = prepare_documentation(product, {"risk_level": "medium"})["required_documents"] if with_docs else []
    text = TemplateDrafter().draft(decision, "Juan", product, docs)
    assert BedrockDrafter._is_safe(text, decision, "Juan", docs)


def test_valid_rewrite_is_used():
    runtime = FakeRuntime(text=good_text())
    assert draft(drafter(runtime)) == good_text()


def test_converse_call_is_bounded_guarded_and_free_of_pii():
    runtime = FakeRuntime(text=good_text())
    draft(drafter(runtime, KnowledgeBase("kb-1", FakeAgentRuntime())))
    call = runtime.calls[0]
    assert call["inferenceConfig"]["maxTokens"] == 400
    assert call["guardrailConfig"] == {"guardrailIdentifier": "gr-123", "guardrailVersion": "1", "trace": "disabled"}
    prompt = call["messages"][0]["content"][0]["text"]
    assert "Juan" in prompt
    assert "Perez" not in prompt and "1712345678" not in prompt
    # KB policy is grounding for the model, kept out of the guardrail-evaluated user turn.
    assert any("Aprobado: informar" in block["text"] for block in call["system"])
    assert "Aprobado: informar" not in prompt


@pytest.mark.parametrize(
    "runtime",
    [
        FakeRuntime(text="Hola Juan, tu cuenta fue aprobada."),  # drops the documents
        FakeRuntime(text=good_text() + " Estás en una lista de riesgo."),  # leaks risk info
        FakeRuntime(text=good_text().replace("Juan", "Cliente")),  # drops the name
        FakeRuntime(text=good_text() + "\n\nSaludos cordiales,\n[Tu Nombre]"),  # unfilled placeholder
        FakeRuntime(text=good_text() + " {firma}"),
        FakeRuntime(text=""),
        FakeRuntime(text="x" * 2000),
        FakeRuntime(text=good_text(), stop_reason="guardrail_intervened"),
        FakeRuntime(error=TimeoutError("boom")),
    ],
)
def test_unsafe_or_failed_rewrite_falls_back_to_template(runtime):
    expected = TemplateDrafter().draft(Decision.APROBADO, "Juan", "cuenta_ahorros", DOCS)
    assert draft(drafter(runtime)) == expected


def test_escalation_message_must_keep_the_sla():
    template = TemplateDrafter().draft(Decision.ESCALADO, "Juan", "cuenta_ahorros", [])
    missing_sla = FakeRuntime(text="Hola Juan, revisaremos tu solicitud de cuenta de ahorros pronto.")
    assert draft(drafter(missing_sla), Decision.ESCALADO, []) == template
    with_sla = "Hola Juan, revisaremos tu solicitud y te contactaremos en 48 horas hábiles."
    assert draft(drafter(FakeRuntime(text=with_sla)), Decision.ESCALADO, []) == with_sla


def test_kb_failure_does_not_break_drafting():
    runtime = FakeRuntime(text=good_text())
    kb = KnowledgeBase("kb-1", FakeAgentRuntime(error=RuntimeError("down")))
    assert draft(drafter(runtime, kb)) == good_text()
    assert not any("Política de comunicación" in block["text"] for block in runtime.calls[0]["system"])


def test_without_bedrock_env_the_orchestrator_is_deterministic(monkeypatch):
    monkeypatch.delenv("MODEL_ID", raising=False)
    monkeypatch.delenv("GUARDRAIL_ID", raising=False)
    assert isinstance(build_orchestrator()._response._drafter, TemplateDrafter)
