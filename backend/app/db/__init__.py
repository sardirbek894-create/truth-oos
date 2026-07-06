"""
Olympus Engine v9 — Database layer package.

Exposes the primary entry points for application code:
  - `DatabaseEngine`: primary/replica routing, PgBouncer pool, health check.
  - `RedisClient`:    Sentinel-aware Redis master/replica + Streams.
  - `PoolMonitor`:    PgBouncer / PostgreSQL / Redis health monitoring.
  - `SessionStore`:   SQLAlchemy model for short-lived user sessions.
  - `AuditLog`:       SQLAlchemy model for the immutable, partitioned ledger.

Hard rules enforced across this package:
  - asyncpg ONLY (no psycopg2 / no sync drivers).
  - Raw PII is NEVER stored; only HMAC-SHA256 hashes.
  - All audit_log rows are append-only (GDPR exception is anonymisation,
    which keeps the row and only NULLs the PII columns).
  - SELECTs prefer read replicas; INSERTs/UPDATEs go to primary.
  - All queries are parameterised — string interpolation is forbidden.
"""

from __future__ import annotations

from app.db.database import DatabaseEngine
from app.db.models.audit_log import AuditLog
from app.db.models.session_store import SessionStore
from app.db.pool_monitor import PoolMonitor
from app.db.redis_client import RedisClient

__all__ = [
    "AuditLog",
    "DatabaseEngine",
    "PoolMonitor",
    "RedisClient",
    "SessionStore",
]
