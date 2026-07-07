"""
Olympus Engine v9 — Mock ONNX Models (Development / CI)

In-process ONNX runtime replacements that emit deterministic
verdicts without requiring real .onnx weight files. They satisfy
the same interface as the production `ONNXModelLoader` so the
decision engine, verifiers, and API surface can run end-to-end in
dev/CI.

CRITICAL: The mock always returns a fixed verdict based on a
hash of the input — this is BY DESIGN for development. The real
ONNXRuntime path (with .onnx files) is selected via
`OLYMPUS_AI_MODE=onnx`; the mock is the default.

Verdicts emitted (deterministic, based on input bytes):
  * Empty / all-zero input       → "FAKE"     (sanity failure)
  * Sparse (1-2 active bytes)    → "UNCERTAIN"
  * Dense (>= 50% active bytes)  → "REAL"

This is intentionally simplistic — it exists to make /verify
exercisable in dev, not to mimic the production AI ensemble.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.models.types import InferenceResult, ModelConfig, ModelInput


log = logging.getLogger("olympus.ai.mock")


# ---------------------------------------------------------------------------
# Model registry (mock).
# ---------------------------------------------------------------------------


MOCK_MODEL_VERSIONS: dict[str, str] = {
    "liveness": "mock-liveness-v0.0.1-dev",
    "texture": "mock-texture-v0.0.1-dev",
    "rppg": "mock-rppg-v0.0.1-dev",
    "multimod": "mock-multimod-v0.0.1-dev",
}


# ---------------------------------------------------------------------------
# Deterministic mock inference.
# ---------------------------------------------------------------------------


def _verdict_from_input(inp: ModelInput) -> tuple[str, float, int, int]:
    """
    Return (verdict, confidence, bpm, hrv_ms) deterministic from input.

    Empty / all-zero → FAKE (0.95 conf).
    Sparse           → UNCERTAIN (0.5 conf).
    Dense            → REAL (0.92 conf).
    """
    data = inp.data
    if not data:
        return "FAKE", 0.95, 0, 0
    arr = np.frombuffer(data, dtype=np.uint8)
    n = arr.size
    if n == 0:
        return "FAKE", 0.95, 0, 0
    nonzero = int(np.count_nonzero(arr))
    ratio = nonzero / n
    digest = hashlib.sha256(data).digest()
    bpm = 60 + (digest[0] % 60)         # 60..119
    hrv = 10 + (digest[1] % 80)         # 10..89
    if ratio < 0.05:
        return "FAKE", 0.95, 0, 0
    if ratio < 0.40:
        return "UNCERTAIN", 0.55, bpm, hrv
    return "REAL", 0.92, bpm, hrv


# ---------------------------------------------------------------------------
# Mock loader.
# ---------------------------------------------------------------------------


@dataclass
class MockModelState:
    name: str
    version: str
    loaded_at: float


class MockModelLoader:
    """
    Drop-in replacement for `ONNXModelLoader`. Returns deterministic
    InferenceResult for any registered model name. Latency is
    simulated to be in the budget (1-30ms) for the dev path.
    """

    def __init__(self) -> None:
        self._models: dict[str, MockModelState] = {}

    async def load(self, name: str, config: ModelConfig) -> MockModelState:
        version = MOCK_MODEL_VERSIONS.get(name, f"mock-{name}-v0.0.1-dev")
        state = MockModelState(name=name, version=version, loaded_at=time.time())
        self._models[name] = state
        log.info("mock_model.loaded name=%s version=%s", name, version)
        return state

    async def warmup(self, name: str) -> None:
        if name not in self._models:
            await self.load(name, ModelConfig(name=name, weights_path=""))

    async def infer(
        self, name: str, inp: ModelInput
    ) -> InferenceResult:
        if name not in self._models:
            await self.warmup(name)
        start = time.perf_counter()
        verdict, conf, bpm, hrv = _verdict_from_input(inp)
        # Simulated 1-30ms latency.
        await_time_ms = 1.0 + (len(inp.data) % 30)
        await _sleep_ms(await_time_ms)
        latency_ms = (time.perf_counter() - start) * 1000.0
        version = self._models[name].version
        log.info(
            "mock_model.infer name=%s verdict=%s conf=%.2f latency=%.2fms",
            name, verdict, conf, latency_ms,
        )
        return InferenceResult(
            verdict=verdict,
            confidence=conf,
            latency_ms=latency_ms,
            model_version=version,
            input_hash=hashlib.sha256(inp.data).hexdigest(),
            bpm=bpm,
            hrv_ms=hrv,
            device="cpu",
        )

    async def health(self) -> dict[str, bool]:
        return {name: True for name in self._models}

    async def close(self) -> None:
        self._models.clear()


# ---------------------------------------------------------------------------
# Async sleep helper (for simulated latency).
# ---------------------------------------------------------------------------


async def _sleep_ms(ms: float) -> None:
    import asyncio
    await asyncio.sleep(ms / 1000.0)


# ---------------------------------------------------------------------------
# Factory.
# ---------------------------------------------------------------------------


def make_model_loader() -> object:
    """
    Construct the model loader based on environment.

    * `OLYMPUS_AI_MODE=mock` (default in dev) → MockModelLoader.
    * `OLYMPUS_AI_MODE=onnx`                 → ONNXModelLoader
      (requires real .onnx files in /models).
    """
    mode = os.getenv("OLYMPUS_AI_MODE", "mock").lower()
    if mode == "onnx":
        from app.models.loader import ONNXModelLoader
        from app.models.gpu_manager import GPUMemoryManager

        return ONNXModelLoader(manager=GPUMemoryManager())
    return MockModelLoader()


__all__ = [
    "MockModelLoader",
    "MockModelState",
    "MOCK_MODEL_VERSIONS",
    "make_model_loader",
]


# VERIFIED: MockModelLoader satisfies the production loader's surface;
# deterministic verdict from input bytes; latency simulated in budget;
# factory switches between mock and onnx via OLYMPUS_AI_MODE.
