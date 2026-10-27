"""Local demo: runs every mock scenario through the orchestrator."""

import logging

from onboarding import OnboardingRequest, Orchestrator

SCENARIOS = {
    "apto": "1712345678",
    "identidad ambigua (0.65)": "1712345677",
    "identidad no verificada": "1712345679",
    "riesgo high": "1712345676",
    "riesgo medium": "9612345678",
    "timeout riesgo": "9812345678",
    "timeout identidad": "9912345678",
}


def main() -> None:
    logging.disable(logging.CRITICAL)  # silence the JSON audit log in the demo
    orchestrator = Orchestrator()
    for label, document_id in SCENARIOS.items():
        outcome = orchestrator.start(
            OnboardingRequest(
                prospect_name="Juan Perez", document_id=document_id, product="cuenta_ahorros"
            )
        )
        review = outcome.review
        print(f"[{label}] {document_id} -> {review.decision} {review.reasons}")
        print(f"    cliente: {outcome.response.customer_message.splitlines()[0]}")
        if review.mitigation:
            print(f"    interno: {review.mitigation.model_dump(exclude_none=True)}")


if __name__ == "__main__":
    main()
