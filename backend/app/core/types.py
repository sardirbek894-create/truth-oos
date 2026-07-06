"""
Olympus Engine v9 — Core Types

Foundation types for the verifier layer. All security-critical
verifiers return `VerificationResult` and raise `SecurityError` on
any failure. No bare booleans, no silent failures.

Security properties:
  - Integer-only constants.
  - Audit hash chain is append-only.
  - Every error path is explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Constants — all integer.
# ---------------------------------------------------------------------------

JITTER_MODULUS: int = 2
DELAY_MIN_MS: int = 5
DELAY_MAX_MS: int = 15
SANITY_CENTROID_MIN: int = 200  # 0.2 * 1000
SANITY_CENTROID_MAX: int = 800  # 0.8 * 1000
FROZEN_THRESHOLD_FRAMES: int = 60
FROZEN_MOVEMENT_THRESHOLD: int = 10  # 0.01 * 1000
FACE_WIDTH_MIN: int = 50
FACE_WIDTH_MAX: int = 400
SAFE_INT_LIMIT: int = 2 ** 53
HSM_TIMEOUT_MS: int = 100
NONCE_BATCH_MAX: int = 100
NONCE_TTL_SECONDS: int = 60


# ---------------------------------------------------------------------------
# Verification result.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Result of a single verifier. Immutable."""

    passed: bool
    verifier: str
    reason: Optional[str] = None
    latency_ms: float = 0.0
    audit_hash: str = ""


@dataclass(frozen=True, slots=True)
class FinalResult:
    """Result of the full verifier chain."""

    passed: bool
    results: list[VerificationResult] = field(default_factory=list)
    total_latency_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class VerifyRequest:
    """Top-level request passed into the verifier chain."""

    payload: bytes
    signature: bytes
    public_key_ref: str
    nonce: str
    batch_id: str
    jitter_received: int
    jitter_base: int
    signal_a: list[int]
    signal_b: list[int]
    landmarks: list[tuple[int, int, int]]


# ---------------------------------------------------------------------------
# Security error hierarchy.
# ---------------------------------------------------------------------------


class SecurityError(Exception):
    """Base class for all security errors. Hard-reject on any subclass."""

    code: str = "SECURITY_ERROR"

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.code)
        self.message = message or self.code


class SignatureError(SecurityError):
    code = "SIGNATURE_ERROR"


class NonceError(SecurityError):
    code = "NONCE_ERROR"


class JitterError(SecurityError):
    code = "JITTER_ERROR"


class CrossCorrelationError(SecurityError):
    code = "CROSS_CORRELATION_ERROR"


class SanityError(SecurityError):
    code = "SANITY_ERROR"


class HSMTimeoutError(SecurityError):
    code = "HSM_TIMEOUT"


# ---------------------------------------------------------------------------
# Audit.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One entry in the append-only audit chain."""

    timestamp_utc: datetime
    verifier: str
    input_hash: str
    result_hash: str
    prev_hash: str
    curr_hash: str


# VERIFIED: All constants integer; SecurityError hierarchy; VerificationResult frozen; no floats in security constants.
