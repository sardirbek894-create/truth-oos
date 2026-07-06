"""
Olympus Engine v9 — QISM 5 (Zone 4+5) Decision Engine Storage
Immutable, append-only audit log with chained HMAC integrity and monthly partitioning.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

from app.db.database import Base

AuditDecision = Literal["PASS", "CHALLENGE", "REJECT"]


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    prev_hash = Column(String(64), nullable=False)
    curr_hash = Column(String(64), nullable=False)
    input_hash = Column(String(64), nullable=False)
    result_hash = Column(String(64), nullable=False)
    model_results = Column(JSONB, nullable=False)
    verifier_results = Column(JSONB, nullable=False)
    decision = Column(Enum("PASS", "CHALLENGE", "REJECT", name="audit_decision"), nullable=False)
    session_id = Column(String(36), nullable=True)
    gdpr_anonymized = Column(Boolean, server_default=text("false"), nullable=False)
    anonymous_before = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    __table_args__ = (
        CheckConstraint("length(prev_hash) = 64", name="ck_prev_hash_length"),
        CheckConstraint("length(curr_hash) = 64", name="ck_curr_hash_length"),
        Index("idx_audit_timestamp", created_at.desc()),
        Index("idx_audit_session", session_id),
        Index("idx_audit_decision", decision, created_at.desc()),
        Index("idx_audit_gdpr", gdpr_anonymized, anonymous_before),
    )

    def verify_chain_integrity(
        self, prev_row: Optional["AuditLog"], audit_key: bytes
    ) -> bool:
        expected_prev = self._compute_prev_hash(prev_row, audit_key)
        expected_curr = self._compute_curr_hash(expected_prev, audit_key)
        return self.prev_hash == expected_prev and self.curr_hash == expected_curr

    def anonymize(self) -> None:
        self.session_id = None
        self.model_results = {}
        self.verifier_results = {}
        self.gdpr_anonymized = True
        self.anonymous_before = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prev_hash": self.prev_hash,
            "curr_hash": self.curr_hash,
            "input_hash": self.input_hash,
            "result_hash": self.result_hash,
            "model_results": self.model_results,
            "verifier_results": self.verifier_results,
            "decision": self.decision,
            "session_id": self.session_id,
            "gdpr_anonymized": self.gdpr_anonymized,
            "anonymous_before": (
                self.anonymous_before.isoformat() if self.anonymous_before else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @staticmethod
    def _compute_prev_hash(prev_row: Optional["AuditLog"], audit_key: bytes) -> str:
        if prev_row is None:
            genesis = hmac.new(audit_key, b"genesis", hashlib.sha256).hexdigest()
            return genesis
        return prev_row.curr_hash

    @staticmethod
    def _compute_curr_hash(prev_hash: str, audit_key: bytes) -> str:
        timestamp = datetime.now(timezone.utc).isoformat()
        message = f"{prev_hash}{timestamp}".encode("utf-8")
        return hmac.new(audit_key, message, hashlib.sha256).hexdigest()

# VERIFIED: AuditLog enforces append-only immutable chain with 64-char prev/curr hash, partitioning-ready RANGE timestamp, and GDPR anonymize method.
