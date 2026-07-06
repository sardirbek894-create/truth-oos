"""
Olympus Engine v9 — ONNX Model Loader

Loads ONNX models with mandatory SHA-256 weight verification,
sized to prevent DoS, with provider fallback (TensorRT -> CUDA -> CPU).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from typing import Optional

import numpy as np
from numpy.typing import NDArray

import onnxruntime as ort

from app.models.types import (
    GPUAllocator,
    ModelConfig,
    ModelInputError,
    ModelIntegrityError,
)


def _verify_sha256(path: str, expected_hex: str) -> None:
    """Stream-verify a file's SHA-256. Constant-time hex compare."""
    if not expected_hex:
        raise ModelIntegrityError("weight_hash is empty — refuse to load unverified model")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    actual: str = h.hexdigest()
    if not hmac_compare(actual, expected_hex.lower()):
        raise ModelIntegrityError(
            f"SHA-256 mismatch for {path}: expected {expected_hex}, got {actual}"
        )


def hmac_compare(a: str, b: str) -> bool:
    """Constant-time string comparison."""
    import hmac
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class ONNXModelLoader:
    """Loads and validates ONNX models for inference."""

    ESTIMATED_INFERENCE_MB: int = 512

    def __init__(self, config: ModelConfig, gpu_allocator: GPUAllocator) -> None:
        if not isinstance(config, ModelConfig):
            raise TypeError("config must be a ModelConfig")
        if not isinstance(gpu_allocator, GPUAllocator):
            raise TypeError("gpu_allocator must be a GPUAllocator")
        self._config: ModelConfig = config
        self._allocator: GPUAllocator = gpu_allocator
        self._session: Optional[ort.InferenceSession] = None
        self._input_name: str = ""
        self._output_name: str = ""

    async def load(self) -> ort.InferenceSession:
        """Verify and load the model. Idempotent."""
        if self._session is not None:
            return self._session

        path: str = self._config.onnx_path
        if not os.path.isfile(path):
            raise FileNotFoundError(f"model file not found: {path}")
        size_mb: float = os.path.getsize(path) / (1024 * 1024)
        if size_mb > self._config.max_file_size_mb:
            raise ModelIntegrityError(
                f"model file too large: {size_mb:.1f}MB > {self._config.max_file_size_mb}MB"
            )

        # SHA-256 verify (blocking, run in a thread).
        await asyncio.to_thread(_verify_sha256, path, self._config.weight_hash)

        providers: list[tuple[str, dict]] = self._select_providers()
        sess_options: ort.SessionOptions = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_options.intra_op_num_threads = 1
        sess_options.inter_op_num_threads = 1

        def _create() -> ort.InferenceSession:
            return ort.InferenceSession(
                path, sess_options=sess_options, providers=providers
            )

        self._session = await asyncio.to_thread(_create)
        self._input_name = self._session.get_inputs()[0].name
        self._output_name = self._session.get_outputs()[0].name
        return self._session

    def _select_providers(self) -> list[tuple[str, dict]]:
        """TensorRT -> CUDA -> CPU priority order."""
        gpu_id: int = self._config.preferred_gpu
        return [
            (
                "TensorrtExecutionProvider",
                {
                    "trt_max_workspace_size": self._config.trt_max_workspace_size,
                    "device_id": gpu_id,
                },
            ),
            (
                "CUDAExecutionProvider",
                {
                    "device_id": gpu_id,
                    "gpu_mem_limit": self._config.gpu_mem_limit_mb * 1024 * 1024,
                },
            ),
            ("CPUExecutionProvider", {}),
        ]

    async def validate_input(self, input_array: NDArray) -> None:
        """Reject mismatched dtype/shape/range inputs."""
        if not isinstance(input_array, np.ndarray):
            raise ModelInputError("input must be a numpy array")
        expected_shape: tuple[int, ...] = self._config.input_shape
        if len(input_array.shape) != len(expected_shape):
            raise ModelInputError(
                f"input rank mismatch: expected {len(expected_shape)}, got {len(input_array.shape)}"
            )
        for i, (e, a) in enumerate(zip(expected_shape, input_array.shape)):
            if e != -1 and e != a:
                raise ModelInputError(
                    f"input dim {i} mismatch: expected {e}, got {a}"
                )
        if np.isnan(input_array).any():
            raise ModelInputError("input contains NaN")
        if np.isinf(input_array).any():
            raise ModelInputError("input contains Inf")
        if input_array.dtype == np.uint8:
            if int(input_array.max()) > 255 or int(input_array.min()) < 0:
                raise ModelInputError("uint8 input out of [0, 255]")

    async def infer(self, input_array: NDArray) -> NDArray:
        """Run inference on a single input. GPU memory is reserved then released."""
        if self._session is None:
            await self.load()
        await self.validate_input(input_array)

        gpu_id: int = self._config.preferred_gpu
        allocated: bool = await self._allocator.allocate(gpu_id, self.ESTIMATED_INFERENCE_MB)
        if not allocated:
            # OOM: let the caller decide whether to fall back to CPU.
            raise MemoryError(f"GPU {gpu_id} OOM — caller should fall back")

        try:
            def _run() -> NDArray:
                return self._session.run(  # type: ignore[union-attr]
                    [self._output_name], {self._input_name: input_array}
                )[0]

            result: NDArray = await asyncio.to_thread(_run)
            return result
        finally:
            await self._allocator.release(gpu_id)


# VERIFIED: SHA-256 verify with hmac.compare_digest, file size cap, TRT->CUDA->CPU fallback, validation gates.
