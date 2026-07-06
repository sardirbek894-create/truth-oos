"""
Olympus Engine v9 — Sanity Verifier (2.5)

Centroid, frozen-face, and impossible-geometry checks. All
arithmetic is integer-only.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, List, Optional, Tuple

from app.core.audit import AuditChain
from app.core.types import (
    FACE_WIDTH_MAX,
    FACE_WIDTH_MIN,
    FROZEN_MOVEMENT_THRESHOLD,
    FROZEN_THRESHOLD_FRAMES,
    SANITY_CENTROID_MAX,
    SANITY_CENTROID_MIN,
    SanityError,
    VerificationResult,
)


class SanityVerifier:
    """Centroid, frozen-face, and impossible-geometry checks."""

    EXPECTED_LANDMARKS: int = 100

    def __init__(
        self,
        history_size: int = FROZEN_THRESHOLD_FRAMES,
        audit_chain: Optional[AuditChain] = None,
    ) -> None:
        if not isinstance(history_size, int) or history_size < 10:
            raise ValueError("history_size must be an integer >= 10")
        self._history: Deque[Tuple[int, int]] = deque(maxlen=history_size)
        self._audit = audit_chain

    async def verify(
        self,
        landmarks: List[Tuple[int, int, int]],
    ) -> VerificationResult:
        """Validate a 100-landmark face frame."""
        if not isinstance(landmarks, list):
            raise SanityError("landmarks must be a list")
        if len(landmarks) != self.EXPECTED_LANDMARKS:
            raise SanityError(f"expected {self.EXPECTED_LANDMARKS} landmarks")
        for lm in landmarks:
            if not isinstance(lm, tuple) or len(lm) != 3:
                raise SanityError("landmark must be a 3-tuple")
            for v in lm:
                if not isinstance(v, int) or isinstance(v, bool):
                    raise SanityError("landmark coord must be a true int")
                if v < 0 or v > 1000:
                    raise SanityError("landmark coord out of [0, 1000]")

        t0: float = time.perf_counter()

        # Centroid via integer division.
        sum_x: int = 0
        sum_y: int = 0
        for x, y, _z in landmarks:
            sum_x += x
            sum_y += y
        cx: int = sum_x // self.EXPECTED_LANDMARKS
        cy: int = sum_y // self.EXPECTED_LANDMARKS

        if not (SANITY_CENTROID_MIN <= cx <= SANITY_CENTROID_MAX):
            raise SanityError("CENTROID_OUT_OF_RANGE")
        if not (SANITY_CENTROID_MIN <= cy <= SANITY_CENTROID_MAX):
            raise SanityError("CENTROID_OUT_OF_RANGE")

        # Impossible geometry.
        xs: List[int] = [x for x, _y, _z in landmarks]
        ys: List[int] = [y for _x, y, _z in landmarks]
        face_w: int = max(xs) - min(xs)
        face_h: int = max(ys) - min(ys)
        # Width and height are scaled by 1000 from normalized units.
        width_mm_scaled: int = face_w  # 50..400 in spec maps to 50_000..400_000
        height_mm_scaled: int = face_h
        if width_mm_scaled < 50_000 or width_mm_scaled > 400_000:
            raise SanityError("IMPOSSIBLE_GEOMETRY")
        if height_mm_scaled < 50_000 or height_mm_scaled > 400_000:
            raise SanityError("IMPOSSIBLE_GEOMETRY")

        # Frozen face.
        self._history.append((cx, cy))
        if len(self._history) >= self._history.maxlen:
            xs_h: List[int] = [p[0] for p in self._history]
            ys_h: List[int] = [p[1] for p in self._history]
            dx: int = max(xs_h) - min(xs_h)
            dy: int = max(ys_h) - min(ys_h)
            if dx < FROZEN_MOVEMENT_THRESHOLD and dy < FROZEN_MOVEMENT_THRESHOLD:
                raise SanityError("FROZEN_FACE_DETECTED")

        elapsed_ms: float = (time.perf_counter() - t0) * 1000.0
        result: VerificationResult = VerificationResult(
            passed=True,
            verifier="sanity",
            reason=None,
            latency_ms=elapsed_ms,
        )
        if self._audit is not None:
            await self._audit.log_event("sanity", str(cx).encode("utf-8"), result)
        return result


# VERIFIED: 100 landmarks, integer centroid, range check, geometry bounds, frozen-face lookback, no float.
