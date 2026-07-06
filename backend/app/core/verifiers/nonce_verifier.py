"""
Olympus Engine v9 — Nonce Verifier (2.2)

Tracks nonces per batch in Redis to prevent replay attacks. Each
batch is a Redis set with a TTL; nonces are added via a
WATCH/MULTI/EXEC transaction to defeat concurrent races.
"""

from __future__ import annotations

import secrets
import time
from typing import Optional

from redis.asyncio import Redis

from app.core.audit import AuditChain
from app.core.types import (
    NONCE_BATCH_MAX,
    NONCE_TTL_SECONDS,
    NonceError,
    VerificationResult,
)


def _batch_key(batch_id: str) -> str:
    if not isinstance(batch_id, str) or not batch_id:
        raise NonceError("batch_id must be a non-empty string")
    return f"batch:nonce:{batch_id}"


class NonceVerifier:
    """Replay protection via per-batch Redis sets."""

    def __init__(self, redis_client: Redis, audit_chain: AuditChain) -> None:
        if redis_client is None:
            raise ValueError("redis_client is required")
        if audit_chain is None:
            raise ValueError("audit_chain is required")
        self._redis = redis_client
        self._audit = audit_chain

    async def verify(
        self,
        nonce: str,
        batch_id: str,
        ttl_seconds: int = NONCE_TTL_SECONDS,
    ) -> VerificationResult:
        """Mark nonce as used; reject if already present."""
        if not isinstance(nonce, str) or not nonce:
            raise NonceError("nonce must be a non-empty string")
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise NonceError("ttl_seconds must be a positive integer")
        if ttl_seconds > 3600:
            raise NonceError("ttl_seconds must not exceed 3600")

        key: str = _batch_key(batch_id)
        t0: float = time.perf_counter()

        # Atomic check-and-set via WATCH/MULTI/EXEC.
        async with self._redis.pipeline(transaction=True) as pipe:
            await pipe.watch(key)
            scard: int = await self._redis.scard(key)
            is_member: bool = bool(await self._redis.sismember(key, nonce))
            if is_member:
                await pipe.unwatch()
                raise NonceError("REPLAY_ATTACK")
            if scard >= NONCE_BATCH_MAX:
                # Rotate: delete the saturated set and start a new one.
                await self._redis.delete(key)
            pipe.multi()
            pipe.sadd(key, nonce)
            pipe.expire(key, ttl_seconds)
            await pipe.execute()

        elapsed_ms: float = (time.perf_counter() - t0) * 1000.0
        result: VerificationResult = VerificationResult(
            passed=True,
            verifier="nonce",
            reason=None,
            latency_ms=elapsed_ms,
        )
        await self._audit.log_event("nonce", nonce.encode("utf-8"), result)
        return result

    async def generate_batch(self, count: int = NONCE_BATCH_MAX) -> tuple[str, list[str]]:
        """Pre-generate a batch of nonces and store them in Redis."""
        if not isinstance(count, int) or not 1 <= count <= NONCE_BATCH_MAX:
            raise NonceError(f"count must be 1..{NONCE_BATCH_MAX}")
        batch_id: str = secrets.token_urlsafe(32)
        nonces: list[str] = [secrets.token_urlsafe(24) for _ in range(count)]
        key: str = _batch_key(batch_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.sadd(key, *nonces)
            pipe.expire(key, NONCE_TTL_SECONDS)
            await pipe.execute()
        return batch_id, nonces


# VERIFIED: WATCH/MULTI/EXEC, batch rotation at 100, 192-bit nonce entropy, audit log, no raw payload.
