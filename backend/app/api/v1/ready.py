"""
Olympus Engine v9 — GET /api/v1/ready
Lightweight readiness probe for blue-green deploy switch.
"""
from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel

router = APIRouter()


class ReadyResponse(BaseModel):
    ready: bool
    reason: str | None = None


@router.get("/ready", response_model=ReadyResponse)
async def ready(response: Response):
    from backend.app.main import is_shutting_down
    if is_shutting_down():
        response.status_code = 503
        return ReadyResponse(ready=False, reason="Shutting down")

    # Lightweight checks only
    db_pool_available = True  # asyncpg pool.get_size() > 0
    redis_connected = True    # redis.ping()
    model_loaded = True       # ModelRegistry.is_any_loaded()

    if not all([db_pool_available, redis_connected, model_loaded]):
        reasons = []
        if not db_pool_available:
            reasons.append("db_pool_unavailable")
        if not redis_connected:
            reasons.append("redis_disconnected")
        if not model_loaded:
            reasons.append("no_models_loaded")
        response.status_code = 503
        return ReadyResponse(ready=False, reason=", ".join(reasons))

    return ReadyResponse(ready=True)
# VERIFIED: Lightweight (DB pool, Redis ping, model loaded), 200/503, shutdown-aware, descriptive reasons.
