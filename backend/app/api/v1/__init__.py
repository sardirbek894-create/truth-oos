"""
Olympus Engine v9 — API v1 Router Assembly
"""
from fastapi import APIRouter

from backend.app.api.v1.register import router as register_router
from backend.app.api.v1.challenge import router as challenge_router
from backend.app.api.v1.verify import router as verify_router
from backend.app.api.v1.health import router as health_router
from backend.app.api.v1.ready import router as ready_router
from backend.app.api.v1.did import router as did_router

v1_router = APIRouter(prefix="/api/v1", tags=["v1"])

v1_router.include_router(register_router)
v1_router.include_router(challenge_router)
v1_router.include_router(verify_router)
v1_router.include_router(health_router)
v1_router.include_router(ready_router)
v1_router.include_router(did_router)
# VERIFIED: All 6 sub-routers mounted under /api/v1 prefix.
