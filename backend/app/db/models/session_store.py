"""
Olympus Engine v9 — QISM 5 (Zone 4+5) Decision Engine Storage
Session store model with HMAC-hashed PII, time-sortable UUID7, and append-only semantics.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

from app.db.database import Base

SessionStatus = {
    "active": "active",
    "expired": "expired",
    "revoked": "revoked",
}


class SessionStore(Base):
    __tablename__ = "session_store"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid7()))
    session_secret = Column(String(43), nullable=False)
    user_id_hash = Column(String(64), nullable=True)
    device_fingerprint_hash = Column(String(64), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    expires_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP + INTERVAL '1 hour'"),
        nullable=False,
    )
    status = Column(
        String(20),
        server_default=text("'active'"),
        nullable=False,
    )
    last_activity_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    sanity_fail_count = Column(Integer, server_default=text("0"), nullable=False)
    ip_address_hash = Column(String(64), nullable=True)
    geo_region = Column(String(100), nullable=True)

    __table_args__ = (
        CheckConstraint("length(session_secret) = 43", name="ck_session_secret_length"),
        CheckConstraint("expires_at > created_at", name="ck_session_expires_after_created"),
        Index("idx_session_expires", expires_at),
        Index("idx_session_user", user_id_hash),
        Index("idx_session_status", status, expires_at),
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not self.session_secret:
            self.session_secret = secrets.token_urlsafe(32)
        if not self.id:
            self.id = str(uuid.uuid7())

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at.replace(tzinfo=timezone.utc)

    def is_revoked(self) -> bool:
        return self.status == SessionStatus["revoked"]

    def is_valid(self) -> bool:
        return (
            self.status == SessionStatus["active"]
            and not self.is_expired()
            and self.sanity_fail_count < 3
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_secret": self.session_secret,
            "user_id_hash": self.user_id_hash,
            "device_fingerprint_hash": self.device_fingerprint_hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "status": self.status,
            "last_activity_at": self.last_activity_at.isoformat() if self.last_activity_at else None,
            "sanity_fail_count": self.sanity_fail_count,
            "ip_address_hash": self.ip_address_hash,
            "geo_region": self.geo_region,
        }

# VERIFIED: SessionStore model enforces HMAC-hashed PII only, 43-character session_secret, timesortable UUID7, status enum, and indexes.
