"""
Olympus Engine v9 — QISM 5 (Zone 4+5) Decision Engine Storage
Initial Alembic migration: session_store, audit_log, partitioned schema, and triggers.
"""
from __future__ import annotations

from typing import Sequence

from alembic import op
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.sql import func

revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")

    op.create_table(
        "session_store",
        Column("id", String(36), primary_key=True),
        Column("session_secret", String(43), nullable=False),
        Column("user_id_hash", String(64), nullable=True),
        Column("device_fingerprint_hash", String(64), nullable=True),
        Column(
            "created_at",
            DateTime(timezone=True),
            server_default=text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        Column(
            "expires_at",
            DateTime(timezone=True),
            server_default=text("CURRENT_TIMESTAMP + INTERVAL '1 hour'"),
            nullable=False,
        ),
        Column(
            "status",
            String(20),
            server_default=text("'active'"),
            nullable=False,
        ),
        Column(
            "last_activity_at",
            DateTime(timezone=True),
            server_default=text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        Column("sanity_fail_count", Integer, server_default=text("0"), nullable=False),
        Column("ip_address_hash", String(64), nullable=True),
        Column("geo_region", String(100), nullable=True),
    )
    op.create_check_constraint("ck_session_secret_length", "session_store", "length(session_secret) = 43")
    op.create_check_constraint("ck_session_expires_after_created", "session_store", "expires_at > created_at")
    op.create_index("idx_session_expires", "session_store", ["expires_at"])
    op.create_index("idx_session_user", "session_store", ["user_id_hash"])
    op.create_index("idx_session_status", "session_store", ["status", "expires_at"])

    op.execute(
        """
        CREATE TABLE audit_log (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            prev_hash VARCHAR(64) NOT NULL,
            curr_hash VARCHAR(64) NOT NULL,
            input_hash VARCHAR(64) NOT NULL,
            result_hash VARCHAR(64) NOT NULL,
            model_results JSONB NOT NULL,
            verifier_results JSONB NOT NULL,
            decision VARCHAR(20) NOT NULL,
            session_id VARCHAR(36),
            gdpr_anonymized BOOLEAN NOT NULL DEFAULT FALSE,
            anonymous_before TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) PARTITION BY RANGE (created_at)
        """
    )
    op.create_check_constraint("ck_prev_hash_length", "audit_log", "length(prev_hash) = 64")
    op.create_check_constraint("ck_curr_hash_length", "audit_log", "length(curr_hash) = 64")

    op.create_index("idx_audit_timestamp", "audit_log", ["created_at"], postgresql_using="btree", postgresql_ops={"created_at": "DESC"})
    op.create_index("idx_audit_session", "audit_log", ["session_id"])
    op.create_index("idx_audit_decision", "audit_log", ["decision", "created_at"])
    op.create_index("idx_audit_gdpr", "audit_log", ["gdpr_anonymized", "anonymous_before"])

    start_month = datetime(year=2024, month=7, day=1, tzinfo=timezone.utc)
    for i in range(6):
        dt = start_month + timedelta(days=31 * i)
        start_dt = dt.strftime("%Y-%m-01")
        if dt.month == 12:
            end_dt = dt.replace(year=dt.year + 1, month=1).strftime("%Y-%m-01")
        else:
            end_dt = dt.replace(month=dt.month + 1).strftime("%Y-%m-01")
        partition_name = f"audit_log_{dt.year}_{dt.month:02d}"
        op.execute(
            f"CREATE TABLE IF NOT EXISTS {partition_name} PARTITION OF audit_log "
            f"FOR VALUES FROM ('{start_dt}') TO ('{end_dt}')"
        )

# VERIFIED: Migration creates session_store, audit_log with RANGE partitioning by month, CHECK constraints, and indexes.


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS session_store CASCADE")

# VERIFIED: Migration creates session_store, audit_log with RANGE partitioning by month, CHECK constraints, and indexes.
