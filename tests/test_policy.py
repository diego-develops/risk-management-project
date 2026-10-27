import pytest

from onboarding.models import Decision, IdentityResult, RiskResult
from onboarding.policy import build_mitigation, evaluate

OK_ID = IdentityResult(verified=True, confidence=0.93)
LOW_RISK = RiskResult(risk_level="low")


def test_all_clear_is_approved():
    assert evaluate(OK_ID, LOW_RISK) == (Decision.APROBADO, ["ALL_CHECKS_PASSED"])


@pytest.mark.parametrize("confidence", [0.0, 0.65, 0.79])
def test_low_confidence_escalates(confidence):
    decision, reasons = evaluate(IdentityResult(verified=True, confidence=confidence), LOW_RISK)
    assert decision is Decision.ESCALADO
    assert reasons == ["IDENTITY_LOW_CONFIDENCE"]


def test_threshold_is_inclusive_at_0_8():
    decision, _ = evaluate(IdentityResult(verified=True, confidence=0.8), LOW_RISK)
    assert decision is Decision.APROBADO


def test_not_verified_with_high_confidence_is_rejected():
    decision, reasons = evaluate(IdentityResult(verified=False, confidence=0.97), LOW_RISK)
    assert decision is Decision.RECHAZADO
    assert reasons == ["IDENTITY_NOT_VERIFIED"]


def test_not_verified_with_low_confidence_escalates():
    decision, _ = evaluate(IdentityResult(verified=False, confidence=0.4), LOW_RISK)
    assert decision is Decision.ESCALADO


def test_high_risk_escalates():
    decision, reasons = evaluate(OK_ID, RiskResult(risk_level="high", matches=["X"]))
    assert decision is Decision.ESCALADO
    assert reasons == ["RISK_HIGH"]


def test_medium_risk_requires_info():
    decision, _ = evaluate(OK_ID, RiskResult(risk_level="medium"))
    assert decision is Decision.REQUIERE_INFO


def test_tool_failures_require_info():
    assert evaluate(None, LOW_RISK)[0] is Decision.REQUIERE_INFO
    assert evaluate(OK_ID, None)[0] is Decision.REQUIERE_INFO
    assert evaluate(OK_ID, LOW_RISK, documentation_failed=True)[0] is Decision.REQUIERE_INFO


def test_most_restrictive_finding_wins_and_all_reasons_kept():
    decision, reasons = evaluate(
        IdentityResult(verified=False, confidence=0.97), RiskResult(risk_level="high")
    )
    assert decision is Decision.RECHAZADO
    assert reasons == ["IDENTITY_NOT_VERIFIED", "RISK_HIGH"]


def test_escalation_beats_missing_info():
    decision, _ = evaluate(None, RiskResult(risk_level="high"))
    assert decision is Decision.ESCALADO


def test_mitigation_only_when_not_approved():
    assert build_mitigation(Decision.APROBADO, ["ALL_CHECKS_PASSED"]) is None


def test_only_escalation_gets_a_ticket():
    escalated = build_mitigation(Decision.ESCALADO, ["RISK_HIGH"])
    assert escalated.escalation_ticket.startswith("ESC-")
    assert escalated.owner == "Oficial de Cumplimiento"
    assert build_mitigation(Decision.REQUIERE_INFO, ["RISK_MEDIUM"]).escalation_ticket is None
    assert build_mitigation(Decision.RECHAZADO, ["IDENTITY_NOT_VERIFIED"]).escalation_ticket is None


def test_duplicate_actions_are_collapsed():
    mitigation = build_mitigation(Decision.ESCALADO, ["IDENTITY_AMBIGUOUS", "IDENTITY_LOW_CONFIDENCE"])
    assert len(mitigation.actions) == 1
