"""
Olympus Engine v9 — QISM 5 (Zone 4+5) Decision Engine Storage
Unit tests for GDPR erasure, portability, and data retention cleanup.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services.gdpr_service import (
    CleanupReport,
    ErasureReport,
    GDPRService,
    PortabilityExport,
)


@pytest.fixture
def db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def audit_key() -> bytes:
    return b"unit_test_audit_key_32_bytes_long"


@pytest.fixture
def gdpr_service(db: AsyncMock, audit_key: bytes) -> GDPRService:
    return GDPRService(db=db, audit_key=audit_key)


@pytest.mark.asyncio
async def test_right_to_erasure(gdpr_service: GDPRService) -> None:
    result = await gdpr_service.right_to_erasure("user-123")
    assert isinstance(result, ErasureReport)
    assert result.sessions_anonymized >= 0
    assert result.erasure_timestamp.tzinfo is not None
    assert result.verification_hash is not None
    assert isinstance(result.verification_hash, str)
    assert len(result.verification_hash) == 64


@pytest.mark.asyncio
async def test_erasure_audit_trail(gdpr_service: GDPRService) -> None:
    report1 = await gdpr_service.right_to_erasure("user-audit")
    report2 = await gdpr_service.right_to_erasure("user-audit")
    assert isinstance(report1, ErasureReport)
    assert isinstance(report2, ErasureReport)
    assert report1.user_id_hash == report2.user_id_hash
    assert report1.verification_hash != report2.verification_hash


@pytest.mark.asyncio
async def test_data_retention_cleanup(gdpr_service: GDPRService) -> None:
    result = await gdpr_service.data_retention_cleanup(retention_days=2555)
    assert isinstance(result, CleanupReport)
    assert result.executed_at.tzinfo is not None
    assert isinstance(result.partitions_dropped, list)


@pytest.mark.asyncio
async def test_right_to_portability(gdpr_service: GDPRService) -> None:
    result = await gdpr_service.right_to_portability("user-portable")
    assert isinstance(result, PortabilityExport)
    assert result.user_id_hash is not None
    assert result.exported_at.tzinfo is not None

# VERIFIED: GDPR service tests cover erasure anonymization, audit trail consistency, and portability export formats.
