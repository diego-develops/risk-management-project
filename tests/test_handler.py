import json

import pytest

from onboarding.handler import handler

VALID = {"prospect_name": "Juan Perez", "document_id": "1712345678", "product": "cuenta_ahorros"}


def call(body, **kwargs):
    event = {"httpMethod": "POST", "path": "/api/v1/onboarding/start", "body": body}
    result = handler(event, **kwargs)
    return result["statusCode"], json.loads(result["body"])


def test_happy_path_returns_customer_view():
    status, body = call(json.dumps(VALID))
    assert status == 200
    assert body["decision"] == "APROBADO"
    assert set(body) == {"onboarding_id", "decision", "customer_message", "required_documents"}


@pytest.mark.parametrize("document_id,decision", [("1712345676", "ESCALADO"), ("1712345679", "RECHAZADO")])
def test_non_approved_still_hides_internal_data(document_id, decision):
    status, body = call(json.dumps({**VALID, "document_id": document_id}))
    assert status == 200 and body["decision"] == decision
    raw = json.dumps(body)
    for forbidden in ("RISK_", "reasons", "mitigation", "matches", "ESC-"):
        assert forbidden not in raw


@pytest.mark.parametrize("body", [None, "", "{not json"])
def test_bad_json_is_400(body):
    assert call(body) == (400, {"error": "invalid_json"})


def test_validation_error_is_422_and_does_not_echo_pii():
    status, body = call(json.dumps({**VALID, "document_id": "12345", "prospect_name": "Maria Secreta"}))
    assert status == 422
    assert {"field": "document_id", "type": "string_pattern_mismatch"} in body["details"]
    raw = json.dumps(body)
    assert "12345" not in raw and "Maria" not in raw


def test_missing_fields_are_422():
    status, body = call(json.dumps({}))
    assert status == 422
    assert {d["field"] for d in body["details"]} == {"prospect_name", "document_id", "product"}


def test_non_object_body_is_422():
    assert call("[1, 2]")[0] == 422


def test_unexpected_failure_is_generic_500():
    class Boom:
        def start(self, request):
            raise RuntimeError("secret detail 1712345678")

    status, body = call(json.dumps(VALID), orchestrator=Boom())
    assert (status, body) == (500, {"error": "internal_error"})
