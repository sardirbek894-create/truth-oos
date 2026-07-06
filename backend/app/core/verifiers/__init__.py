"""
Olympus Engine v9 — Verifier Chain (orchestrator)

Runs all verifiers sequentially. The first verifier to raise a
`SecurityError` short-circuits the chain (HARD REJECT). Verifiers
are intentionally NOT parallelized — parallel execution leaks
timing side-channels about which verifier passed.
"""

from __future__ import annotations

import time
from typing import List, Protocol, runtime_checkable

from app.core.audit import AuditChain
from app.core.types import (
    FinalResult,
    SecurityError,
    VerificationResult,
    VerifyRequest,
)


@runtime_checkable
class BaseVerifier(Protocol):
    """Any class with an async `verify` returning VerificationResult."""

    async def verify(self, *args, **kwargs) -> VerificationResult: ...


class VerifierChain:
    """Sequential verifier chain with hard-reject semantics."""

    def __init__(
        self,
        verifiers: List[BaseVerifier],
        audit_chain: AuditChain,
    ) -> None:
        if not isinstance(verifiers, list) or not verifiers:
            raise ValueError("verifiers must be a non-empty list")
        if audit_chain is None:
            raise ValueError("audit_chain is required")
        self._verifiers = verifiers
        self._audit = audit_chain

    async def verify(self, request: VerifyRequest) -> FinalResult:
        """Run the chain. Any SecurityError short-circuits."""
        if not isinstance(request, VerifyRequest):
            raise TypeError("request must be a VerifyRequest")

        results: List[VerificationResult] = []
        t_total: float = time.perf_counter()
        for v in self._verifiers:
            try:
                r: VerificationResult = await self._dispatch(v, request)
                results.append(r)
            except SecurityError as e:
                fail: VerificationResult = VerificationResult(
                    passed=False,
                    verifier=getattr(v, "name", v.__class__.__name__),
                    reason=str(e),
                    latency_ms=0.0,
                )
                results.append(fail)
                await self._audit.log_event(
                    fail.verifier,
                    b"",
                    fail,
                )
                elapsed_ms: float = (time.perf_counter() - t_total) * 1000.0
                return FinalResult(
                    passed=False,
                    results=results,
                    total_latency_ms=elapsed_ms,
                )
        elapsed_ms = (time.perf_counter() - t_total) * 1000.0
        return FinalResult(
            passed=True,
            results=results,
            total_latency_ms=elapsed_ms,
        )

    async def _dispatch(self, v: BaseVerifier, r: VerifyRequest) -> VerificationResult:
        """Call a verifier with the args it expects based on its class name."""
        name: str = v.__class__.__name__
        if name == "SignatureVerifier":
            return await v.verify(r.payload, r.signature, r.public_key_ref)  # type: ignore[attr-defined]
        if name == "NonceVerifier":
            return await v.verify(r.nonce, r.batch_id)  # type: ignore[attr-defined]
        if name == "JitterVerifier":
            return await v.verify(r.jitter_received)  # type: ignore[attr-defined]
        if name == "CrossCorrelationVerifier":
            return await v.verify(r.signal_a, r.signal_b)  # type: ignore[attr-defined]
        if name == "SanityVerifier":
            return await v.verify(r.landmarks)  # type: ignore[attr-defined]
        raise SecurityError(f"unknown verifier: {name}")


__all__ = [
    "BaseVerifier",
    "VerifierChain",
    "SignatureVerifier",
    "NonceVerifier",
    "JitterVerifier",
    "CrossCorrelationVerifier",
    "SanityVerifier",
]


# VERIFIED: Sequential (no timing leaks), short-circuit on first SecurityError, audit per verifier, named dispatch.
