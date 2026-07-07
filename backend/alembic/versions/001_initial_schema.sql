-- =============================================================================
-- Olympus Engine v9 — Database Schema (initial)
-- =============================================================================
-- Mounted by docker-compose into postgres' /docker-entrypoint-initdb.d
-- Only the dev stack uses this file directly; production runs the
-- Alembic migrations in `backend/alembic/versions/`.
-- =============================================================================

-- Required extensions.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ------------------------------------------------------------------
-- session_store — short-lived sessions (1h TTL)
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS session_store (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    did               TEXT NOT NULL UNIQUE,
    user_hash         TEXT,                                     -- HMAC-SHA256
    device_fp_hash    TEXT,                                     -- HMAC-SHA256
    session_secret    TEXT NOT NULL,                            -- server-side
    status            TEXT NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active', 'expired', 'revoked')),
    sanity_fail_count INTEGER NOT NULL DEFAULT 0,
    gdpr_anonymized   BOOLEAN NOT NULL DEFAULT FALSE,
    anonymized_at     TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at        TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '1 hour')
);

CREATE INDEX IF NOT EXISTS idx_session_store_expires
    ON session_store (expires_at);
CREATE INDEX IF NOT EXISTS idx_session_store_user_hash
    ON session_store (user_hash);
CREATE INDEX IF NOT EXISTS idx_session_store_status
    ON session_store (status);
CREATE INDEX IF NOT EXISTS idx_session_store_created_at
    ON session_store (created_at);

-- ------------------------------------------------------------------
-- audit_log — append-only, hash-chained (monthly partitions)
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    seq              BIGSERIAL,
    ts               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id       UUID,
    prev_hash        CHAR(64) NOT NULL,
    curr_hash        CHAR(64) NOT NULL,
    input_hash       CHAR(64) NOT NULL,
    result_hash      CHAR(64) NOT NULL,
    event_type       TEXT NOT NULL DEFAULT 'VERIFY',
    risk_score       DOUBLE PRECISION,
    decision         TEXT,
    error_code       TEXT,
    payload          JSONB,
    gdpr_anonymized  BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (ts, seq)
) PARTITION BY RANGE (ts);

-- Initial partition covering 2025-01-01 to 2030-01-01 (dev only).
CREATE TABLE IF NOT EXISTS audit_log_default
    PARTITION OF audit_log DEFAULT;

CREATE INDEX IF NOT EXISTS idx_audit_log_session
    ON audit_log (session_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_event
    ON audit_log (event_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_curr_hash
    ON audit_log (curr_hash);

-- ------------------------------------------------------------------
-- Append-only enforcement: reject UPDATE / DELETE on audit_log.
-- ------------------------------------------------------------------
CREATE OR REPLACE FUNCTION audit_log_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only (op=%)', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log;
CREATE TRIGGER audit_log_no_update
    BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();

DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log;
CREATE TRIGGER audit_log_no_delete
    BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();

-- ------------------------------------------------------------------
-- Auto-update updated_at
-- ------------------------------------------------------------------
CREATE OR REPLACE FUNCTION touch_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS session_store_touch ON session_store;
CREATE TRIGGER session_store_touch
    BEFORE UPDATE ON session_store
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
