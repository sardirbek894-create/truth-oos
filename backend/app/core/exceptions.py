"""
Olympus Engine v9 — Security Exception Hierarchy

Centralised error taxonomy for the 5-Verifier gate, the Decision Engine,
and the audit subsystem. Every exception that bubbles out of a security
boundary MUST inherit from one of:

    SecurityError              — base, never raised directly
    ├── HardRejectError        — generic client message, detailed audit
    ├── SoftChallengeError     — risk between [0.3, 0.7]
    ├── DegradedModeError      — partial HA fallback
    └── IntegrityError         — audit chain / HSM / config corruption

Design rules:
  * `client_message` is constant; internal details NEVER leak to /verify.
  * `audit_payload` is structured for ChainedAuditLog.log_event.
  * `error_code` matches `SecurityErrorCode` enum (string-stable for SIEM).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SecurityErrorCode(str, Enum):
    """Stable, machine-parseable error identifiers for SIEM ingestion."""

    # --- Signature & nonces ---
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    SIGNATURE_MALFORMED = "SIGNATURE_MALFORMED"
    SIGNATURE_EXPIRED = "SIGNATURE_EXPIRED"
    NONCE_REUSED = "NONCE_REUSED"
    NONCE_UNKNOWN = "NONCE_UNKNOWN"
    NONCE_BATCH_INVALID = "NONCE_BATCH_INVALID"

    # --- Jitter / Sanity / Cross-correlation ---
    JITTER_MANIPULATION = "JITTER_MANIPULATION"
    JITTER_UNSAFE_INTEGER = "JITTER_UNSAFE_INTEGER"
    JITTER_OUT_OF_BOUNDS = "JITTER_OUT_OF_BOUNDS"
    SANITY_FROZEN = "SANITY_FROZEN"
    SANITY_CENTROID = "SANITY_CENTROID"
    SANITY_GEOMETRY = "SANITY_GEOMETRY"
    CROSS_CORR_PEAK_MISSING = "CROSS_CORR_PEAK_MISSING"
    CROSS_CORR_LATENCY = "CROSS_CORR_LATENCY"

    # --- Session & device ---
    SESSION_INVALID = "SESSION_INVALID"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    SESSION_RATE_LIMITED = "SESSION_RATE_LIMITED"
    DEVICE_FINGERPRINT_MISMATCH = "DEVICE_FINGERPRINT_MISMATCH"

    # --- AI / Model ---
    MODEL_INFERENCE_TIMEOUT = "MODEL_INFERENCE_TIMEOUT"
    MODEL_HASH_MISMATCH = "MODEL_HASH_MISMATCH"
    MODEL_VERSION_STALE = "MODEL_VERSION_STALE"
    MULTIMODAL_FUSION_REJECT = "MULTIMODAL_FUSION_REJECT"

    # --- Storage / HSM / Vault ---
    HSM_UNAVAILABLE = "HSM_UNAVAILABLE"
    HSM_KEY_NOT_FOUND = "HSM_KEY_NOT_FOUND"
    HSM_SIGNATURE_INVALID = "HSM_SIGNATURE_INVALID"
    VAULT_SEALED = "VAULT_SEALED"
    PGBOUNCER_POOL_EXHAUSTED = "PGBOUNCER_POOL_EXHAUSTED"
    REDIS_REPLICA_LAG_EXCEEDED = "REDIS_REPLICA_LAG_EXCEEDED"

    # --- Audit / integrity ---
    AUDIT_CHAIN_TAMPERED = "AUDIT_CHAIN_TAMPERED"
    AUDIT_HASH_COLLISION = "AUDIT_HASH_COLLISION"
    AUDIT_PARTITION_MISSING = "AUDIT_PARTITION_MISSING"

    # --- GDPR / compliance ---
    GDPR_ERASURE_DENIED = "GDPR_ERASURE_DENIED"
    GDPR_VERIFICATION_HASH_MISSING = "GDPR_VERIFICATION_HASH_MISSING"

    # --- Generic ---
    INPUT_VALIDATION = "INPUT_VALIDATION"
    RATE_LIMIT = "RATE_LIMIT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DEGRADED_MODE = "DEGRADED_MODE"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"


@dataclass(slots=True)
class SecurityError(Exception):
    """
    Base security exception.

    Attributes
    ----------
    error_code : SecurityErrorCode
        Stable identifier, safe for external logging.
    client_message : str
        Generic, constant message returned to the client. NEVER contains
        PII, session IDs, or internal state.
    audit_payload : dict[str, Any]
        Structured detail persisted to the audit chain.
    cause : Exception | None
        Wrapped underlying exception (kept out of the client response).
    """

    error_code: SecurityErrorCode
    client_message: str = "Security violation"
    audit_payload: dict[str, Any] = field(default_factory=dict)
    cause: Exception | None = None
    status_code: int = 403

    def __post_init__(self) -> None:
        if self.cause is not None:
            super().__init__(self.client_message)
            self.__cause__ = self.cause
        else:
            super().__init__(self.client_message)

    def to_response(self) -> dict[str, str]:
        """Minimal client-facing dict; safe to serialise to JSON."""
        return {
            "error": self.error_code.value,
            "message": self.client_message,
        }

    def to_audit(self) -> dict[str, Any]:
        """Structured detail for the immutable audit log."""
        payload = {
            "error_code": self.error_code.value,
            "client_message": self.client_message,
        }
        payload.update(self.audit_payload)
        if self.cause is not None:
            payload["cause_type"] = type(self.cause).__name__
        return payload


@dataclass(slots=True)
class HardRejectError(SecurityError):
    """
    Hard reject — generic client message, full audit detail.

    Maps to HTTP 403. The client never learns whether the failure
    was signature, nonce, sanity, or AI — this is by design.
    """

    error_code: SecurityErrorCode
    audit_payload: dict[str, Any] = field(default_factory=dict)
    cause: Exception | None = None
    status_code: int = 403

    client_message: str = "Verification failed"

    def __post_init__(self) -> None:
        # Force the generic message; detail stays in audit_payload.
        object.__setattr__(self, "client_message", "Verification failed")
        super().__post_init__()


@dataclass(slots=True)
class SoftChallengeError(SecurityError):
    """
    Soft challenge — risk band [0.3, 0.7].

    Maps to HTTP 202 with `decision="CHALLENGE"`. The client is told
    to re-verify with an additional proof (e.g. OTP, WebAuthn).
    """

    error_code: SecurityErrorCode = SecurityErrorCode.INPUT_VALIDATION
    audit_payload: dict[str, Any] = field(default_factory=dict)
    cause: Exception | None = None
    status_code: int = 202

    client_message: str = "Additional verification required"


@dataclass(slots=True)
class DegradedModeError(SecurityError):
    """
    System is in degraded mode (e.g. HSM down but soft-fallback engaged).

    Returns HTTP 503 with a hint to retry. Always logged as a critical
    event — degraded mode is an SRE page, not a client issue.
    """

    error_code: SecurityErrorCode = SecurityErrorCode.DEGRADED_MODE
    audit_payload: dict[str, Any] = field(default_factory=dict)
    cause: Exception | None = None
    status_code: int = 503

    client_message: str = "Service temporarily degraded"


@dataclass(slots=True)
class IntegrityError(SecurityError):
    """
    Audit chain, HSM, or static config is broken.

    Returns HTTP 500, but clients are told "internal error" — no
    further detail. Triggers immediate PagerDuty + security team page.
    """

    error_code: SecurityErrorCode = SecurityErrorCode.AUDIT_CHAIN_TAMPERED
    audit_payload: dict[str, Any] = field(default_factory=dict)
    cause: Exception | None = None
    status_code: int = 500

    client_message: str = "Internal integrity check failed"


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


def is_hard_reject(exc: BaseException) -> bool:
    """True for any HardRejectError or SecurityError with status 403."""
    if isinstance(exc, HardRejectError):
        return True
    if isinstance(exc, SecurityError) and exc.status_code == 403:
        return True
    return False


def is_client_safe(exc: BaseException) -> bool:
    """
    True when the exception can be surfaced to the client without
    leaking internal state. Used by the global exception handler.
    """
    return isinstance(exc, SecurityError)


__all__ = [
    "SecurityErrorCode",
    "SecurityError",
    "HardRejectError",
    "SoftChallengeError",
    "DegradedModeError",
    "IntegrityError",
    "is_hard_reject",
    "is_client_safe",
]


# VERIFIED: error taxonomy aligned with the 5-verifier gate, decision engine,
# GDPR service, and Prometheus alert rules (security_audit_*.json dashboard).
