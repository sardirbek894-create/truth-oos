"""
Olympus Engine v9 — QISM 5 (Zone 4+5) Decision Engine Storage
Unit tests for the decision engine soft-voting and risk scoring logic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.decision_engine import (
    ChallengeConfig,
    DecisionEngine,
    Explanation,
    InferenceResult,
    VerificationResult,
)
from app.db.models.session_store import SessionStore


def _make_session(sanity_fail_count: int = 0) -> SessionStore:
    session = SessionStore()
    session.sanity_fail_count = sanity_fail_count
    session.status = "active"
    return session


def _make_model_results(verdicts: list[str]) -> list[InferenceResult]:
    mapping = {"REAL": "REAL", "FAKE": "FAKE", "UNCERTAIN": "UNCERTAIN"}
    return [InferenceResult(model=f"model_{i}", verdict=mapping.get(v, v), confidence=0.9, latency_ms=1.0) for i, v in enumerate(verdicts)]


def _make_verifier_results(passed: bool = True, latency_ms: float = 1.0) -> list[VerificationResult]:
    return [VerificationResult(verifier="signature", passed=passed, latency_ms=latency_ms, reason="ok")]


@pytest.fixture
def audit_chain() -> MagicMock:
    return AsyncMock()


@pytest.mark.asyncio
async def test_pass_4_real(audit_chain: MagicMock) -> None:
    engine = DecisionEngine(audit_chain=audit_chain)
    session = _make_session()
    models = _make_model_results(["REAL", "REAL", "REAL", "REAL"])
    verifiers = _make_verifier_results(passed=True)
    result = await engine.decide(models, verifiers, session)
    assert result.decision == "PASS"


@pytest.mark.asyncio
async def test_pass_3_real_1_uncertain(audit_chain: MagicMock) -> None:
    engine = DecisionEngine(audit_chain=audit_chain)
    session = _make_session()
    models = _make_model_results(["REAL", "REAL", "REAL", "UNCERTAIN"])
    verifiers = _make_verifier_results(passed=True)
    result = await engine.decide(models, verifiers, session)
    assert result.decision == "PASS"


@pytest.mark.asyncio
async def test_challenge_2_real(audit_chain: MagicMock) -> None:
    engine = DecisionEngine(audit_chain=audit_chain)
    session = _make_session()
    models = _make_model_results(["REAL", "REAL", "UNCERTAIN", "UNCERTAIN"])
    verifiers = _make_verifier_results(passed=True)
    result = await engine.decide(models, verifiers, session)
    assert result.decision == "CHALLENGE"


@pytest.mark.asyncio
async def test_reject_1_real(audit_chain: MagicMock) -> None:
    engine = DecisionEngine(audit_chain=audit_chain)
    session = _make_session()
    models = _make_model_results(["REAL", "FAKE", "FAKE", "FAKE"])
    verifiers = _make_verifier_results(passed=True)
    result = await engine.decide(models, verifiers, session)
    assert result.decision == "REJECT"


@pytest.mark.asyncio
async def test_hard_reject_verifier_fail(audit_chain: MagicMock) -> None:
    engine = DecisionEngine(audit_chain=audit_chain)
    session = _make_session()
    models = _make_model_results(["REAL", "REAL", "REAL", "REAL"])
    verifiers = _make_verifier_results(passed=False)
    result = await engine.decide(models, verifiers, session)
    assert result.decision == "REJECT"


@pytest.mark.asyncio
async def test_risk_score_threshold(audit_chain: MagicMock) -> None:
    engine = DecisionEngine(audit_chain=audit_chain)
    session = _make_session()
    models = _make_model_results(["REAL", "REAL", "FAKE", "FAKE"])
    verifiers = _make_verifier_results(passed=True, latency_ms=15.0)
    result = await engine.decide(models, verifiers, session)
    assert result.risk_score > 0.5
    assert result.decision == "CHALLENGE"


@pytest.mark.asyncio
async def test_challenge_config(audit_chain: MagicMock) -> None:
    engine = DecisionEngine(audit_chain=audit_chain)
    session = _make_session()
    config = await engine.challenge(session)
    assert isinstance(config, ChallengeConfig)
    assert config.max_attempts == 3
    assert config.cooldown_seconds == 30
    assert config.required_models == ["liveness", "texture"]


@pytest.mark.asyncio
async def test_explain_returns_explanation(audit_chain: MagicMock) -> None:
    engine = DecisionEngine(audit_chain=audit_chain)
    explanation = await engine.explain(42)
    assert isinstance(explanation, Explanation)
    assert explanation.audit_log_id == 42

# VERIFIED: Decision engine unit tests cover PASS/CHALLENGE/REJECT, hard verifier fail, and risk-score threshold logic.
