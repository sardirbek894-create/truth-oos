"""Tests for the audit chain."""

import pytest

from app.core.audit import AuditChain, _genesis_hash
from app.core.types import VerificationResult
from app.utils.hsm_client import MockHSMClient


class _InMemoryPool:
    def __init__(self):
        self.rows: list[dict] = []

    def acquire(self):
        return _Conn(self)


class _Conn:
    def __init__(self, pool: _InMemoryPool):
        self._pool = pool

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def fetchrow(self, sql, *args):
        if not self._pool.rows:
            return None
        return self._pool.rows[-1]

    async def fetch(self, sql, *args):
        return list(self._pool.rows)

    async def execute(self, sql, *args):
        prev = self._pool.rows[-1]["curr_hash"] if self._pool.rows else _genesis_hash().hex()
        self._pool.rows.append(
            {
                "prev_hash": args[0],
                "curr_hash": args[1],
                "verifier": args[2],
                "input_hash": args[3],
                "result_hash": args[4],
                "timestamp_utc": args[5],
            }
        )


@pytest.mark.asyncio
async def test_chain_integrity_1000_entries():
    pool = _InMemoryPool()
    hsm = MockHSMClient()
    await hsm.initialize()
    chain = AuditChain(hsm, pool)  # type: ignore[arg-type]
    for i in range(1000):
        await chain.log_event("v", str(i).encode(), VerificationResult(True, "v"))
    assert await chain.verify_chain() is True


@pytest.mark.asyncio
async def test_tamper_detect():
    pool = _InMemoryPool()
    hsm = MockHSMClient()
    await hsm.initialize()
    chain = AuditChain(hsm, pool)  # type: ignore[arg-type]
    for i in range(5):
        await chain.log_event("v", str(i).encode(), VerificationResult(True, "v"))
    # Tamper with row 2.
    pool.rows[2]["verifier"] = "tampered"
    tampered = await chain.tamper_detect()
    assert 2 in tampered


@pytest.mark.asyncio
async def test_genesis_hash():
    pool = _InMemoryPool()
    hsm = MockHSMClient()
    await hsm.initialize()
    chain = AuditChain(hsm, pool)  # type: ignore[arg-type]
    ev = await chain.log_event("v", b"x", VerificationResult(True, "v"))
    assert ev.prev_hash == _genesis_hash().hex()
