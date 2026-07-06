"""Integration test for the full verifier chain."""

import random
import pytest
from fakeredis.aioredis import FakeRedis

from app.core.audit import AuditChain
from app.core.types import (
    CrossCorrelationError,
    JitterError,
    NonceError,
    SanityError,
    SignatureError,
    VerifyRequest,
    VerificationResult,
)
from app.core.verifiers import VerifierChain
from app.core.verifiers.signature_verifier import SignatureVerifier
from app.core.verifiers.nonce_verifier import NonceVerifier
from app.core.verifiers.jitter_verifier import JitterVerifier
from app.core.verifiers.cross_correlation_verifier import (
    CrossCorrelationVerifier,
)
from app.core.verifiers.sanity_verifier import SanityVerifier
from app.utils.hsm_client import MockHSMClient


class _InMemoryPool:
    def __init__(self):
        self.rows: list[dict] = []

    def acquire(self):
        from tests.unit.test_audit_chain import _Conn
        return _Conn(self)


class _StubAudit:
    async def log_event(self, *args, **kwargs):
        return None


def _face(cx: int = 500, cy: int = 500, width: int = 200_000) -> list[tuple[int, int, int]]:
    half: int = width // 2
    return [
        (cx - half + (i * (width // 99)), cy - half + (i * (width // 99)), 0)
        for i in range(100)
    ]


def _signal() -> tuple[list[int], list[int]]:
    random.seed(1)
    a = [random.randint(0, 100) for _ in range(60)]
    b = [0] * 10 + a[:50]
    return a, b


async def _build_chain(audit):
    hsm = MockHSMClient()
    await hsm.initialize()
    await hsm.generate_keypair("session-key-1")
    redis = FakeRedis()
    sig = SignatureVerifier(hsm, audit)  # type: ignore[arg-type]
    non = NonceVerifier(redis, audit)  # type: ignore[arg-type]
    jit = JitterVerifier(50, audit)  # type: ignore[arg-type]
    cro = CrossCorrelationVerifier(audit_chain=audit)  # type: ignore[arg-type]
    san = SanityVerifier(audit_chain=audit)  # type: ignore[arg-type]
    return VerifierChain([sig, non, jit, cro, san], audit), hsm


@pytest.mark.asyncio
async def test_happy_path():
    audit = _StubAudit()
    chain, hsm = await _build_chain(audit)
    payload = b"hello"
    sig_bytes = await hsm.sign(payload, "session-key-1-pub")
    batch_id, nonces = await NonceVerifier(FakeRedis(), audit).generate_batch(3)  # type: ignore[arg-type]
    a, b = _signal()
    req = VerifyRequest(
        payload=payload,
        signature=sig_bytes,
        public_key_ref="session-key-1-pub",
        nonce=nonces[0],
        batch_id=batch_id,
        jitter_received=50,
        jitter_base=50,
        signal_a=a,
        signal_b=b,
        landmarks=_face(),
    )
    r = await chain.verify(req)
    assert r.passed is True


@pytest.mark.asyncio
async def test_signature_fail_short_circuits():
    audit = _StubAudit()
    chain, hsm = await _build_chain(audit)
    a, b = _signal()
    req = VerifyRequest(
        payload=b"hello",
        signature=b"\x00" * 64,
        public_key_ref="session-key-1-pub",
        nonce="n1",
        batch_id="b1",
        jitter_received=50,
        jitter_base=50,
        signal_a=a,
        signal_b=b,
        landmarks=_face(),
    )
    r = await chain.verify(req)
    assert r.passed is False
    # The first verifier failed, so the rest should not have been called.
    assert len(r.results) == 1


@pytest.mark.asyncio
async def test_jitter_fail():
    audit = _StubAudit()
    chain, hsm = await _build_chain(audit)
    payload = b"hi"
    sig_bytes = await hsm.sign(payload, "session-key-1-pub")
    redis = FakeRedis()
    batch_id, nonces = await NonceVerifier(redis, audit).generate_batch(3)  # type: ignore[arg-type]
    a, b = _signal()
    req = VerifyRequest(
        payload=payload,
        signature=sig_bytes,
        public_key_ref="session-key-1-pub",
        nonce=nonces[0],
        batch_id=batch_id,
        jitter_received=999,  # wrong
        jitter_base=50,
        signal_a=a,
        signal_b=b,
        landmarks=_face(),
    )
    r = await chain.verify(req)
    assert r.passed is False
