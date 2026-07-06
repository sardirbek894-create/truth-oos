"""Tests for the jitter verifier."""

import pytest

from app.core.types import JitterError
from app.core.verifiers.jitter_verifier import JitterVerifier


class _StubAudit:
    async def log_event(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_even_received():
    v = JitterVerifier(50, _StubAudit())  # type: ignore[arg-type]
    r = await v.verify(50)
    assert r.passed is True


@pytest.mark.asyncio
async def test_odd_received_adjusted():
    v = JitterVerifier(50, _StubAudit())  # type: ignore[arg-type]
    r = await v.verify(51)
    assert r.passed is True


@pytest.mark.asyncio
async def test_negative_odd():
    v = JitterVerifier(-50, _StubAudit())  # type: ignore[arg-type]
    r = await v.verify(-49)
    assert r.passed is True


@pytest.mark.asyncio
async def test_float_attack():
    v = JitterVerifier(50, _StubAudit())  # type: ignore[arg-type]
    with pytest.raises(JitterError):
        await v.verify(50.5)  # type: ignore[arg-value]


@pytest.mark.asyncio
async def test_unsafe_integer():
    v = JitterVerifier(50, _StubAudit())  # type: ignore[arg-type]
    with pytest.raises(JitterError):
        await v.verify(2 ** 53)


@pytest.mark.asyncio
async def test_invalid_base_odd():
    with pytest.raises(JitterError):
        JitterVerifier(51, _StubAudit())  # type: ignore[arg-type]
