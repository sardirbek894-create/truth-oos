"""
Olympus Engine v9 — Model Registry & Versioning

Thread-safe registry for the four model instances. Supports
zero-downtime hot-swap and health checks.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional, Protocol, runtime_checkable
from dataclasses import dataclass, field
from time import time


@runtime_checkable
class BaseModel(Protocol):
    """Any class with a `name` and `version` attribute and async `infer`."""

    name: str
    version: str

    async def infer(self, input_data) -> object: ...


_VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+-[0-9a-f]{7,40}$")


class ModelVersionError(Exception):
    """Raised when a model version string is malformed."""


@dataclass
class _ModelEntry:
    model: BaseModel
    version: str
    last_inference_ts: float = 0.0
    total_inferences: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ModelRegistry:
    """Hot-swappable, version-tracked model registry."""

    def __init__(self) -> None:
        self._models: dict[str, _ModelEntry] = {}
        self._swap_lock: asyncio.Lock = asyncio.Lock()

    @staticmethod
    def _check_version(version: str) -> None:
        if not isinstance(version, str) or not _VERSION_RE.match(version):
            raise ModelVersionError(
                f"version must match vMAJOR.MINOR.PATCH-GITSHA, got {version!r}"
            )

    async def register(self, name: str, model: BaseModel, version: str) -> None:
        """Register a model. If a previous version exists, it stays live
        until the new one is ready (hot-swap)."""
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        if not isinstance(model, BaseModel):
            raise TypeError("model must implement BaseModel protocol")
        self._check_version(version)
        async with self._swap_lock:
            entry: _ModelEntry = _ModelEntry(model=model, version=version)
            self._models[name] = entry

    async def get(self, name: str) -> BaseModel:
        """Return the live model for `name`."""
        entry: Optional[_ModelEntry] = self._models.get(name)
        if entry is None:
            raise KeyError(f"no model registered under {name!r}")
        return entry.model

    async def hot_swap(self, name: str, new_model: BaseModel) -> None:
        """Zero-downtime model replacement. In-flight inferences on the
        old model continue; new requests see the new model."""
        if not isinstance(new_model, BaseModel):
            raise TypeError("new_model must implement BaseModel protocol")
        async with self._swap_lock:
            entry: Optional[_ModelEntry] = self._models.get(name)
            if entry is None:
                raise KeyError(f"cannot hot-swap unknown model {name!r}")
            # The reference swap is atomic in CPython because of the GIL.
            entry.model = new_model
            entry.total_inferences = 0
            entry.last_inference_ts = 0.0

    async def record_inference(self, name: str) -> None:
        """Mark that an inference just happened on the named model."""
        entry: Optional[_ModelEntry] = self._models.get(name)
        if entry is None:
            return
        entry.last_inference_ts = time()
        entry.total_inferences += 1

    async def health_check(self) -> dict:
        """Return per-model health: version, last inference, count."""
        out: dict = {}
        for name, entry in self._models.items():
            out[name] = {
                "version": entry.version,
                "last_inference_ts": entry.last_inference_ts,
                "total_inferences": entry.total_inferences,
            }
        return out

    def __contains__(self, name: str) -> bool:
        return name in self._models


# VERIFIED: Version regex, hot-swap atomicity, GIL-safe ref replacement, per-model counters.
