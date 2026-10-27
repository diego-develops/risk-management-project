"""Deterministic decision matrix. The most restrictive finding wins."""

from uuid import uuid4

from onboarding.models import Decision, IdentityResult, Mitigation, RiskResult

IDENTITY_CONFIDENCE_THRESHOLD = 0.8

_SEVERITY = {
    Decision.APROBADO: 0,
    Decision.REQUIERE_INFO: 1,
    Decision.ESCALADO: 2,
    Decision.RECHAZADO: 3,
}

_ACTIONS = {
    "IDENTITY_UNAVAILABLE": "Reintentar la verificación de identidad; si persiste, solicitar validación presencial.",
    "IDENTITY_NOT_VERIFIED": "Rechazar la solicitud en línea y ofrecer verificación presencial en agencia con documento original.",
    "IDENTITY_AMBIGUOUS": "Escalar a revisión manual de identidad (cotejo de documento y selfie).",
    "IDENTITY_LOW_CONFIDENCE": "Escalar a revisión manual de identidad (cotejo de documento y selfie).",
    "RISK_UNAVAILABLE": "Reintentar la consulta de listas de riesgo; no avanzar sin resultado.",
    "RISK_HIGH": "Escalar a Cumplimiento para debida diligencia reforzada; no informar al cliente de las coincidencias.",
    "RISK_MEDIUM": "Solicitar declaración de origen de fondos y certificado de actividad económica.",
    "DOCUMENTATION_UNAVAILABLE": "Reintentar la preparación de documentación antes de contactar al cliente.",
}

_OWNERS = {
    Decision.REQUIERE_INFO: "Mesa de Onboarding",
    Decision.ESCALADO: "Oficial de Cumplimiento",
    Decision.RECHAZADO: "Mesa de Onboarding",
}


def evaluate(
    identity: IdentityResult | None,
    risk: RiskResult | None,
    documentation_failed: bool = False,
) -> tuple[Decision, list[str]]:
    findings: list[tuple[Decision, str]] = []

    if identity is None:
        findings.append((Decision.REQUIERE_INFO, "IDENTITY_UNAVAILABLE"))
    elif not identity.verified:
        if identity.confidence >= IDENTITY_CONFIDENCE_THRESHOLD:
            findings.append((Decision.RECHAZADO, "IDENTITY_NOT_VERIFIED"))
        else:
            findings.append((Decision.ESCALADO, "IDENTITY_AMBIGUOUS"))
    elif identity.confidence < IDENTITY_CONFIDENCE_THRESHOLD:
        findings.append((Decision.ESCALADO, "IDENTITY_LOW_CONFIDENCE"))

    if risk is None:
        findings.append((Decision.REQUIERE_INFO, "RISK_UNAVAILABLE"))
    elif risk.risk_level == "high":
        findings.append((Decision.ESCALADO, "RISK_HIGH"))
    elif risk.risk_level == "medium":
        findings.append((Decision.REQUIERE_INFO, "RISK_MEDIUM"))

    if documentation_failed:
        findings.append((Decision.REQUIERE_INFO, "DOCUMENTATION_UNAVAILABLE"))

    if not findings:
        return Decision.APROBADO, ["ALL_CHECKS_PASSED"]

    decision = max((d for d, _ in findings), key=_SEVERITY.__getitem__)
    return decision, [code for _, code in findings]


def build_mitigation(decision: Decision, reasons: list[str]) -> Mitigation | None:
    if decision is Decision.APROBADO:
        return None
    actions = list(dict.fromkeys(_ACTIONS[code] for code in reasons))
    ticket = f"ESC-{uuid4().hex[:8].upper()}" if decision is Decision.ESCALADO else None
    return Mitigation(
        causes=reasons,
        actions=actions,
        owner=_OWNERS[decision],
        escalation_ticket=ticket,
    )
