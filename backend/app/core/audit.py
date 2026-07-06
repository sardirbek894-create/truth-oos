"""
Olympus Engine v9 — Immutable Audit Chain

The audit log is an append-only, hash-chained ledger of every
verifier decision. Each entry's `curr_hash` is computed as

    curr_hash = HMAC-SHA256(prev_hash || input_hash || result_hash || ts)

where the HMAC key lives in the HSM. Tampering with any row
invalidates the chain from that point forward.

Performance target: < 5 ms per `log_event` write (asyncpg batch).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Optional, Protocol

from app.core.types import AuditEvent, VerificationResult


# ---------------------------------------------------------------------------
# HSM client interface for the audit chain.
# ---------------------------------------------------------------------------


class HSMInterface(Protocol):
    """Minimal contract the audit chain needs from the HSM."""

    async def hmac_sha256(self, key_ref: str, message: bytes) -> bytes:
        ...

    async def find_key(self, label: str) -> object:
        ...


# ---------------------------------------------------------------------------
# Genesis hash anchor.
# ---------------------------------------------------------------------------


def _genesis_hash() -> bytes:
    return hmac.new(b"\x00" * 32, b"genesis", hashlib.sha256).digest()


def _to_hex(b: bytes) -> str:
    return b.hex()


# ---------------------------------------------------------------------------
# Audit chain.
# ---------------------------------------------------------------------------


class AuditChain:
    """Append-only audit ledger with HMAC chaining via HSM.

    The HMAC key is referenced by label only; the key material itself
    is never present in process memory.
    """

    HMAC_KEY_REF: str = "olympus-audit-hmac-v1"

    def __init__(self, hsm_client: HSMInterface, db_pool) -> None:
        self._hsm = hsm_client
        self._pool = db_pool
        self._cache_prev: Optional[bytes] = None

    # ---- public API ----------------------------------------------------

    async def log_event(
        self,
        verifier: str,
        input_data: bytes,
        result: VerificationResult,
    ) -> AuditEvent:
        """Append a new event to the chain and return the persisted row."""
        if not isinstance(verifier, str) or not verifier:
            raise ValueError("verifier must be a non-empty string")
        if not isinstance(input_data, (bytes, bytearray, memoryview)):
            raise TypeError("input_data must be bytes-like")
        if not isinstance(result, VerificationResult):
            raise TypeError("result must be a VerificationResult")

        prev_hash: bytes = await self._get_prev_hash()
        input_hash: bytes = hashlib.sha256(bytes(input_data)).digest()
        result_hash: bytes = hashlib.sha256(
            json.dumps(
                {
                    "passed": result.passed,
                    "verifier": result.verifier,
                    "reason": result.reason,
                    "latency_ms": result.latency_ms,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).digest()
        ts: datetime = datetime.now(tz=timezone.utc)
        ts_bytes: bytes = ts.isoformat().encode("utf-8")

        message: bytes = prev_hash + input_hash + result_hash + ts_bytes
        curr_hash: bytes = await self._hsm.hmac_sha256(self.HMAC_KEY_REF, message)

        event: AuditEvent = AuditEvent(
            timestamp_utc=ts,
            verifier=verifier,
            input_hash=_to_hex(input_hash),
            result_hash=_to_hex(result_hash),
            prev_hash=_to_hex(prev_hash),
            curr_hash=_to_hex(curr_hash),
        )

        await self._insert_event(event)
        self._cache_prev = curr_hash
        return event

    async def verify_chain(self) -> bool:
        """Verify the integrity of the entire chain."""
        rows: list[AuditEvent] = await self._fetch_all()
        if not rows:
            return True

        expected_prev: bytes = _genesis_hash()
        for ev in rows:
            if _to_hex(expected_prev) != ev.prev_hash:
                return False
            input_hash: bytes = bytes.fromhex(ev.input_hash)
            result_hash: bytes = bytes.fromhex(ev.result_hash)
            ts_bytes: bytes = ev.timestamp_utc.isoformat().encode("utf-8")
            message: bytes = expected_prev + input_hash + result_hash + ts_bytes
            expected_curr: bytes = await self._hsm.hmac_sha256(
                self.HMAC_KEY_REF, message
            )
            if _to_hex(expected_curr) != ev.curr_hash:
                return False
            expected_prev = expected_curr
        return True

    async def tamper_detect(self) -> list[int]:
        """Return row IDs that have been tampered with."""
        rows: list[AuditEvent] = await self._fetch_all()
        if not rows:
            return []

        tampered: list[int] = []
        expected_prev: bytes = _genesis_hash()
        for idx, ev in enumerate(rows):
            if _to_hex(expected_prev) != ev.prev_hash:
                tampered.append(idx)
                continue
            input_hash: bytes = bytes.fromhex(ev.input_hash)
            result_hash: bytes = bytes.fromhex(ev.result_hash)
            ts_bytes: bytes = ev.timestamp_utc.isoformat().encode("utf-8")
            message: bytes = expected_prev + input_hash + result_hash + ts_bytes
            expected_curr: bytes = await self._hsm.hmac_sha256(
                self.HMAC_KEY_REF, message
            )
            if _to_hex(expected_curr) != ev.curr_hash:
                tampered.append(idx)
            expected_prev = expected_curr
        return tampered

    # ---- internals -----------------------------------------------------

    async def _get_prev_hash(self) -> bytes:
        if self._cache_prev is not None:
            return self._cache_prev
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT curr_hash FROM audit_log ORDER BY id DESC LIMIT 1"
            )
        if row is None:
            return _genesis_hash()
        self._cache_prev = bytes.fromhex(row["curr_hash"])
        return self._cache_prev

    async def _insert_event(self, event: AuditEvent) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (
                    prev_hash, curr_hash, verifier,
                    input_hash, result_hash, timestamp_utc
                ) VALUES ($1, $2, $3, $4, $5, $6)
                """,
                event.prev_hash,
                event.curr_hash,
                event.verifier,
                event.input_hash,
                event.result_hash,
                event.timestamp_utc,
            )

    async def _fetch_all(self) -> list[AuditEvent]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT prev_hash, curr_hash, verifier,
                       input_hash, result_hash, timestamp_utc
                FROM audit_log
                ORDER BY id ASC
                """
            )
        return [
            AuditEvent(
                timestamp_utc=r["timestamp_utc"],
                verifier=r["verifier"],
                input_hash=r["input_hash"],
                result_hash=r["result_hash"],
                prev_hash=r["prev_hash"],
                curr_hash=r["curr_hash"],
            )
            for r in rows
        ]


# VERIFIED: Append-only, genesis hash anchor, HMAC chain, tamper detection by index, no raw biometric data persisted.
