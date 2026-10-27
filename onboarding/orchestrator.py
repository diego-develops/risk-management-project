import logging
from uuid import uuid4

from onboarding.agents import (
    DocumentationAgent,
    Drafter,
    IdentityAgent,
    ResponseAgent,
    RiskAgent,
)
from onboarding.audit import AuditTrail, mask_document_id, mask_name
from onboarding.models import (
    Decision,
    InternalReview,
    OnboardingOutcome,
    OnboardingRequest,
    OnboardingResponse,
    OnboardingState,
)
from onboarding.policy import build_mitigation, evaluate
from onboarding.tools import ToolRegistry


class Orchestrator:
    """Agent0: fixed control flow, per-agent tool permissions, shared state."""

    name = "orchestrator"

    def __init__(
        self,
        tools: ToolRegistry | None = None,
        drafter: Drafter | None = None,
        logger: logging.Logger | None = None,
    ):
        self._tools = tools or ToolRegistry()
        self._identity = IdentityAgent()
        self._risk = RiskAgent()
        self._documentation = DocumentationAgent()
        self._response = ResponseAgent(drafter)
        self._logger = logger

    def start(self, request: OnboardingRequest) -> OnboardingOutcome:
        onboarding_id = str(uuid4())
        audit = AuditTrail(onboarding_id, self._logger)
        state = OnboardingState(onboarding_id, request, audit)
        audit.record(
            self.name, "onboarding_started",
            product=request.product,
            document_id=mask_document_id(request.document_id),
            prospect=mask_name(request.prospect_name),
        )

        # Identity and risk always both run: compliance wants the full picture.
        self._identity.run(state, self._tools)
        self._risk.run(state, self._tools)
        state.decision, state.reasons = evaluate(state.identity, state.risk)

        # Documents only matter when the customer can still proceed.
        if state.decision in (Decision.APROBADO, Decision.REQUIERE_INFO):
            self._documentation.run(state, self._tools)
            state.decision, state.reasons = evaluate(
                state.identity, state.risk,
                documentation_failed="prepare_documentation" in state.tool_errors,
            )

        state.mitigation = build_mitigation(state.decision, state.reasons)
        audit.record(
            self.name, "decision_made",
            decision=state.decision, reasons=state.reasons,
            escalation_ticket=state.mitigation.escalation_ticket if state.mitigation else None,
        )

        if state.mitigation:
            audit.record(
                self.name, "mitigation_proposed",
                causes=state.mitigation.causes, actions=state.mitigation.actions,
                owner=state.mitigation.owner,
            )

        self._response.run(state)

        return OnboardingOutcome(
            response=OnboardingResponse(
                onboarding_id=onboarding_id,
                decision=state.decision,
                customer_message=state.customer_message,
                required_documents=state.documents,
            ),
            review=InternalReview(
                onboarding_id=onboarding_id,
                decision=state.decision,
                reasons=state.reasons,
                mitigation=state.mitigation,
            ),
        )
