from typing import Protocol

from pydantic import BaseModel, ValidationError

from onboarding.models import (
    Decision,
    DocumentationResult,
    IdentityResult,
    OnboardingState,
    RiskResult,
)
from onboarding.tools import ToolError, ToolRegistry

_PRODUCT_LABELS = {
    "cuenta_ahorros": "cuenta de ahorros",
    "cuenta_corriente": "cuenta corriente",
    "tarjeta_credito": "tarjeta de crédito",
}


class _ToolAgent:
    name: str

    def _invoke[T: BaseModel](
        self,
        state: OnboardingState,
        tools: ToolRegistry,
        tool: str,
        model: type[T],
        **kwargs,
    ) -> T | None:
        """Call a tool and validate its output. Failures become uncertainty, not exceptions."""
        try:
            return model.model_validate(tools.call(self.name, tool, **kwargs))
        except (ToolError, ValidationError) as exc:
            state.tool_errors[tool] = type(exc).__name__
            state.audit.record(self.name, "tool_error", tool=tool, error=type(exc).__name__)
            return None


class IdentityAgent(_ToolAgent):
    name = "identity_agent"

    def run(self, state: OnboardingState, tools: ToolRegistry) -> None:
        state.identity = self._invoke(
            state, tools, "verify_identity", IdentityResult,
            document_id=state.request.document_id,
        )
        if state.identity:
            state.audit.record(
                self.name, "identity_checked",
                verified=state.identity.verified, confidence=state.identity.confidence,
            )


class RiskAgent(_ToolAgent):
    name = "risk_agent"

    def run(self, state: OnboardingState, tools: ToolRegistry) -> None:
        state.risk = self._invoke(
            state, tools, "check_risk_lists", RiskResult,
            name=state.request.prospect_name, document_id=state.request.document_id,
        )
        if state.risk:
            # Match contents stay out of the audit log; only the count is recorded.
            state.audit.record(
                self.name, "risk_checked",
                risk_level=state.risk.risk_level, match_count=len(state.risk.matches),
            )


class DocumentationAgent(_ToolAgent):
    name = "documentation_agent"

    def run(self, state: OnboardingState, tools: ToolRegistry) -> None:
        result = self._invoke(
            state, tools, "prepare_documentation", DocumentationResult,
            product=state.request.product,
            client_data={"risk_level": state.risk.risk_level if state.risk else None},
        )
        if result:
            state.documents = result.required_documents
            state.audit.record(self.name, "documentation_prepared", count=len(result.required_documents))


class Drafter(Protocol):
    def draft(self, decision: Decision, first_name: str, product: str, documents: list[str]) -> str: ...


class TemplateDrafter:
    """Deterministic Spanish templates. Swap for a Nova-backed drafter in the cloud step."""

    def draft(self, decision: Decision, first_name: str, product: str, documents: list[str]) -> str:
        label = _PRODUCT_LABELS[product]
        docs = "".join(f"\n- {d}" for d in documents)
        match decision:
            case Decision.APROBADO:
                return (
                    f"Hola {first_name}, tu solicitud de {label} fue aprobada preliminarmente. "
                    f"Para finalizar, presenta los siguientes documentos:{docs}"
                )
            case Decision.REQUIERE_INFO:
                tail = f" Por favor presenta:{docs}" if docs else ""
                return (
                    f"Hola {first_name}, necesitamos información adicional para continuar "
                    f"con tu solicitud de {label}.{tail}"
                )
            case Decision.ESCALADO:
                return (
                    f"Hola {first_name}, tu solicitud de {label} requiere una revisión adicional "
                    "de nuestro equipo. Te contactaremos en un plazo de 48 horas hábiles."
                )
            case Decision.RECHAZADO:
                return (
                    f"Hola {first_name}, no pudimos continuar con tu solicitud de {label} en línea. "
                    "Puedes acercarte a una agencia con tu documento original para validar tu identidad."
                )


class ResponseAgent:
    """Writes the customer message. Has no tools, so it cannot see risk-list data."""

    name = "response_agent"

    def __init__(self, drafter: Drafter | None = None):
        self._drafter = drafter or TemplateDrafter()

    def run(self, state: OnboardingState) -> None:
        state.customer_message = self._drafter.draft(
            state.decision,
            state.request.prospect_name.split()[0],
            state.request.product,
            state.documents,
        )
        state.audit.record(self.name, "message_drafted", decision=state.decision)
