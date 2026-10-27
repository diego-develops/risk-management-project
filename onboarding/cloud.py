"""Bedrock-backed pieces. The LLM only rewrites a deterministic message; it never decides."""

import logging
import os

from onboarding.agents import Drafter, TemplateDrafter
from onboarding.models import Decision
from onboarding.orchestrator import Orchestrator

logger = logging.getLogger("onboarding.cloud")

# The rewritten message must keep these facts or we fall back to the template.
_REQUIRED_PHRASES = {
    Decision.ESCALADO: ["48 horas hábiles"],
    Decision.RECHAZADO: ["agencia"],
}
# Anything hinting at risk-list data must never reach the customer, whatever the LLM says.
_FORBIDDEN_TERMS = ["riesgo", "lista", "cumplimiento", "sospech", "esc-", "pep", "sancion", "lavado"]

_SYSTEM_PROMPT = (
    "Eres el asistente de comunicaciones de un banco. Reescribes mensajes para prospectos "
    "en español, con tono cálido y breve. Reglas: conserva todos los datos del mensaje base, "
    "incluidos los nombres de documentos exactamente como están escritos; no agregues "
    "información nueva; nunca menciones listas, niveles de riesgo ni motivos internos. "
    "No agregues firma, despedida con nombre ni marcadores de posición entre corchetes."
)


class KnowledgeBase:
    """Retrieves policy snippets used to ground the rewrite. Failures are non-fatal."""

    def __init__(self, knowledge_base_id: str, client):
        self._kb_id = knowledge_base_id
        self._client = client

    def snippet(self, query: str, top_k: int = 2) -> str:
        try:
            result = self._client.retrieve(
                knowledgeBaseId=self._kb_id,
                retrievalQuery={"text": query},
                retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": top_k}},
            )
            return "\n---\n".join(r["content"]["text"] for r in result["retrievalResults"])
        except Exception as exc:
            logger.warning("kb_retrieve_failed error=%s", type(exc).__name__)
            return ""


class BedrockDrafter:
    def __init__(
        self,
        client,
        model_id: str,
        guardrail_id: str,
        guardrail_version: str,
        knowledge_base: KnowledgeBase | None = None,
        fallback: Drafter | None = None,
    ):
        self._client = client
        self._model_id = model_id
        self._guardrail = {
            "guardrailIdentifier": guardrail_id,
            "guardrailVersion": guardrail_version,
            "trace": "disabled",
        }
        self._kb = knowledge_base
        self._fallback = fallback or TemplateDrafter()

    def draft(self, decision: Decision, first_name: str, product: str, documents: list[str]) -> str:
        base = self._fallback.draft(decision, first_name, product, documents)
        try:
            text = self._rewrite(decision, base)
        except Exception as exc:
            logger.warning("llm_rewrite_failed error=%s", type(exc).__name__)
            return base
        if not self._is_safe(text, decision, first_name, documents):
            logger.warning("llm_rewrite_rejected decision=%s", decision)
            return base
        return text

    def _rewrite(self, decision: Decision, base: str) -> str:
        context = self._kb.snippet(f"mensaje al cliente cuando la solicitud es {decision}") if self._kb else ""
        # Bank policy goes in `system`: the guardrail does not evaluate it, and it would otherwise
        # block itself, since the policy text discusses the very topic the guardrail denies.
        system = [{"text": _SYSTEM_PROMPT}]
        if context:
            system.append({"text": f"Política de comunicación del banco:\n{context}"})
        response = self._client.converse(
            modelId=self._model_id,
            system=system,
            messages=[{"role": "user", "content": [{"text": f"Mensaje base:\n{base}"}]}],
            inferenceConfig={"maxTokens": 400, "temperature": 0.2},
            guardrailConfig=self._guardrail,
        )
        if response.get("stopReason") == "guardrail_intervened":
            raise RuntimeError("guardrail_intervened")
        return response["output"]["message"]["content"][0]["text"].strip()

    @staticmethod
    def _is_safe(text: str, decision: Decision, first_name: str, documents: list[str]) -> bool:
        lowered = text.lower()
        return (
            0 < len(text) <= 1200
            and not any(char in text for char in "[]{}<>")  # unfilled template placeholders
            and first_name in text
            and all(doc in text for doc in documents)
            and all(phrase in text for phrase in _REQUIRED_PHRASES.get(decision, []))
            and not any(term in lowered for term in _FORBIDDEN_TERMS)
        )


def build_orchestrator() -> Orchestrator:
    """Cloud wiring from environment; without Bedrock config it stays fully deterministic."""
    model_id = os.environ.get("MODEL_ID")
    guardrail_id = os.environ.get("GUARDRAIL_ID")
    if not (model_id and guardrail_id):
        return Orchestrator()

    import boto3
    from botocore.config import Config

    config = Config(retries={"max_attempts": 2, "mode": "adaptive"}, connect_timeout=3, read_timeout=10)
    runtime = boto3.client("bedrock-runtime", config=config)
    kb = None
    if kb_id := os.environ.get("KB_ID"):
        kb = KnowledgeBase(kb_id, boto3.client("bedrock-agent-runtime", config=config))
    drafter = BedrockDrafter(runtime, model_id, guardrail_id, os.environ.get("GUARDRAIL_VERSION", "1"), kb)
    return Orchestrator(drafter=drafter)
