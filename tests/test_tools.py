import pytest

from onboarding.tools import (
    ToolPermissionError,
    ToolRegistry,
    ToolTimeoutError,
    check_risk_lists,
    prepare_documentation,
    verify_identity,
)


def test_happy_path_document():
    assert verify_identity("1712345678") == {"verified": True, "confidence": 0.93}
    assert check_risk_lists("Juan Perez", "1712345678") == {"risk_level": "low", "matches": []}


def test_ambiguous_and_unverified_identity():
    assert verify_identity("1712345677")["confidence"] == 0.65
    assert verify_identity("1712345679")["verified"] is False


def test_high_and_medium_risk():
    assert check_risk_lists("x", "1712345676")["risk_level"] == "high"
    assert check_risk_lists("x", "1712345676")["matches"]
    assert check_risk_lists("x", "9612345678")["risk_level"] == "medium"


def test_timeouts():
    with pytest.raises(ToolTimeoutError):
        verify_identity("9912345678")
    with pytest.raises(ToolTimeoutError):
        check_risk_lists("x", "9812345678")


def test_documents_per_product_and_enhanced_due_diligence():
    base = prepare_documentation("cuenta_ahorros", {})["required_documents"]
    card = prepare_documentation("tarjeta_credito", {})["required_documents"]
    enhanced = prepare_documentation("cuenta_ahorros", {"risk_level": "medium"})["required_documents"]
    assert len(card) > len(base)
    assert "Declaración de origen de fondos" in enhanced
    assert "Declaración de origen de fondos" not in base


@pytest.mark.parametrize(
    "agent,tool,kwargs",
    [
        ("identity_agent", "check_risk_lists", {"name": "x", "document_id": "1712345678"}),
        ("risk_agent", "verify_identity", {"document_id": "1712345678"}),
        ("documentation_agent", "verify_identity", {"document_id": "1712345678"}),
        ("response_agent", "check_risk_lists", {"name": "x", "document_id": "1712345678"}),
        ("orchestrator", "verify_identity", {"document_id": "1712345678"}),
        ("unknown_agent", "verify_identity", {"document_id": "1712345678"}),
    ],
)
def test_agents_cannot_call_tools_outside_their_permissions(agent, tool, kwargs):
    with pytest.raises(ToolPermissionError):
        ToolRegistry().call(agent, tool, **kwargs)


def test_agent_can_call_its_own_tool():
    result = ToolRegistry().call("identity_agent", "verify_identity", document_id="1712345678")
    assert result["verified"] is True
