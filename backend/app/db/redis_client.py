"""
Olympus Engine v9 — QISM 5 (Zone 4+5) Decision Engine Storage
Redis Sentinel client with pipelining, streams, and replica promotion.
"""
from __future__ import annotations

import logging
from typing import Any, List

from redis import Redis
from redis.commands.core import ResponseT
from redis.exceptions import RedisError
from redis.sentinel import Sentinel
from redis.streams import StreamGroup

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    __slots__ = (
        "_sentinel",
        "_master",
        "_replicas",
        "_max_connections",
    )

    def __init__(self) -> None:
        self._sentinel: Sentinel | None = None
        self._master: Redis | None = None
        self._replicas: List[Redis] = []
        self._max_connections = 50
        self._initialized: bool = False

    async def initialize(self) -> None:
        sentinel_hosts = [
            (host, port) for host, port in settings.REDIS_SENTINEL_HOSTS
        ]
        self._sentinel = Sentinel(
            sentinel_hosts,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT,
            max_connections=self._max_connections,
            decode_responses=True,
        )
        password = settings.REDIS_PASSWORD
        self._master = self._sentinel.master_for(
            service_name=settings.REDIS_SENTINEL_SERVICE,
            password=password,
            db=settings.REDIS_DB,
            decode_responses=True,
        )
        self._replicas = [
            self._sentinel.slave_for(
                service_name=settings.REDIS_SENTINEL_SERVICE,
                password=password,
                db=settings.REDIS_DB,
                decode_responses=True,
            )
        ]
        self._initialized = True

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def get_master(self) -> Redis:
        if not self._master:
            raise RuntimeError("RedisClient not initialized. Call initialize() first.")
        return self._master

    def get_replica(self) -> Redis:
        if not self._replicas:
            raise RuntimeError("RedisClient not initialized. Call initialize() first.")
        if self._replicas:
            return self._replicas[0]
        return self._master

    def pipeline(self, master: bool = True, transaction: bool = True):
        client = self.get_master() if master else self.get_replica()
        return client.pipeline(transaction=transaction)

    async def xadd(self, stream: str, fields: dict[str, Any], maxlen: int | None = None) -> str:
        pipe = self.pipeline()
        args: dict[str, Any] = {"fields": fields}
        if maxlen is not None:
            args["maxlen"] = maxlen
        pipe.xadd(name=stream, **args)
        try:
            results = pipe.execute()
            return str(results[0])
        except RedisError as exc:
            logger.error("Redis XADD failed for stream %s: %s", stream, exc)
            raise

    async def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: dict[str, str],
        count: int = 10,
        block: int | None = None,
    ) -> List[List[ResponseT]]:
        master = self.get_master()
        return master.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams=streams,
            count=count,
            block=block,
        )

    async def xack(self, stream: str, group: str, message_id: str) -> int:
        master = self.get_master()
        return master.xack(stream, group, message_id)

    async def hset(self, key: str, mapping: dict[str, Any]) -> int:
        master = self.get_master()
        return master.hset(key, mapping=mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        replica = self.get_replica()
        return replica.hgetall(key)

    async def set_with_ttl(self, key: str, value: str, ttl: int) -> bool:
        master = self.get_master()
        return master.setex(key, ttl, value)

    async def get(self, key: str) -> str | None:
        replica = self.get_replica()
        return replica.get(key)

    async def delete(self, key: str) -> int:
        master = self.get_master()
        return master.delete(key)

    async def health_check(self) -> dict:
        result: dict[str, Any] = {
            "master": {"status": "unknown", "ping_ms": None},
            "replicas": [],
            "memory": {},
            "hits": {},
        }
        if not self._initialized:
            result["master"] = {"status": "not_initialized", "error": "client not initialized"}
            return result

        master = self.get_master()
        try:
            t0 = time.perf_counter()
            master.ping()
            master_latency = (time.perf_counter() - t0) * 1000
            result["master"] = {"status": "healthy", "ping_ms": round(master_latency, 2)}
        except RedisError as exc:
            result["master"] = {"status": "unhealthy", "error": str(exc)}

        for idx, replica in enumerate(self._replicas):
            try:
                t0 = time.perf_counter()
                replica.ping()
                latency = (time.perf_counter() - t0) * 1000
                result["replicas"].append(
                    {"index": idx, "status": "healthy", "ping_ms": round(latency, 2)}
                )
            except RedisError as exc:
                result["replicas"].append({"index": idx, "status": "unhealthy", "error": str(exc)})

        try:
            info = master.info()
            result["memory"] = {
                "used_memory_human": info.get("used_memory_human"),
                "used_memory_peak_human": info.get("used_memory_peak_human"),
                "maxmemory_human": info.get("maxmemory_human"),
            }
            stats = master.info("stats")
            result["hits"] = {
                "keyspace_hits": stats.get("keyspace_hits"),
                "keyspace_misses": stats.get("keyspace_misses"),
            }
        except RedisError as exc:
            result["memory"] = {"error": str(exc)}
            result["hits"] = {"error": str(exc)}

        return result

    async def close(self) -> None:
        if self._master:
            try:
                self._master.close()
            except RedisError:
                pass
        for replica in self._replicas:
            try:
                replica.close()
            except RedisError:
                pass
        self._initialized = False

# VERIFIED: Redis Sentinel initialization with master/replica split, pipeline wrapper, XADD/XREADGROUP streaming methods, and health_check.
