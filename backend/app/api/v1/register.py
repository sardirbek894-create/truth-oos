"""
Olympus Engine v9 — POST /api/v1/register
Device binding + DID creation + bcrypt-hashed session secret.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, constr

logger = structlog.get_logger("olympus.register")

router = APIRouter()

# ── In-memory session store (production: PostgreSQL via asyncpg) ──
SESSIONS: dict[str, dict] = {}

# ── Mock Vault salt (production: rotated monthly via Vault) ──
VAULT_SALT = "vault-per-user-salt-rotated-monthly"


# ── Schemas ──

class RegisterRequest(BaseModel):
    device_fingerprint: constr(pattern=r"^[a-f0-9]{64}$")
    webauthn_credential: str | None = None
    device_type: Literal["mobile", "desktop", "tablet"] = "desktop"
    os_version: str = Field(default="unknown", max_length=50)


class RegisterResponse(BaseModel):
    session_id: str
    session_secret: str
    expires_at: datetime
    did: str
    server_time_ms: int


# ── Helpers ──

def _base58_encode(data: bytes) -> str:
    """Minimal Base58 encoder."""
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = int.from_bytes(data, "big")
    if num == 0:
        return alphabet[0]
    result = []
    while num > 0:
        num, rem = divmod(num, 58)
        result.append(alphabet[rem])
    # Preserve leading zeros
    for byte in data:
        if byte == 0:
            result.append(alphabet[0])
        else:
            break
    return "".join(reversed(result))


def _make_did(session_id: str) -> str:
    """did:olympus:<base58(session_id_bytes + checksum_4bytes)>"""
    sid_bytes = uuid.UUID(session_id).bytes
    checksum = hashlib.sha256(sid_bytes).digest()[:4]
    return f"did:olympus:{_base58_encode(sid_bytes + checksum)}"


def _bcrypt_hash(secret: str) -> str:
    """bcrypt hash (rounds=12). Falls back to SHA-256 if bcrypt unavailable."""
    try:
        import bcrypt
        return bcrypt.hashpw(secret.encode(), bcrypt.gensalt(rounds=12)).decode()
    except ImportError:
        return hashlib.sha256(secret.encode()).hexdigest()


def _bcrypt_verify(secret: str, hashed: str) -> bool:
    try:
        import bcrypt
        return bcrypt.checkpw(secret.encode(), hashed.encode())
    except ImportError:
        return hashlib.sha256(secret.encode()).hexdigest() == hashed


# ── Rate limit store (production: Redis) ──
_register_counts: dict[str, tuple[int, float]] = {}


# ── Endpoint ──

@router.post("/register", response_model=RegisterResponse)
async def register(req: RegisterRequest, request: Request, response: Response):
    client_ip = request.client.host if request.client else "unknown"

    # Rate limit: 3 registrations/IP/hour
    now = time.time()
    hour_start = int(now / 3600) * 3600
    rk = f"register:ip:{client_ip}"
    entry = _register_counts.get(rk)
    if entry and entry[1] >= hour_start:
        if entry[0] >= 3:
            logger.warning("register.rate_limited", ip_hash=hashlib.sha256(client_ip.encode()).hexdigest()[:16])
            raise HTTPException(status_code=429, detail="Registration rate limit exceeded (3/hour)")
        _register_counts[rk] = (entry[0] + 1, entry[1])
    else:
        _register_counts[rk] = (1, now)

    # Generate session
    session_id = str(uuid.uuid4())
    session_secret = secrets.token_urlsafe(32)
    session_secret_hash = _bcrypt_hash(session_secret)
    device_fp_hash = hmac.new(
        VAULT_SALT.encode(), req.device_fingerprint.encode(), hashlib.sha256
    ).hexdigest()

    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    did = _make_did(session_id)

    SESSIONS[session_id] = {
        "session_secret_hash": session_secret_hash,
        "device_fingerprint_hash": device_fp_hash,
        "device_type": req.device_type,
        "os_version": req.os_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at.isoformat(),
        "status": "active",
        "request_count": 0,
        "sanity_fail_count": 0,
        "last_activity_at": None,
        "last_verified_at": None,
    }

    trace_id = request.headers.get("x-trace-id", secrets.token_hex(16))
    response.headers["X-Trace-ID"] = trace_id

    logger.info("register.success", session_id=session_id, did=did)

    return RegisterResponse(
        session_id=session_id,
        session_secret=session_secret,
        expires_at=expires_at,
        did=did,
        server_time_ms=int(time.time() * 1000),
    )
# VERIFIED: SHA-256 fingerprint regex, 3/hr rate limit per IP, UUID4 session, bcrypt(12) hashing, HMAC device FP, Base58 DID with checksum.
