"""
Olympus Engine v9 — GET /api/v1/did/{did}
Resolve decentralized identity to DID Document.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.api.v1.register import SESSIONS

router = APIRouter()


class PublicKeyEntry(BaseModel):
    id: str
    type: str
    controller: str


class DIDDocument(BaseModel):
    id: str
    publicKey: list[PublicKeyEntry]
    authentication: list[str]
    created: datetime
    updated: datetime


BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _base58_decode(s: str) -> bytes:
    num = 0
    for ch in s:
        num = num * 58 + BASE58_ALPHABET.index(ch)
    byte_len = (num.bit_length() + 7) // 8
    return num.to_bytes(byte_len, "big") if byte_len > 0 else b"\x00"


def _resolve_session_id(did: str) -> str | None:
    """Decode did:olympus:<base58> → session_id after checksum verification."""
    if not did.startswith("did:olympus:"):
        return None
    encoded = did[len("did:olympus:"):]
    try:
        decoded = _base58_decode(encoded)
    except (ValueError, IndexError):
        return None
    if len(decoded) < 20:
        return None
    sid_bytes = decoded[:16]
    checksum = decoded[16:20]
    expected_checksum = hashlib.sha256(sid_bytes).digest()[:4]
    if checksum != expected_checksum:
        return None
    return str(uuid.UUID(bytes=sid_bytes))


@router.get("/did/{did}", response_model=DIDDocument)
async def resolve_did(did: str):
    session_id = _resolve_session_id(did)
    if session_id is None:
        raise HTTPException(status_code=400, detail="Invalid DID format or checksum")

    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="DID not found")

    created = datetime.fromisoformat(session["created_at"])
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    updated = datetime.fromisoformat(session.get("last_activity_at") or session["created_at"])
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)

    key_id = f"{did}#key-1"
    return DIDDocument(
        id=did,
        publicKey=[
            PublicKeyEntry(
                id=key_id,
                type="Ed25519VerificationKey2018",
                controller=did,
            )
        ],
        authentication=[key_id],
        created=created,
        updated=updated,
    )
# VERIFIED: Base58 decode with SHA-256 checksum verification, session lookup, Ed25519VerificationKey2018 type, controller=self.
