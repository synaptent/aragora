"""Operational hooks for the foundation receipt models.

The receipt dataclasses live in the foundation layer, but signing, rendering,
compliance artifacts, provider detection and failure classification are
implemented in packages above it. The application facades register adapters
here from their own module init: ``aragora.gauntlet.receipt_models`` registers
all five, ``aragora.export.decision_receipt`` registers signing, and
``aragora.receipts`` imports both. Calling an operation that has no adapter
raises :class:`ReceiptOperationNotRegisteredError`; nothing degrades silently.

Adapters are objects whose attributes are looked up on every call, so
registering a module keeps ``mock.patch`` on that module effective.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, Protocol

__all__ = [
    "ComplianceGeneratorAdapter",
    "FailureClassifierAdapter",
    "ProviderDetectorAdapter",
    "ReceiptExporterAdapter",
    "ReceiptOperationNotRegisteredError",
    "ReceiptSigningAdapter",
    "all_responses_are_failures",
    "compliance_generator",
    "detect_provider",
    "receipt_exporters",
    "register_compliance_generator",
    "register_exporters",
    "register_failure_classifier",
    "register_provider_detector",
    "register_signing",
    "registered_operations",
    "sign_receipt",
    "signing_backend",
]

SIGNING = "signing"
EXPORTERS = "exporters"
COMPLIANCE = "compliance"
PROVIDER_DETECTION = "provider_detection"
FAILURE_CLASSIFICATION = "failure_classification"


class ReceiptOperationNotRegisteredError(RuntimeError):
    """An operational receipt hook was called before any facade registered it."""

    def __init__(self, operation: str) -> None:
        super().__init__(
            f"no adapter registered for receipt operation {operation!r}; import "
            "aragora.receipts (or aragora.gauntlet.receipt_models / "
            "aragora.export.decision_receipt) to register it"
        )
        self.operation = operation


class ReceiptSigningAdapter(Protocol):
    """Signing primitives, as provided by ``aragora.storage.receipt_signing``."""

    @property
    def HMACSigner(self) -> Any: ...

    @property
    def ReceiptSigner(self) -> Any: ...

    @property
    def SignatureMetadata(self) -> Any: ...

    @property
    def SignedReceipt(self) -> Any: ...

    @property
    def get_default_signer(self) -> Callable[[], Any]: ...


class ReceiptExporterAdapter(Protocol):
    """Renderers, as provided by ``aragora.gauntlet.receipt_exporters``."""

    @property
    def receipt_to_markdown(self) -> Callable[..., str]: ...

    @property
    def receipt_to_html(self) -> Callable[..., str]: ...

    @property
    def receipt_to_html_paginated(self) -> Callable[..., str]: ...

    @property
    def receipt_to_sarif(self) -> Callable[..., dict[str, Any]]: ...

    @property
    def receipt_to_csv(self) -> Callable[..., str]: ...


class ComplianceGeneratorAdapter(Protocol):
    """Builds a generator with ``generate(receipt_dict, frameworks=...)``."""

    def __call__(self, **kwargs: Any) -> Any: ...


class ProviderDetectorAdapter(Protocol):
    """Maps a model identifier to a provider name, or ``"unknown"``."""

    def __call__(self, model: str) -> str: ...


class FailureClassifierAdapter(Protocol):
    """True when every text is an agent failure placeholder (or there are none)."""

    def __call__(self, texts: Iterable[Any]) -> bool: ...


_adapters: dict[str, Any] = {}


def _adapter(operation: str) -> Any:
    try:
        return _adapters[operation]
    except KeyError:
        raise ReceiptOperationNotRegisteredError(operation) from None


def register_signing(adapter: ReceiptSigningAdapter) -> None:
    _adapters[SIGNING] = adapter


def register_exporters(adapter: ReceiptExporterAdapter) -> None:
    _adapters[EXPORTERS] = adapter


def register_compliance_generator(adapter: ComplianceGeneratorAdapter) -> None:
    _adapters[COMPLIANCE] = adapter


def register_provider_detector(adapter: ProviderDetectorAdapter) -> None:
    _adapters[PROVIDER_DETECTION] = adapter


def register_failure_classifier(adapter: FailureClassifierAdapter) -> None:
    _adapters[FAILURE_CLASSIFICATION] = adapter


def registered_operations() -> frozenset[str]:
    return frozenset(_adapters)


def signing_backend() -> ReceiptSigningAdapter:
    adapter: ReceiptSigningAdapter = _adapter(SIGNING)
    return adapter


def receipt_exporters() -> ReceiptExporterAdapter:
    adapter: ReceiptExporterAdapter = _adapter(EXPORTERS)
    return adapter


def compliance_generator(**kwargs: Any) -> Any:
    return _adapter(COMPLIANCE)(**kwargs)


def detect_provider(model: str) -> str:
    detected: str = _adapter(PROVIDER_DETECTION)(model)
    return detected


def all_responses_are_failures(texts: Iterable[Any]) -> bool:
    return bool(_adapter(FAILURE_CLASSIFICATION)(texts))


def sign_receipt(receipt: Any, signer: Any | None = None) -> Any:
    """Sign a receipt's ``to_dict()`` (or a mapping) and return the ``SignedReceipt``.

    Uses ``signer`` when given, otherwise the registered default signer.
    """
    if signer is None:
        signer = signing_backend().get_default_signer()
    payload = dict(receipt) if isinstance(receipt, Mapping) else receipt.to_dict()
    return signer.sign(payload)
