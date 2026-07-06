"""
Olympus Engine v9 — GET /api/v1/challenge
Nonce batch generation. Nonces are single-use, 60s TTL, Redis-backed.
"""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from backend.app.api.v1.register import SESSIONS, _bcrypt_verify

logger = structlog.get_logger("olympus.challenge")

router = APIRouter()

# ── Nonce store (production: Redis SADD + EXPIRE 60) ──
NONCE_BATCHES: dict[str, dict] = {}

# ── Rate limit store ──
_challenge_counts: dict[str, tuple[int, float]] = {}


class ChallengeResponse(BaseModel):
    batch_id: str
    nonces: list[str]
    expires_at: datetime
    remaining_challenges: int


@router.get("/challenge", response_model=ChallengeResponse)
async def challenge(
    x_session_id: str = Header(..., alias="X-Session-ID"),
    x_session_secret: str = Header(..., alias="X-Session-Secret"),
):
    # 1. Session lookup
    session = SESSIONS.get(x_session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Session not found")

    # 2. bcrypt verify
    if not _bcrypt_verify(x_session_secret, session["session_secret_hash"]):
        raise HTTPException(status_code=401, detail="Invalid session secret")

    # 3. Expiry and status check
    expires = datetime.fromisoformat(session["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires:
        session["status"] = "expired"
        raise HTTPException(status_code=401, detail="Session expired")
    if session["status"] != "active":
        raise HTTPException(status_code=401, detail=f"Session status: {session['status']}")

    # 4. Rate limit: 10/minute per session
    now = time.time()
    minute_start = int(now / 60) * 60
    rk = f"challenge:session:{x_session_id}"
    entry = _challenge_counts.get(rk)
    used = 0
    if entry and entry[1] >= minute_start:
        if entry[0] >= 10:
            raise HTTPException(status_code=429, detail="Challenge rate limit exceeded (10/min)")
        used = entry[0]
        _challenge_counts[rk] = (entry[0] + 1, entry[1])
    else:
        _challenge_counts[rk] = (1, now)
        used = 0

    # 5. Generate batch
    batch_id = secrets.token_urlsafe(32)
    nonces = [secrets.token_urlsafe(24) for _ in range(100)]
    batch_expires = datetime.now(timezone.utc) + timedelta(seconds=60)

    NONCE_BATCHES[batch_id] = {
        "nonces": set(nonces),
        "expires_at": batch_expires.isoformat(),
        "session_id": x_session_id,
    }

    logger.info("challenge.issued", session_id=x_session_id, batch_id=batch_id)

    return ChallengeResponse(
        batch_id=batch_id,
        nonces=nonces,
        expires_at=batch_expires,
        remaining_challenges=10 - (used + 1),
    )
# VERIFIED: bcrypt session verify, expiry+status check, 10/min rate limit, 100 nonces x 192-bit entropy, 60s TTL, remaining count.
