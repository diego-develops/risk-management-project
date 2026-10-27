"""AWS Lambda entrypoint for POST /api/v1/onboarding/start (API Gateway proxy integration)."""

import json
import logging

from pydantic import ValidationError

from onboarding.cloud import build_orchestrator
from onboarding.models import OnboardingRequest
from onboarding.orchestrator import Orchestrator

logger = logging.getLogger("onboarding.handler")
# Lambda's root logger defaults to WARNING, which would drop the audit trail.
logging.getLogger("onboarding.audit").setLevel(logging.INFO)

_orchestrator = build_orchestrator()


def _reply(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def handler(event: dict, context=None, orchestrator: Orchestrator | None = None) -> dict:
    try:
        payload = json.loads(event.get("body") or "")
    except json.JSONDecodeError:
        return _reply(400, {"error": "invalid_json"})

    try:
        request = OnboardingRequest.model_validate(payload)
    except ValidationError as exc:
        # Report field and error type only: pydantic's `input` would echo PII back.
        errors = [{"field": ".".join(map(str, e["loc"])), "type": e["type"]} for e in exc.errors()]
        return _reply(422, {"error": "validation_error", "details": errors})

    try:
        outcome = (orchestrator or _orchestrator).start(request)
    except Exception as exc:
        logger.error("onboarding_failed error=%s", type(exc).__name__)
        return _reply(500, {"error": "internal_error"})

    # Only the customer view leaves the Lambda; the review is already in the audit log.
    return _reply(200, outcome.response.model_dump(mode="json"))
