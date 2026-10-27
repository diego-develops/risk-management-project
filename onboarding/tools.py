"""Mocked tools and the registry that enforces which agent may call which tool.

Mock scenarios are driven by `document_id`:
  last digit 7   -> identity verified, confidence 0.65 (ambiguous)
  last digit 9   -> identity NOT verified, confidence 0.97
  last digit 6   -> risk high, with a match
  prefix 96      -> risk medium
  prefix 98      -> check_risk_lists times out
  prefix 99      -> verify_identity times out
  anything else  -> happy path (e.g. 1712345678)
"""

from collections.abc import Callable


class ToolError(Exception):
    """A tool failed; the orchestrator treats this as uncertainty, not a crash."""


class ToolTimeoutError(ToolError):
    pass


class ToolPermissionError(Exception):
    """An agent tried to use a tool it is not allowed to. A config bug, never swallowed."""


def verify_identity(document_id: str) -> dict:
    if document_id.startswith("99"):
        raise ToolTimeoutError("verify_identity timed out")
    last = document_id[-1]
    if last == "9":
        return {"verified": False, "confidence": 0.97}
    if last == "7":
        return {"verified": True, "confidence": 0.65}
    return {"verified": True, "confidence": 0.93}


def check_risk_lists(name: str, document_id: str) -> dict:
    if document_id.startswith("98"):
        raise ToolTimeoutError("check_risk_lists timed out")
    if document_id[-1] == "6":
        return {"risk_level": "high", "matches": ["PEP-MOCK-001"]}
    if document_id.startswith("96"):
        return {"risk_level": "medium", "matches": ["ADVERSE-MEDIA-MOCK-014"]}
    return {"risk_level": "low", "matches": []}


_BASE_DOCUMENTS = {
    "cuenta_ahorros": [
        "Cédula de identidad (copia)",
        "Planilla de servicio básico (máximo 3 meses)",
        "Formulario de apertura firmado",
    ],
    "cuenta_corriente": [
        "Cédula de identidad (copia)",
        "Planilla de servicio básico (máximo 3 meses)",
        "Formulario de apertura firmado",
        "Referencias bancarias o comerciales",
        "RUC o declaración de ingresos",
    ],
    "tarjeta_credito": [
        "Cédula de identidad (copia)",
        "Planilla de servicio básico (máximo 3 meses)",
        "Formulario de apertura firmado",
        "Rol de pagos o certificado de ingresos",
        "Autorización de consulta a buró de crédito",
    ],
}

_ENHANCED_DUE_DILIGENCE = [
    "Declaración de origen de fondos",
    "Certificado de actividad económica",
]


def prepare_documentation(product: str, client_data: dict) -> dict:
    documents = list(_BASE_DOCUMENTS[product])
    if client_data.get("risk_level") == "medium":
        documents += _ENHANCED_DUE_DILIGENCE
    return {"product": product, "required_documents": documents}


TOOLS: dict[str, Callable[..., dict]] = {
    "verify_identity": verify_identity,
    "check_risk_lists": check_risk_lists,
    "prepare_documentation": prepare_documentation,
}

PERMISSIONS: dict[str, frozenset[str]] = {
    "orchestrator": frozenset(),
    "identity_agent": frozenset({"verify_identity"}),
    "risk_agent": frozenset({"check_risk_lists"}),
    "documentation_agent": frozenset({"prepare_documentation"}),
    "response_agent": frozenset(),
}


class ToolRegistry:
    def __init__(
        self,
        tools: dict[str, Callable[..., dict]] | None = None,
        permissions: dict[str, frozenset[str]] | None = None,
    ):
        self._tools = tools if tools is not None else TOOLS
        self._permissions = permissions if permissions is not None else PERMISSIONS

    def call(self, agent: str, tool: str, **kwargs) -> dict:
        if tool not in self._permissions.get(agent, frozenset()):
            raise ToolPermissionError(f"{agent} is not allowed to call {tool}")
        return self._tools[tool](**kwargs)
