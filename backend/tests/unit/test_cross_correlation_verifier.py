"""Tests for the cross-correlation verifier."""

import pytest

from app.core.types import CrossCorrelationError
from app.core.verifiers.cross_correlation_verifier import CrossCorrelationVerifier


class _StubAudit:
    async def log_event(self, *args, **kwargs):
        return None


def _signal_with_delay(samples: int = 60, delay: int = 10) -> tuple[list[int], list[int]]:
    """Return (a, b) where b is a delayed copy of a (delay in samples)."""
    import random
    random.seed(42)
    a = [random.randint(0, 100) for _ in range(samples)]
    b = [0] * delay + a[: samples - delay]
    return a, b


@pytest.mark.asyncio
async def test_valid_delay():
    v = CrossCorrelationVerifier(audit_chain=_StubAudit())  # type: ignore[arg-type]
    a, b = _signal_with_delay(60, 10)
    r = await v.verify(a, b)
    assert r.passed is True


@pytest.mark.asyncio
async def test_delay_too_low():
    v = CrossCorrelationVerifier(audit_chain=_StubAudit())  # type: ignore[arg-type]
    a, b = _signal_with_delay(60, 1)  # 33ms delay in ms = 1 sample ~ 33ms (out of 5..15)
    with pytest.raises(CrossCorrelationError):
        await v.verify(a, b)


@pytest.mark.asyncio
async def test_delay_too_high():
    v = CrossCorrelationVerifier(audit_chain=_StubAudit())  # type: ignore[arg-type]
    a, b = _signal_with_delay(60, 25)  # ~833ms > 15
    with pytest.raises(CrossCorrelationError):
        await v.verify(a, b)


@pytest.mark.asyncio
async def test_delay_mismatch():
    v = CrossCorrelationVerifier(audit_chain=_StubAudit())  # type: ignore[arg-type]
    a, b = _signal_with_delay(60, 10)
    # Tamper b so secondary check mismatches.
    b_tampered = [0] * 30 + b[:30]
    with pytest.raises(CrossCorrelationError):
        await v.verify(a, b_tampered)


@pytest.mark.asyncio
async def test_insufficient_samples():
    v = CrossCorrelationVerifier(audit_chain=_StubAudit())  # type: ignore[arg-type]
    a = [0] * 20
    b = [0] * 20
    with pytest.raises(CrossCorrelationError):
        await v.verify(a, b)
