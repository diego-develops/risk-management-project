from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from onboarding.audit import AuditTrail

Product = Literal["cuenta_ahorros", "cuenta_corriente", "tarjeta_credito"]


class Decision(StrEnum):
    APROBADO = "APROBADO"
    REQUIERE_INFO = "REQUIERE_INFO"
    ESCALADO = "ESCALADO"
    RECHAZADO = "RECHAZADO"


class OnboardingRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # Letters only: the first name is interpolated into an LLM prompt, so no free-form text.
    prospect_name: str = Field(
        min_length=2,
        max_length=120,
        pattern=r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’. -]*$",
    )
    document_id: str = Field(pattern=r"^\d{10}$")
    product: Product


class IdentityResult(BaseModel):
    verified: bool
    confidence: float = Field(ge=0.0, le=1.0)


class RiskResult(BaseModel):
    risk_level: Literal["low", "medium", "high"]
    matches: list[str] = Field(default_factory=list)


class DocumentationResult(BaseModel):
    required_documents: list[str]


class Mitigation(BaseModel):
    causes: list[str]
    actions: list[str]
    owner: str
    escalation_ticket: str | None = None


class OnboardingResponse(BaseModel):
    """Customer-facing view. No reason codes, mitigation or risk data: avoids tipping-off."""

    onboarding_id: str
    decision: Decision
    customer_message: str
    required_documents: list[str] = Field(default_factory=list)


class InternalReview(BaseModel):
    """Compliance/back-office view. Must never be returned to the customer."""

    onboarding_id: str
    decision: Decision
    reasons: list[str]
    mitigation: Mitigation | None = None


class OnboardingOutcome(BaseModel):
    response: OnboardingResponse
    review: InternalReview


@dataclass
class OnboardingState:
    onboarding_id: str
    request: OnboardingRequest
    audit: AuditTrail
    identity: IdentityResult | None = None
    risk: RiskResult | None = None
    documents: list[str] = field(default_factory=list)
    tool_errors: dict[str, str] = field(default_factory=dict)
    decision: Decision | None = None
    reasons: list[str] = field(default_factory=list)
    mitigation: Mitigation | None = None
    customer_message: str = ""
