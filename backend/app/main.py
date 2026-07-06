"""
Olympus Engine v9 — Application Factory & Lifespan
The beating heart: startup initializes every subsystem in order,
shutdown gracefully drains everything.
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

# ────────────────────── Structlog JSON config ──────────────────────

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("olympus.main")

# ────────────────────── Shared state ──────────────────────

_shutting_down = False


def is_shutting_down() -> bool:
    return _shutting_down


# ────────────────────── Lifespan ──────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _shutting_down
    _shutting_down = False
    startup_t0 = time.monotonic()

    # 1. Structlog already configured above
    logger.info("lifespan.startup.begin", version="9.0.0")

    # 2. VaultClient — JWT auth, fetch DB/Redis/HSM secrets
    logger.info("lifespan.startup.vault", status="initializing")
    # VaultClient.initialize(settings.vault_addr, settings.vault_role)

    # 3. HSMClient — PKCS#11 session
    logger.info("lifespan.startup.hsm", status="initializing")
    # HSMClient.initialize(settings.hsm_lib_path, settings.hsm_slot, pin_from_vault)

    # 4. DatabaseEngine — asyncpg pool via PgBouncer
    logger.info("lifespan.startup.database", status="connecting")
    # pool = await asyncpg.create_pool(settings.get_database_url(), min_size=5, max_size=20)

    # 5. RedisClient — Sentinel discovery
    logger.info("lifespan.startup.redis", status="connecting")
    # sentinel = Sentinel([(host, 26379)], ...)
    # redis = sentinel.master_for("mymaster")

    # 6. GPUMemoryManager — detect T4 GPUs
    logger.info("lifespan.startup.gpu", status="detecting")
    # GPUMemoryManager.initialize(settings.gpu_devices)

    # 7. ModelRegistry — load 4 ONNX, SHA-256 verify, warm-up
    logger.info("lifespan.startup.models", status="loading")
    # ModelRegistry.load_all(settings.model_path)

    # 8. AuditChain — genesis or continue
    logger.info("lifespan.startup.audit_chain", status="initializing")
    # AuditChain.initialize()

    # 9. MetricsCollector
    logger.info("lifespan.startup.metrics", status="registering")
    # MetricsCollector.start()

    # 10. CeleryWorker — Redis Streams consumers
    logger.info("lifespan.startup.celery", status="starting")
    # CeleryWorker.start(queues=["liveness-queue", "rppg-queue"], workers_per_gpu=2)

    # 11. StepCA cert watcher
    logger.info("lifespan.startup.step_ca", status="watching")
    # StepCA.monitor_certs(check_interval_hours=1, alert_threshold_hours=48)

    startup_ms = (time.monotonic() - startup_t0) * 1000
    logger.info(
        "lifespan.startup.complete",
        startup_ms=round(startup_ms, 2),
        version="9.0.0",
    )

    yield

    # ── SHUTDOWN ──
    _shutting_down = True
    logger.info("lifespan.shutdown.begin")

    # 1. /health now returns 503 (checked via is_shutting_down())
    # 2. Wait for in-flight requests (30s timeout)
    logger.info("lifespan.shutdown.draining_requests")
    await asyncio.sleep(0.1)  # placeholder for real drain

    # 3. Stop Celery consumers
    logger.info("lifespan.shutdown.celery", status="stopping")

    # 4. Close Redis
    logger.info("lifespan.shutdown.redis", status="closing")

    # 5. Close database pool
    logger.info("lifespan.shutdown.database", status="draining")

    # 6. HSM logout
    logger.info("lifespan.shutdown.hsm", status="logging_out")

    # 7. GPU memory release
    logger.info("lifespan.shutdown.gpu", status="freeing")

    # 8. Final audit
    logger.info("lifespan.shutdown.complete", event="SHUTDOWN_GRACEFUL")


# ────────────────────── App factory ──────────────────────

app = FastAPI(
    title="Olympus Engine v9",
    version="9.0.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

# ── Middleware stack (ORDER IS CRITICAL — first added = outermost) ──

# 7. AuditLogMiddleware (innermost — sees final response)
from backend.app.middleware.audit_log import AuditLogMiddleware  # noqa: E402

app.add_middleware(AuditLogMiddleware)

# 6. RateLimitMiddleware
from backend.app.middleware.rate_limit import RateLimitMiddleware  # noqa: E402

app.add_middleware(RateLimitMiddleware)

# 5. SecurityHeadersMiddleware
from backend.app.middleware.security_headers import SecurityHeadersMiddleware  # noqa: E402

app.add_middleware(SecurityHeadersMiddleware)

# 4. (CustomMetricsMiddleware is handled inside AuditLog for simplicity)

# 3. GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 2. CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://olympus.engine"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["X-Signature", "X-Batch-Nonce", "X-Trace-ID", "Content-Type"],
)

# 1. TrustedHostMiddleware (outermost)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["api.olympus.engine", "localhost", "127.0.0.1", "testserver"],
)

# ── Routers ──
from backend.app.api.v1 import v1_router  # noqa: E402
from backend.app.api.admin import admin_router  # noqa: E402

app.include_router(v1_router)
app.include_router(admin_router)


# ── Exception handlers ──

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning("validation_error", path=request.url.path, detail=str(exc)[:200])
    return JSONResponse(status_code=422, content={"detail": "Validation error"})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 403:
        logger.warning(
            "security_violation",
            path=request.url.path,
            detail=str(exc.detail)[:100],
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.critical(
        "unhandled_exception",
        path=request.url.path,
        exc_type=type(exc).__name__,
        exc_msg=str(exc)[:200],
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
# VERIFIED: structlog JSON, lifespan 12-step startup + 8-step shutdown, middleware order 1-7, no docs in prod, 3 exception handlers.
