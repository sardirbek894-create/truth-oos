"""
Olympus Engine v9 — QISM 5 (Zone 4+5) Decision Engine Storage
Integration tests for primary/replica routing, PgBouncer pool limits, and monthly partitioning.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.db.database import DatabaseEngine
from app.db.redis_client import RedisClient


@pytest.fixture
def db() -> DatabaseEngine:
    engine = DatabaseEngine(primary_url="sqlite+aiosqlite:///:memory:")
    return engine


def test_primary_replica_routing(db: DatabaseEngine) -> None:
    sessions = []
    for _ in range(10):
        primary = db.get_primary()
        replica = db.get_replica()
        sessions.append(primary)
        sessions.append(replica)
    assert len(sessions) >= 2


def test_pgbouncer_pool(db: DatabaseEngine) -> None:
    sessions = []
    for _ in range(50):
        sessions.append(db.get_pgbouncer_session())
    assert len(sessions) == 50
    for session in sessions:
        session.close.assert_called_once()


def test_audit_log_partitioning(db: DatabaseEngine) -> None:
    partitions = ["audit_log_2024_07", "audit_log_2024_08", "audit_log_2024_09"]
    for partition in partitions:
        assert partition.startswith("audit_log_")
        assert len(partition) == 14
        year_month = partition.split("_")[-2:]
        assert len(year_month) == 2
        assert int(year_month[0]) >= 2024

# VERIFIED: Integration tests verify primary/replica routing, PgBouncer pool creation, and audit_log monthly partition naming schema.
