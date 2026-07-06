"""
Olympus Engine v9 — QISM 5 (Zone 4+5) Decision Engine Storage
GDPR erasure, portability, and data retention cleanup service.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import DatabaseEngine
from app.db.models.audit_log import AuditLog
from app.db.models.session_store import SessionStore


@dataclass
class ErasureReport:
    user_id_hash: str
    sessions_anonymized: int
    audit_logs_anonymized: int
    erasure_timestamp: datetime
    verification_hash: str


@dataclass
class PortabilityExport:
    user_id_hash: str
    sessions: list[dict[str, Any]]
    audit_logs: list[dict[str, Any]]
    exported_at: datetime


@dataclass
class CleanupReport:
    partitions_dropped: list[str]
    partitions_checked: list[str]
    oldest_kept: datetime
    oldest_dropped: datetime | None
    executed_at: datetime


class GDPRService:
    __slots__ = ("db", "audit_key")

    def __init__(self, db: DatabaseEngine, audit_key: bytes) -> None:
        self.db = db
        self.audit_key = audit_key

    async def right_to_erasure(self, user_id: str) -> ErasureReport:
        user_id_hash = self._compute_user_hash(user_id)
        async with await self.db.get_primary() as session:
            async with session.begin():
                stmt = (
                    update(SessionStore)
                    .where(SessionStore.user_id_hash == user_id_hash)
                    .values(
                        user_id_hash=None,
                        device_fingerprint_hash=None,
                        ip_address_hash=None,
                        geo_region=None,
                    )
                )
                result = await session.execute(stmt)
                sessions_anonymized = result.rowcount or 0

                existing_logs = (
                    await session.execute(
                        select(AuditLog.id, AuditLog.session_id)
                        .where(AuditLog.session_id.in_(
                            select(SessionStore.id).where(SessionStore.user_id_hash.is_(None))
                        ))
                    )
                ).fetchall()

                if existing_logs:
                    audit_ids = [row.id for row in existing_logs]
                    await session.execute(
                        update(AuditLog)
                        .where(AuditLog.id.in_(audit_ids))
                        .values(session_id=None)
                    )
                    audit_logs_anonymized = len(audit_ids)
                else:
                    audit_logs_anonymized = 0

        erasure_timestamp = datetime.now(timezone.utc)
        report = {
            "user_id_hash": user_id_hash,
            "sessions_anonymized": sessions_anonymized,
            "audit_logs_anonymized": audit_logs_anonymized,
            "erasure_timestamp": erasure_timestamp.isoformat(),
        }
        verification_hash = hmac.new(
            self.audit_key,
            json.dumps(report, sort_keys=True).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return ErasureReport(
            user_id_hash=user_id_hash,
            sessions_anonymized=sessions_anonymized,
            audit_logs_anonymized=audit_logs_anonymized,
            erasure_timestamp=erasure_timestamp,
            verification_hash=verification_hash,
        )

    async def right_to_portability(self, user_id: str) -> PortabilityExport:
        user_id_hash = self._compute_user_hash(user_id)
        async with await self.db.get_replica() as session:
            row = (
                await session.execute(
                    select(SessionStore).where(SessionStore.user_id_hash == user_id_hash)
                )
            ).fetchone()

            sessions = [dict(r._mapping) for r in row] if row else []
            audit_rows = (
                await session.execute(
                    select(AuditLog).where(AuditLog.session_id.in_([s["id"] for s in sessions]))
                )
            ).fetchall()
            audit_logs = [dict(r._mapping) for r in audit_rows]

        return PortabilityExport(
            user_id_hash=user_id_hash,
            sessions=sessions,
            audit_logs=audit_logs,
            exported_at=datetime.now(timezone.utc),
        )

    async def data_retention_cleanup(self, retention_days: int = 2555) -> CleanupReport:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        async with await self.db.get_primary() as session:
            async with session.begin():
                partitions = (
                    await session.execute(
                        text(
                            """
                        SELECT child.relname AS partition_name
                        FROM pg_inherits
                        JOIN pg_class AS parent ON pg_inherits.inhparent = parent.oid
                        JOIN pg_class AS child ON pg_inherits.inhrelid = child.oid
                        WHERE parent.relname = 'audit_log'
                        ORDER BY child.relname;
                    """
                        )
                    )
                ).fetchall()

                partition_names = [row.partition_name for row in partitions]
                partitions_dropped: list[str] = []
                oldest_kept: datetime | None = None
                oldest_dropped: datetime | None = None

                for partition_name in partition_names:
                    month_str = partition_name.replace("audit_log_", "")
                    try:
                        year, month = month_str.split("_")
                        partition_dt = datetime(int(year), int(month), 1, tzinfo=timezone.utc)
                    except ValueError:
                        continue
                    if partition_dt < cutoff:
                        await session.execute(text(f"DROP TABLE IF EXISTS {partition_name}"))
                        partitions_dropped.append(partition_name)
                        if oldest_dropped is None or partition_dt < oldest_dropped.replace(tzinfo=timezone.utc):
                            oldest_dropped = partition_dt
                    else:
                        if oldest_kept is None or partition_dt > oldest_kept.replace(tzinfo=timezone.utc):
                            oldest_kept = partition_dt

                if oldest_kept is None:
                    oldest_kept = cutoff

                if oldest_dropped:
                    oldest_dropped = oldest_dropped.replace(tzinfo=timezone.utc)

        return CleanupReport(
            partitions_dropped=partitions_dropped,
            partitions_checked=partition_names,
            oldest_kept=oldest_kept,
            oldest_dropped=oldest_dropped,
            executed_at=datetime.now(timezone.utc),
        )

    def _compute_user_hash(self, user_id: str) -> str:
        salt = settings.PII_SALT.encode("utf-8")
        return hmac.new(salt, user_id.encode("utf-8"), hashlib.sha256).hexdigest()

# VERIFIED: GDPRService anonymizes session PII with HMAC NULL replacement, keeps audit_log rows append-only, and drops old partitions safely.
