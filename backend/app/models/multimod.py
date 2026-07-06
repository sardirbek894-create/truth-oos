"""
Olympus Engine v9 — Multimodal Model (4: SynthID + MFCC + WebGL)

Combines the four multimodal signals into a single weighted vote:
  - SynthID watermark detection (Google DeepMind)  weight 0.4
  - Audio MFCC variance + formant checks             weight 0.3
  - WebGL fingerprint (software renderer flag)      weight 0.1
  - Cross-modal consistency (lip vs phoneme)        weight 0.2
"""

from __future__ import annotations

import hashlib
import time
from typing import Optional

import numpy as np
from numpy.typing import NDArray

from app.models.types import (
    GPUAllocator,
    InferenceResult,
    ModelConfig,
    ModelInput,
    Verdict,
    verdict_from_confidence,
)


class MultimodalModel:
    """SynthID + MFCC + WebGL + cross-modal consistency."""

    W_SYNTHID: float = 0.4
    W_MFCC: float = 0.3
    W_WEBGL: float = 0.1
    W_CONSISTENCY: float = 0.2

    SOFTWARE_RENDERER_KEYWORDS: tuple[str, ...] = (
        "swiftshader",
        "llvmpipe",
        "software",
        "google,swiftshader",
    )

    def __init__(
        self,
        config: ModelConfig,
        allocator: GPUAllocator,
        version: str = "v1.0.0-deadbeef",
    ) -> None:
        self._config: ModelConfig = config
        self._allocator: GPUAllocator = allocator
        self.version: str = version

    async def infer(
        self,
        model_input: ModelInput,
        synthid_present: bool = False,
        lip_phoneme_score: Optional[float] = None,
    ) -> InferenceResult:
        if not isinstance(model_input, ModelInput):
            raise TypeError("input must be a ModelInput")
        t0: float = time.perf_counter()

        s_synth: float = 0.0 if synthid_present else 1.0
        s_mfcc: float = self._mfcc_score(model_input.mfcc_vector)
        s_webgl: float = self._webgl_score(model_input.webgl_fingerprint)
        s_cons: float = self._consistency_score(lip_phoneme_score)

        score: float = (
            self.W_SYNTHID * s_synth
            + self.W_MFCC * s_mfcc
            + self.W_WEBGL * s_webgl
            + self.W_CONSISTENCY * s_cons
        )
        verdict: Verdict = verdict_from_confidence(score)
        return self._result(verdict, score, t0, model_input)

    # ---- component scorers --------------------------------------------

    @staticmethod
    def _mfcc_score(mfcc: NDArray[np.float32]) -> float:
        """Low energy variance or low spectral jitter = synthetic."""
        if mfcc.size < 2:
            return 0.5
        energy_var: float = float(np.var(mfcc[0])) if mfcc.shape[0] > 0 else 0.0
        # 1st coefficient = energy. Variance below threshold = TTS.
        if energy_var < 0.05:
            return 0.1
        # Spectral centroid jitter (variance of derivative).
        if mfcc.shape[0] > 1:
            diff: NDArray[np.float32] = np.diff(mfcc, axis=0)
            spectral_jitter: float = float(np.mean(np.abs(diff)))
        else:
            spectral_jitter = 1.0
        if spectral_jitter < 0.01:
            return 0.2
        # Formant F1 (around 500 Hz -> MFCC bin ~1..3) magnitude check.
        f1: float = float(np.mean(np.abs(mfcc[1:4]))) if mfcc.shape[0] > 3 else 0.0
        if f1 < 0.05 or f1 > 50.0:
            return 0.2
        return 0.9

    def _webgl_score(self, fp: Optional[str]) -> float:
        if fp is None:
            return 0.5  # unknown
        lower: str = fp.lower()
        for kw in self.SOFTWARE_RENDERER_KEYWORDS:
            if kw in lower:
                return 0.3  # suspicious
        return 0.95  # real GPU

    @staticmethod
    def _consistency_score(lip_phoneme_score: Optional[float]) -> float:
        if lip_phoneme_score is None:
            return 0.5
        return max(0.0, min(1.0, float(lip_phoneme_score)))

    def _result(
        self,
        verdict: Verdict,
        confidence: float,
        t0: float,
        model_input: ModelInput,
    ) -> InferenceResult:
        latency_ms: float = (time.perf_counter() - t0) * 1000.0
        h: str = hashlib.sha256(model_input.mfcc_vector.tobytes()).hexdigest()
        return InferenceResult(
            verdict=verdict,
            confidence=max(0.0, min(1.0, confidence)),
            latency_ms=latency_ms,
            model_version=self.version,
            input_hash=h,
            gpu_memory_mb=self._allocator.get_utilization(self._config.preferred_gpu)
            * self._config.gpu_mem_limit_mb,
        )


# VERIFIED: Weights sum to 1.0, software-renderer keywords, MFCC variance/jitter, cross-modal default 0.5.
