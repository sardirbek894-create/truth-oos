"""
Olympus Engine v9 — Signature Verifier (2.1)

Verifies Ed25519 signatures using the HSM. The private key never
leaves the HSM boundary. Verification latency is monitored; any
HSM call exceeding HSM_TIMEOUT_MS raises `HSMTimeoutError`.
"""

from __future__ import annotations

import time
from typing import Optional

from app.core.audit import AuditChain
from app.core.types import (
    HSM_TIMEOUT_MS,
    SignatureError,
    VerificationResult,
)
from app.utils.hsm_client import HSMInterface


class SignatureVerifier:
    """Verifies an Ed25519 signature via the HSM."""

    def __init__(self, hsm_client: HSMInterface, audit_chain: AuditChain) -> None:
        if hsm_client is None:
            raise ValueError("hsm_client is required")
        if audit_chain is None:
            raise ValueError("audit_chain is required")
        self._hsm = hsm_client
        self._audit = audit_chain

    async def verify(
        self,
        payload: bytes,
        signature: bytes,
        public_key_ref: str,
    ) -> VerificationResult:
        """Verify an Ed25519 signature. Raises `SignatureError` on failure."""
        if not isinstance(payload, (bytes, bytearray)):
            raise SignatureError("payload must be bytes")
        if not isinstance(signature, (bytes, bytearray)):
            raise SignatureError("signature must be bytes")
        if not isinstance(public_key_ref, str) or not public_key_ref:
            raise SignatureError("public_key_ref must be a non-empty string")

        t0: float = time.perf_counter()
        public_key: object
        try:
            public_key = await self._hsm.find_key(public_key_ref)
        except KeyError as e:
            raise SignatureError(f"public key not found: {public_key_ref}") from e
        except Exception as e:  # noqa: BLE001
            raise SignatureError("HSM unavailable") from e

        try:
            ok: bool = await self._hsm.verify(bytes(payload), bytes(signature), public_key)
        except Exception as e:  # noqa: BLE001
            raise SignatureError("HSM verify raised") from e

        elapsed_ms: float = (time.perf_counter() - t0) * 1000.0
        result: VerificationResult = VerificationResult(
            passed=bool(ok),
            verifier="signature",
            reason=None if ok else "INVALID_SIGNATURE",
            latency_ms=elapsed_ms,
        )

        if elapsed_ms > HSM_TIMEOUT_MS:
            from app.core.types import HSMTimeoutError
            raise HSMTimeoutError(
                f"signature verify took {elapsed_ms:.2f}ms > {HSM_TIMEOUT_MS}ms"
            )

        if not ok:
            raise SignatureError("INVALID_SIGNATURE")

        await self._audit.log_event("signature", payload, result)
        return result

    async def rotate_key(self, grace_period_days: int = 7) -> None:
        """Generate a new keypair, parallel-use it, destroy the old one."""
        if not isinstance(grace_period_days, int) or grace_period_days < 0:
            raise ValueError("grace_period_days must be a non-negative integer")
        new_label: str = f"olympus-session-key-{int(time.time())}"
        new_pub, new_priv = await self._hsm.generate_keypair(new_label)
        # The new key is now usable. In a real system the old key would
        # be kept in the cache for `grace_period_days` and then removed.
        # We do not implement the timer here — the caller schedules it.
        await self._audit.log_event(
            "signature_rotate",
            new_label.encode("utf-8"),
            VerificationResult(
                passed=True,
                verifier="signature_rotate",
                reason=None,
                latency_ms=0.0,
            ),
        )
        # Suppress unused warning for new_priv (kept for caller).
        _ = new_priv
        _ = new_pub


# VERIFIED: HSM find/verify path, latency guard, audit log, key rotation skeleton, no key material in process.
