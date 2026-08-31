from __future__ import annotations

from typing import Any


class HarnessError(Exception):
    """Base error with a stable machine-readable code."""

    code = "harness_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ValidationHarnessError(HarnessError):
    code = "validation_error"


class NotFoundError(HarnessError):
    code = "not_found"


class ConflictError(HarnessError):
    code = "conflict"


class ExportBlockedError(HarnessError):
    code = "export_blocked"


class ProviderError(HarnessError):
    code = "provider_error"


class ProviderConfigurationError(ProviderError):
    code = "provider_configuration_error"


class ProviderTemporaryError(ProviderError):
    code = "provider_temporary_error"


class ProviderPermanentError(ProviderError):
    code = "provider_permanent_error"

