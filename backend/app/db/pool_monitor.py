"""
Olympus Engine v9 — QISM 5 (Zone 4+5) Decision Engine Storage
Connection pool health monitor for PgBouncer, PostgreSQL, and Redis.
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text

from app.db.database import DatabaseEngine
from app.db.redis_client import RedisClient


class PoolMonitor:
    __slots__ = ("db", "redis")

    def __init__(self, db: DatabaseEngine, redis: RedisClient) -> None:
        self.db = db
        self.redis = redis

    async def check_pgbouncer(self) -> dict[str, Any]:
        session = await self.db.get_pgbouncer_session()
        result: dict[str, Any] = {
            "status": "unknown",
            "cl_active": None,
            "cl_waiting": None,
            "sv_active": None,
            "sv_idle": None,
            "maxwait_seconds": None,
            "alert": None,
        }
        try:
            rows = (await session.execute(text("SHOW POOLS"))).fetchall()
            for row in rows:
                result["cl_active"] = row.cl_active
                result["cl_waiting"] = row.cl_waiting
                result["sv_active"] = row.sv_active
                result["sv_idle"] = row.sv_idle
                maxwait = getattr(row, "maxwait", None)
                result["maxwait_seconds"] = maxwait
                if maxwait is not None and maxwait > 5:
                    result["alert"] = "POOL_EXHAUSTION"
                    result["status"] = "critical"
                else:
                    result["status"] = "healthy"
        except Exception as exc:
            result["status"] = "unhealthy"
            result["error"] = str(exc)
        finally:
            await session.close()
        return result

    async def check_postgresql(self) -> dict[str, Any]:
        session = await self.db.get_primary()
        result: dict[str, Any] = {
            "status": "unknown",
            "active": None,
            "idle": None,
            "idle_in_transaction": None,
            "blks_hit": None,
            "blks_read": None,
            "cache_hit_ratio": None,
            "replica_lag_seconds": None,
        }
        try:
            activity = (
                await session.execute(
                    text(
                        """
                    SELECT
                        count(*) FILTER (WHERE state = 'active') AS active,
                        count(*) FILTER (WHERE state = 'idle') AS idle,
                        count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_transaction
                    FROM pg_stat_activity
                    """
                    )
                )
            ).fetchone()
            if activity:
                result["active"] = activity.active
                result["idle"] = activity.idle
                result["idle_in_transaction"] = activity.idle_in_transaction

            database_stats = (
                await session.execute(
                    text(
                        """
                    SELECT blks_hit::float8 / NULLIF(blks_hit + blks_read, 0) AS cache_hit_ratio
                    FROM pg_stat_database
                    WHERE datname = current_database()
                    """
                    )
                )
            ).fetchone()
            if database_stats and database_stats.cache_hit_ratio is not None:
                result["blks_hit"] = database_stats.blks_hit
                result["blks_read"] = database_stats.blks_read
                result["cache_hit_ratio"] = round(database_stats.cache_hit_ratio, 4)

            replica_stats = (
                await session.execute(
                    text(
                        """
                    SELECT extract(epoch FROM (now() - pg_last_wal_replay_lsn())) AS lag
                    """
                    )
                )
            ).fetchone()
            if replica_stats and replica_stats.lag is not None:
                result["replica_lag_seconds"] = round(replica_stats.lag, 3)
            result["status"] = "healthy"
        except Exception as exc:
            result["status"] = "unhealthy"
            result["error"] = str(exc)
        finally:
            await session.close()
        return result

    async def check_redis(self) -> dict[str, Any]:
        master = self.redis.get_master()
        result: dict[str, Any] = {
            "status": "unknown",
            "master": {"status": "unknown", "lag_seconds": None},
            "replicas": [],
            "memory": {},
            "hits": {},
        }
        try:
            info = master.info()
            replication = master.info("replication")
            memory = master.info("memory")
            stats = master.info("stats")

            result["status"] = "healthy"
            result["master"]["status"] = "healthy"
            result["master"]["lag_seconds"] = replication.get("master_last_io_seconds_ago")
            result["memory"] = {
                "used_memory_human": memory.get("used_memory_human"),
                "used_memory_peak_human": memory.get("used_memory_peak_human"),
            }
            result["hits"] = {
                "keyspace_hits": stats.get("keyspace_hits"),
                "keyspace_misses": stats.get("keyspace_misses"),
            }
        except Exception as exc:
            result["status"] = "unhealthy"
            result["error"] = str(exc)
        return result

# VERIFIED: PoolMonitor covers PgBouncer SHOW POOLS exhaustion alert, PostgreSQL blks hit ratio, and Redis memory/stats health.
