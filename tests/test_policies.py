"""Guards against drift between the policy documents (future KB content) and the code."""

import re
from pathlib import Path

import pytest

from onboarding import policy, tools

POLICIES = Path(__file__).parent.parent / "policies"
PRODUCTS = ["cuenta_ahorros", "cuenta_corriente", "tarjeta_credito"]


def bullets_under(path: Path, heading: str) -> list[str]:
    text = path.read_text(encoding="utf-8")
    section = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert section, f"{path.name} has no '## {heading}' section"
    return [line[2:].strip() for line in section.group(1).splitlines() if line.startswith("- ")]


@pytest.mark.parametrize("product", PRODUCTS)
def test_product_documents_match_tool(product):
    documented = bullets_under(POLICIES / f"politica_{product}.md", "Documentos requeridos")
    assert documented == tools.prepare_documentation(product, {})["required_documents"]


def test_enhanced_due_diligence_documents_match_tool():
    documented = bullets_under(POLICIES / "politica_debida_diligencia.md", "Documentos de debida diligencia reforzada")
    medium = tools.prepare_documentation("cuenta_ahorros", {"risk_level": "medium"})["required_documents"]
    assert medium[-len(documented):] == documented


def test_every_product_has_a_policy_and_vice_versa():
    assert {p.stem.removeprefix("politica_") for p in POLICIES.glob("politica_*.md")} - {
        "debida_diligencia", "comunicacion_cliente",
    } == set(PRODUCTS) == set(tools._BASE_DOCUMENTS)


def test_documented_confidence_threshold_matches_code():
    text = (POLICIES / "politica_debida_diligencia.md").read_text(encoding="utf-8")
    assert f"{policy.IDENTITY_CONFIDENCE_THRESHOLD}" in text
    for product in PRODUCTS:
        assert f"{policy.IDENTITY_CONFIDENCE_THRESHOLD}" in (POLICIES / f"politica_{product}.md").read_text(encoding="utf-8")


def test_policies_contain_no_real_looking_pii_or_internal_codes_for_customers():
    # The KB feeds the document-preparation agent; it must stay free of mock list data.
    for path in POLICIES.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert "PEP-MOCK" not in text and "ADVERSE-MEDIA" not in text
        assert not re.search(r"\b\d{10}\b", text), f"{path.name} contains a 10-digit number"
