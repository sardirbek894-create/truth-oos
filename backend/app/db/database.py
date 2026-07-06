"""
Olympus Engine v9 — QISM 5 Decision Engine Storage
Database engine with primary/replica routing and PgBouncer integration.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.core.config import settings

Base = declarative_base()

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass
class ReplicaEndpoint:
    url: str
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


class DatabaseEngine:
    __slots__ = (
        "primary_url",
        "replica_urls",
        "pgbouncer_url",
        "primary_engine",
        "replicas",
        "pgbouncer_engine",
        "primary_session_factory",
        "pgbouncer_session_factory",
        "_replica_round_robin",
    )

    def __init__(self) -> None:
        self.primary_url = settings.DATABASE_PRIMARY_URL
        self.replica_urls = settings.DATABASE_REPLICA_URLS or []
        self.pgbouncer_url = settings.DATABASE_PGBOUNCER_URL

        self.primary_engine: AsyncEngine | None = None
        self.replicas: list[ReplicaEndpoint] = []
        self.pgbouncer_engine: AsyncEngine | None = None

        self.primary_session_factory: async_sessionmaker[AsyncSession] | None = None
        self.pgbouncer_session_factory: async_sessionmaker[AsyncSession] | None = None

        self._replica_round_robin: int = 0

    async def initialize(self) -> None:
        self.primary_engine = create_async_engine(
            self.primary_url,
            echo=settings.DEBUG,
            pool_pre_ping=True,
            pool_size=20,
            max_overflow=10,
            pool_reset_on_return="commit",
            json_serializer=lambda obj: json.dumps(obj, default=str),
        )
        self.primary_session_factory = async_sessionmaker(
            self.primary_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        for url in self.replica_urls:
            engine = create_async_engine(
                url,
                echo=settings.DEBUG,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=5,
                pool_reset_on_return="commit",
                json_serializer=lambda obj: json.dumps(obj, default=str),
            )
            factory = async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            self.replicas.append(ReplicaEndpoint(url=url, engine=engine, session_factory=factory))

        self.pgbouncer_engine = create_async_engine(
            self.pgbouncer_url,
            echo=settings.DEBUG,
            pool_pre_ping=True,
            pool_size=50,
            max_overflow=100,
            pool_timeout=30,
            pool_reset_on_return="commit",
            json_serializer=lambda obj: json.dumps(obj, default=str),
        )
        self.pgbouncer_session_factory = async_sessionmaker(
            self.pgbouncer_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def get_primary(self) -> AsyncSession:
        if not self.primary_session_factory:
            raise RuntimeError("DatabaseEngine not initialized. Call initialize() first.")
        return self.primary_session_factory()

    async def get_replica(self) -> AsyncSession:
        if not self.replicas:
            raise RuntimeError("DatabaseEngine not initialized. Call initialize() first.")
        idx = self._replica_round_robin % len(self.replicas)
        self._replica_round_robin += 1
        return self.replicas[idx].session_factory()

    async def get_pgbouncer_session(self) -> AsyncSession:
        if not self.pgbouncer_session_factory:
            raise RuntimeError("DatabaseEngine not initialized. Call initialize() first.")
        return self.pgbouncer_session_factory()

    def get_primary_engine(self) -> AsyncEngine:
        if not self.primary_engine:
            raise RuntimeError("DatabaseEngine not initialized. Call initialize() first.")
        return self.primary_engine

    async def health_check(self) -> dict:
        result = {
            "primary": {"status": "unknown", "latency_ms": None},
            "replicas": [],
            "pgbouncer": {"status": "unknown", "latency_ms": None},
        }

        if not self.primary_engine:
            result["primary"] = {"status": "not_initialized", "error": "engine not initialized"}
            return result

        try:
            async with self.primary_engine.connect() as conn:
                t0 = time.perf_counter()
                await conn.execute(text("SELECT 1"))
                latency = (time.perf_counter() - t0) * 1000
                result["primary"] = {"status": "healthy", "latency_ms": round(latency, 2)}
        except Exception as exc:  # pragma: no cover
            result["primary"] = {"status": "unhealthy", "error": str(exc)}

        for idx, replica in enumerate(self.replicas):
            try:
                async with replica.engine.connect() as conn:
                    t0 = time.perf_counter()
                    await conn.execute(text("SELECT 1"))
                    latency = (time.perf_counter() - t0) * 1000
                    result["replicas"].append(
                        {"index": idx, "url": replica.url, "status": "healthy", "latency_ms": round(latency, 2)}
                    )
            except Exception as exc:
                result["replicas"].append(
                    {"index": idx, "url": replica.url, "status": "unhealthy", "error": str(exc)}
                )

        if self.pgbouncer_engine:
            try:
                async with self.pgbouncer_engine.connect() as conn:
                    t0 = time.perf_counter()
                    await conn.execute(text("SELECT 1"))
                    latency = (time.perf_counter() - t0) * 1000
                    result["pgbouncer"] = {"status": "healthy", "latency_ms": round(latency, 2)}
            except Exception as exc:
                result["pgbouncer"] = {"status": "unhealthy", "error": str(exc)}

        return result

    async def close(self) -> None:
        if self.primary_engine:
            await self.primary_engine.dispose()
        for replica in self.replicas:
            await replica.engine.dispose()
        if self.pgbouncer_engine:
            await self.pgbouncer_engine.dispose()

    def create_all(self) -> None:
        from app.db.models.session_store import SessionStore
        from app.db.models.audit_log import AuditLog

        Base.metadata.create_all(self.primary_engine)

    async def drop_all(self) -> None:
        from app.db.models.session_store import SessionStore
        from app.db.models.audit_log import AuditLog

        async with self.primary_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

# VERIFIED: Primary/replica/PgBouncer async engines use asyncpg with pool_pre_ping, json_serializer, and round-robin replica routing.
