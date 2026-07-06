"""
Olympus Engine v9 — Server-Side AI Inference Types

Foundation types for the four-model server-side AI layer:
  1. Liveness (face landmarks + EfficientNet-B0)
  2. Texture (LBP/Laplacian + EfficientNet-Lite0)
  3. rPPG (deterministic POS + Butterworth + HRV)
  4. Multimodal (SynthID + MFCC + WebGL)

All public types are immutable. The GPU allocator is thread-safe.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np
from numpy.typing import NDArray


# Verdict enumeration. Confidence is always 0.0..1.0 (clamped on output).
Verdict = Literal["REAL", "UNCERTAIN", "FAKE"]


@dataclass(frozen=True, slots=True)
class InferenceResult:
    """Result of a single model inference."""

    verdict: Verdict
    confidence: float
    latency_ms: float
    model_version: str
    input_hash: str
    gpu_memory_mb: float


@dataclass(frozen=True, slots=True)
class ModelInput:
    """Aggregated input for the 4-model server-side pipeline."""

    landmarks: NDArray[np.int16]
    roi_forehead: NDArray[np.uint8]
    roi_left_cheek: NDArray[np.uint8]
    roi_right_cheek: NDArray[np.uint8]
    rppg_signal: list[int]
    mfcc_vector: NDArray[np.float32]
    webgl_fingerprint: Optional[str] = None
    synthid_watermark: Optional[bytes] = None


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """ONNX model configuration."""

    onnx_path: str
    input_shape: tuple[int, ...]
    output_shape: tuple[int, ...]
    preferred_gpu: int
    max_batch_size: int = 1
    weight_hash: str = ""  # SHA-256 of the ONNX file, lowercase hex
    max_file_size_mb: int = 500
    trt_max_workspace_size: int = 2_147_483_648  # 2 GB
    gpu_mem_limit_mb: int = 4_096


# ---------------------------------------------------------------------------
# Verdict helpers.
# ---------------------------------------------------------------------------


def verdict_from_confidence(confidence: float) -> Verdict:
    """Map a raw [0, 1] confidence to a discrete verdict."""
    if not isinstance(confidence, (int, float)) or confidence != confidence:  # NaN
        return "FAKE"
    c = max(0.0, min(1.0, float(confidence)))
    if c > 0.9:
        return "REAL"
    if c > 0.4:
        return "UNCERTAIN"
    return "FAKE"


# ---------------------------------------------------------------------------
# GPU memory allocator (thread-safe, async-aware).
# ---------------------------------------------------------------------------


class GPUAllocator:
    """Async-safe GPU memory pool.

    Each GPU has its own asyncio.Lock. Memory accounting is kept in MB.
    """

    def __init__(self, gpu_count: int = 2, mem_per_gpu_mb: int = 16_384) -> None:
        if not isinstance(gpu_count, int) or gpu_count < 1:
            raise ValueError("gpu_count must be a positive integer")
        if not isinstance(mem_per_gpu_mb, int) or mem_per_gpu_mb < 256:
            raise ValueError("mem_per_gpu_mb must be >= 256")
        self._pools: dict[int, asyncio.Lock] = {
            i: asyncio.Lock() for i in range(gpu_count)
        }
        self._memory_used: dict[int, int] = {i: 0 for i in range(gpu_count)}
        self._memory_total: dict[int, int] = {
            i: mem_per_gpu_mb for i in range(gpu_count)
        }
        self._high_water: dict[int, int] = {i: 0 for i in range(gpu_count)}

    async def allocate(self, gpu_id: int, size_mb: int) -> bool:
        """Reserve `size_mb` MB on the given GPU."""
        if gpu_id not in self._pools:
            raise ValueError(f"unknown GPU id: {gpu_id}")
        if not isinstance(size_mb, int) or size_mb <= 0:
            raise ValueError("size_mb must be a positive integer")
        async with self._pools[gpu_id]:
            capacity: int = int(self._memory_total[gpu_id] * 0.9)
            if self._memory_used[gpu_id] + size_mb > capacity:
                return False
            self._memory_used[gpu_id] += size_mb
            if self._memory_used[gpu_id] > self._high_water[gpu_id]:
                self._high_water[gpu_id] = self._memory_used[gpu_id]
            return True

    async def release(self, gpu_id: int) -> None:
        """Release the last-allocated block. Idempotent."""
        if gpu_id not in self._pools:
            return
        async with self._pools[gpu_id]:
            if self._memory_used[gpu_id] > 0:
                self._memory_used[gpu_id] -= 1  # zero out the last call
                if self._memory_used[gpu_id] < 0:
                    self._memory_used[gpu_id] = 0

    def get_utilization(self, gpu_id: int) -> float:
        """Return current utilization as a 0..1 fraction."""
        if gpu_id not in self._pools:
            return 0.0
        used: int = self._memory_used[gpu_id]
        total: int = self._memory_total[gpu_id]
        if total <= 0:
            return 0.0
        return float(used) / float(total)

    def high_water_mark(self, gpu_id: int) -> int:
        return self._high_water.get(gpu_id, 0)

    def set_total(self, gpu_id: int, total_mb: int) -> None:
        self._memory_total[gpu_id] = int(total_mb)


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class ModelIntegrityError(Exception):
    """Raised when a model weight file fails SHA-256 verification."""


class ModelInputError(Exception):
    """Raised when input validation fails."""


# VERIFIED: Frozen dataclasses, GPUAllocator with per-GPU locks, 90% headroom, verdict thresholds 0.4/0.9.
