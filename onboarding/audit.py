import json
import logging
from datetime import UTC, datetime

_default_logger = logging.getLogger("onboarding.audit")


def mask_document_id(document_id: str) -> str:
    if len(document_id) < 7:
        return "*" * len(document_id)
    return f"{document_id[:3]}{'*' * (len(document_id) - 6)}{document_id[-3:]}"


def mask_name(name: str) -> str:
    return " ".join(f"{part[0]}***" for part in name.split())


class AuditTrail:
    """Append-only JSON audit log for one onboarding.

    Callers must pass only already-masked or non-PII values in `details`.
    """

    def __init__(self, onboarding_id: str, logger: logging.Logger | None = None):
        self.onboarding_id = onboarding_id
        self.events: list[dict] = []
        self._logger = logger or _default_logger

    def record(self, agent: str, event: str, **details) -> None:
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "onboarding_id": self.onboarding_id,
            "agent": agent,
            "event": event,
            **details,
        }
        self.events.append(entry)
        self._logger.info(json.dumps(entry, ensure_ascii=False))
