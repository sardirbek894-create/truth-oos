"""Integration tests for the full inference pipeline."""

import numpy as np
import pytest

from app.models.gpu_manager import GPUMemoryManager
from app.models.liveness import LivenessModel
from app.models.loader import ONNXModelLoader
from app.models.multimod import MultimodalModel
from app.models.registry import ModelRegistry
from app.models.rppg import RPPGModel
from app.models.texture import TextureModel
from app.models.types import (
    GPUAllocator,
    ModelConfig,
    ModelInput,
)


def _landmarks() -> np.ndarray:
    out: np.ndarray = np.zeros((100, 3), dtype=np.int16)
    for i in range(100):
        out[i] = (500 + (i % 5), 500 + (i % 7), 0)
    return out


def _roi(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (40, 40, 3), dtype=np.uint8)


def _mfcc() -> np.ndarray:
    rng = np.random.default_rng(2)
    return rng.normal(0, 1, (13,)).astype(np.float32)


def _rppg_signal() -> list[int]:
    """Simulate a plausible heart-rate signal at ~70 BPM."""
    import math
    t: np.ndarray = np.arange(300) / 30.0
    sig: np.ndarray = (
        100
        + 5 * np.sin(2 * math.pi * 1.2 * t)
        + np.random.default_rng(3).normal(0, 0.5, 300)
    )
    return [int(v) for v in sig.tolist()]


def _input() -> ModelInput:
    return ModelInput(
        landmarks=_landmarks(),
        roi_forehead=_roi(0),
        roi_left_cheek=_roi(1),
        roi_right_cheek=_roi(2),
        rppg_signal=_rppg_signal(),
        mfcc_vector=_mfcc(),
        webgl_fingerprint="ANGLE (NVIDIA, T4)",
    )


def _allocator() -> GPUAllocator:
    return GPUMemoryManager(gpu_count=1, mem_per_gpu_mb=4096).allocator


def _config() -> ModelConfig:
    return ModelConfig(
        onnx_path="/dev/null",
        input_shape=(1, 3, 224, 224),
        output_shape=(1, 2),
        preferred_gpu=0,
        weight_hash="0" * 64,
    )


# ---- happy path -----------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_real_signals():
    alloc = _allocator()
    cfg = _config()

    live = LivenessModel(cfg, loader=None, allocator=alloc)  # type: ignore[arg-type]
    tex = TextureModel(cfg, loader=None, allocator=alloc)  # type: ignore[arg-type]
    rppg = RPPGModel(cfg, allocator=alloc)
    multi = MultimodalModel(cfg, allocator=alloc)

    inp = _input()
    lbp_hist: np.ndarray = np.zeros(256, dtype=np.uint8)
    r1 = await live.infer(inp)
    r2 = await tex.infer(inp, lbp_hist=lbp_hist, laplacian_var=1_000_000, deep=False)
    r3 = await rppg.infer(inp, forehead_signal=inp.rppg_signal)
    r4 = await multi.infer(inp, synthid_present=False, lip_phoneme_score=0.9)

    # All four models should be tolerant of "no ONNX session" — we expect
    # at minimum 3 of 4 to be REAL or UNCERTAIN (rPPG is deterministic).
    verdicts: list[str] = [r1.verdict, r2.verdict, r3.verdict, r4.verdict]
    assert "FAKE" not in verdicts or verdicts.count("FAKE") <= 1


# ---- deepfake rejection ---------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_deepfake_rejected():
    alloc = _allocator()
    cfg = _config()

    tex = TextureModel(cfg, loader=None, allocator=alloc)  # type: ignore[arg-type]
    rppg = RPPGModel(cfg, allocator=alloc)

    # Deepfake signals: uniform LBP, constant rPPG.
    inp = _input()
    lbp_uniform: np.ndarray = np.ones(256, dtype=np.uint8)
    r2 = await tex.infer(inp, lbp_hist=lbp_uniform, laplacian_var=1_000_000, deep=False)
    r3 = await rppg.infer(inp, forehead_signal=[128] * 300)
    assert r2.verdict == "FAKE"
    assert r3.verdict == "FAKE"


# ---- GPU OOM fallback -----------------------------------------------------


@pytest.mark.asyncio
async def test_gpu_oom_returns_false():
    alloc = GPUMemoryManager(gpu_count=1, mem_per_gpu_mb=512).allocator
    # Try to allocate 90% of memory twice.
    ok1: bool = await alloc.allocate(0, 460)
    ok2: bool = await alloc.allocate(0, 460)
    assert ok1 is True
    assert ok2 is False


# ---- Model version mismatch ----------------------------------------------


@pytest.mark.asyncio
async def test_model_registry_rejects_bad_version():
    reg = ModelRegistry()

    class _Stub:
        name: str = "stub"
        version: str = "v1.0.0-abc1234"

        async def infer(self, x):
            return None

    with pytest.raises(Exception):
        await reg.register("stub", _Stub(), "not-a-version")  # type: ignore[arg-type]
    await reg.register("stub", _Stub(), "v1.0.0-abc1234")
    assert "stub" in reg
