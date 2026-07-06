"""Tests for the nonce verifier."""

import pytest
from fakeredis.aioredis import FakeRedis

from app.core.audit import AuditChain
from app.core.types import NonceError
from app.core.verifiers.nonce_verifier import NonceVerifier


class _StubAudit:
    async def log_event(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_valid_nonce():
    r = FakeRedis()
    v = NonceVerifier(r, _StubAudit())  # type: ignore[arg-type]
    result = await v.verify("nonce-1", "batch-1")
    assert result.passed is True


@pytest.mark.asyncio
async def test_replay_nonce_rejected():
    r = FakeRedis()
    v = NonceVerifier(r, _StubAudit())  # type: ignore[arg-type]
    await v.verify("nonce-1", "batch-1")
    with pytest.raises(NonceError):
        await v.verify("nonce-1", "batch-1")


@pytest.mark.asyncio
async def test_expired_batch_rejected():
    r = FakeRedis()
    v = NonceVerifier(r, _StubAudit())  # type: ignore[arg-type]
    # Manually delete the batch to simulate TTL expiry.
    await r.delete("batch:nonce:batch-x")
    with pytest.raises(NonceError):
        await v.verify("nonce-1", "batch-x")


@pytest.mark.asyncio
async def test_race_condition_atomic():
    r = FakeRedis()
    v = NonceVerifier(r, _StubAudit())  # type: ignore[arg-type]
    import asyncio
    results = await asyncio.gather(
        v.verify("nonce-1", "batch-race"),
        v.verify("nonce-1", "batch-race"),
        return_exceptions=True,
    )
    passed = sum(1 for r in results if not isinstance(r, Exception))
    rejected = sum(1 for r in results if isinstance(r, NonceError))
    assert passed == 1
    assert rejected == 1
