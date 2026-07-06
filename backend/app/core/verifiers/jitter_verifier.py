"""
Olympus Engine v9 — Jitter Verifier (2.3)

IEEE 754 attack protection. Rejects any non-integer or unsafe
integer, computes the parity-adjusted comparison in pure integer
arithmetic, and treats every error as a hard reject.
"""

from __future__ import annotations

import secrets
import time
from typing import Optional

from app.core.audit import AuditChain
from app.core.types import (
    JITTER_MODULUS,
    SAFE_INT_LIMIT,
    JitterError,
    VerificationResult,
)


class JitterVerifier:
    """Verifies an integer jitter value against a base, integer-only."""

    def __init__(self, base_value: int, audit_chain: AuditChain) -> None:
        self._validate_base(base_value)
        if audit_chain is None:
            raise ValueError("audit_chain is required")
        self._base = base_value
        self._audit = audit_chain

    @staticmethod
    def _validate_base(value: int) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise JitterError("INVALID_BASE_VALUE: not an int")
        if abs(value) >= SAFE_INT_LIMIT:
            raise JitterError("INVALID_BASE_VALUE: unsafe integer")
        if value % JITTER_MODULUS != 0:
            raise JitterError("INVALID_BASE_VALUE: must be even")

    async def verify(self, received_value: int) -> VerificationResult:
        """Compare a received jitter value to the base."""
        # Type check first — this is the IEEE 754 attack vector.
        if isinstance(received_value, bool) or not isinstance(received_value, int):
            raise JitterError("IEEE_754_ATTACK_DETECTED: not a true int")
        if abs(received_value) >= SAFE_INT_LIMIT:
            raise JitterError("UNSAFE_INTEGER: exceeds 2^53")

        t0: float = time.perf_counter()
        # Parity adjustment.
        adjusted: int = (
            received_value
            if received_value % JITTER_MODULUS == 0
            else received_value - 1
        )
        passed: bool = adjusted == self._base
        elapsed_ms: float = (time.perf_counter() - t0) * 1000.0

        if not passed:
            raise JitterError("JITTER_MISMATCH")

        result: VerificationResult = VerificationResult(
            passed=True,
            verifier="jitter",
            reason=None,
            latency_ms=elapsed_ms,
        )
        await self._audit.log_event(
            "jitter",
            str(received_value).encode("utf-8"),
            result,
        )
        return result

    async def generate_challenge(self) -> int:
        """Generate a fresh even base value (≤ 31 random bits × 2)."""
        return secrets.randbits(31) * 2


# VERIFIED: bool/int discrimination, 2^53 guard, parity adjustment, base even, audit log, no float.
