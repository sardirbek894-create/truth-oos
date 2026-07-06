"""Tests for the sanity verifier."""

import pytest

from app.core.types import SanityError
from app.core.verifiers.sanity_verifier import SanityVerifier


class _StubAudit:
    async def log_event(self, *args, **kwargs):
        return None


def _face(cx: int = 500, cy: int = 500, width: int = 200_000) -> list[tuple[int, int, int]]:
    half: int = width // 2
    out: list[tuple[int, int, int]] = []
    for i in range(100):
        x: int = cx - half + (i * (width // 99))
        y: int = cy - half + (i * (width // 99))
        out.append((x, y, 0))
    return out


@pytest.mark.asyncio
async def test_valid_centroid():
    v = SanityVerifier(audit_chain=_StubAudit())  # type: ignore[arg-type]
    r = await v.verify(_face())
    assert r.passed is True


@pytest.mark.asyncio
async def test_centroid_too_low():
    v = SanityVerifier(audit_chain=_StubAudit())  # type: ignore[arg-type]
    with pytest.raises(SanityError):
        await v.verify(_face(cx=100, cy=500))


@pytest.mark.asyncio
async def test_centroid_too_high():
    v = SanityVerifier(audit_chain=_StubAudit())  # type: ignore[arg-type]
    with pytest.raises(SanityError):
        await v.verify(_face(cx=900, cy=500))


@pytest.mark.asyncio
async def test_frozen_face():
    v = SanityVerifier(history_size=10, audit_chain=_StubAudit())  # type: ignore[arg-type]
    # Same face 10 times — centroid never moves.
    for _ in range(10):
        with pytest.raises(SanityError):
            await v.verify(_face())


@pytest.mark.asyncio
async def test_impossible_geometry():
    v = SanityVerifier(audit_chain=_StubAudit())  # type: ignore[arg-type]
    with pytest.raises(SanityError):
        await v.verify(_face(width=10_000))  # 10px width < 50
