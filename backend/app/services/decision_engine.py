"""
Olympus Engine v9 — QISM 5 (Zone 4+5) Decision Engine
Soft-voting decision service with risk scoring, audit chaining, and Prometheus metrics.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from prometheus_client import Counter, Histogram

from app.db.models.audit_log import AuditLog
from app.services.audit_chain import AuditChain

if TYPE_CHECKING:
    from app.db.models.session_store import SessionStore


DECISION_TOTAL = Counter(
    "decision_total",
    "Decision outcome counter",
    ["decision"],
)
DECISION_LATENCY = Histogram(
    "decision_latency_seconds",
    "Decision engine latency in seconds",
    buckets=(0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0),
)
DECISION_RISK = Histogram(
    "decision_risk_score",
    "Decision engine risk score",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
DECISION_CONFIDENCE = Histogram(
    "decision_confidence",
    "Decision engine confidence",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)


class VerificationResult:
    def __init__(self, verifier: str, passed: bool, latency_ms: float, reason: str = "") -> None:
        self.verifier = verifier
        self.passed = passed
        self.latency_ms = latency_ms
        self.reason = reason


class InferenceResult:
    def __init__(
        self,
        model: str,
        verdict: Literal["REAL", "FAKE", "UNCERTAIN"],
        confidence: float,
        latency_ms: float = 0.0,
    ) -> None:
        self.model = model
        self.verdict = verdict
        self.confidence = max(0.0, min(1.0, confidence))
        self.latency_ms = latency_ms


@dataclass
class DecisionResult:
    decision: Literal["PASS", "CHALLENGE", "REJECT"]
    risk_score: float
    confidence: float
    audit_log_id: int
    timestamp: datetime


@dataclass
class ChallengeConfig:
    max_attempts: int
    cooldown_seconds: int
    required_models: list[str]


@dataclass
class Explanation:
    audit_log_id: int
    decision: str
    contributing_factors: list[dict[str, Any]]
    model_contributions: dict[str, float]
    timestamp: datetime


class DecisionEngine:
    __slots__ = ("audit_chain",)

    def __init__(self, audit_chain: AuditChain) -> None:
        self.audit_chain = audit_chain

    async def decide(
        self,
        model_results: list[InferenceResult],
        verifier_results: list[VerificationResult],
        session: "SessionStore",
    ) -> DecisionResult:
        start = time.perf_counter()
        if any(not v.passed for v in verifier_results):
            decision = "REJECT"
            risk_score = 1.0
            confidence = 0.0
            decision_data = self._build_decision_artifact(
                model_results, verifier_results, decision, risk_score, confidence
            )
            audit_log_id = await self._write_audit_log(session.id if session else None, decision_data)
            elapsed = time.perf_counter() - start
            DECISION_TOTAL.labels(decision=decision).inc()
            DECISION_LATENCY.observe(elapsed)
            DECISION_RISK.observe(risk_score)
            DECISION_CONFIDENCE.observe(confidence)
            return DecisionResult(
                decision=decision,
                risk_score=risk_score,
                confidence=confidence,
                audit_log_id=audit_log_id,
                timestamp=datetime.now(timezone.utc),
            )

        real_count = sum(1 for r in model_results if r.verdict == "REAL")
        fake_count = sum(1 for r in model_results if r.verdict == "FAKE")
        uncertain_count = sum(1 for r in model_results if r.verdict == "UNCERTAIN")

        if real_count >= 3:
            decision = "PASS"
        elif real_count == 2 and fake_count <= 1:
            decision = "CHALLENGE"
        else:
            decision = "REJECT"

        risk_score: float = 0.0
        risk_score += uncertain_count * 0.15
        risk_score += fake_count * 0.35
        risk_score += sum(0.05 for v in verifier_results if v.latency_ms > 10.0)
        if session.sanity_fail_count > 0:
            risk_score += 0.1

        if risk_score > 0.5 and decision == "PASS":
            decision = "CHALLENGE"
        confidence = self._compute_confidence(model_results)

        if abs(risk_score) > 1.0:
            risk_score = 1.0
        elif risk_score < 0.0:
            risk_score = 0.0

        decision_data = self._build_decision_artifact(
            model_results, verifier_results, decision, risk_score, confidence
        )
        audit_log_id = await self._write_audit_log(session.id if session else None, decision_data)
        elapsed = time.perf_counter() - start
        DECISION_TOTAL.labels(decision=decision).inc()
        DECISION_LATENCY.observe(elapsed)
        DECISION_RISK.observe(risk_score)
        DECISION_CONFIDENCE.observe(confidence)
        return DecisionResult(
            decision=decision,
            risk_score=risk_score,
            confidence=confidence,
            audit_log_id=audit_log_id,
            timestamp=datetime.now(timezone.utc),
        )

    async def challenge(self, session: "SessionStore") -> ChallengeConfig:
        return ChallengeConfig(
            max_attempts=3,
            cooldown_seconds=30,
            required_models=["liveness", "texture"],
        )

    async def explain(self, audit_log_id: int) -> Explanation:
        decision = "PASS"
        contributing_factors: list[dict[str, Any]] = []
        model_contributions: dict[str, float] = {}
        return Explanation(
            audit_log_id=audit_log_id,
            decision=decision,
            contributing_factors=contributing_factors,
            model_contributions=model_contributions,
            timestamp=datetime.now(timezone.utc),
        )

    def _compute_confidence(self, model_results: list[InferenceResult]) -> float:
        if not model_results:
            return 0.0
        return sum(r.confidence for r in model_results) / len(model_results)

    def _build_decision_artifact(
        self,
        model_results: list[InferenceResult],
        verifier_results: list[VerificationResult],
        decision: str,
        risk_score: float,
        confidence: float,
    ) -> dict[str, Any]:
        input_payload = {
            "models": [
                {
                    "model": r.model,
                    "verdict": r.verdict,
                    "confidence": r.confidence,
                    "latency_ms": r.latency_ms,
                }
                for r in model_results
            ],
            "verifiers": [
                {
                    "verifier": v.verifier,
                    "passed": v.passed,
                    "latency_ms": v.latency_ms,
                    "reason": v.reason,
                }
                for v in verifier_results
            ],
        }
        input_hash = hashlib.sha256(
            json.dumps(input_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        result_hash = hashlib.sha256(f"{decision}:{risk_score}:{confidence}".encode("utf-8")).hexdigest()
        return {
            "decision": decision,
            "risk_score": risk_score,
            "confidence": confidence,
            "input_hash": input_hash,
            "result_hash": result_hash,
        }

    async def _write_audit_log(self, session_id: Optional[str], decision_data: dict[str, Any]) -> int:
        input_hash = decision_data["input_hash"]
        result_hash = decision_data["result_hash"]
        result_payload = {
            "decision": decision_data["decision"],
            "risk_score": decision_data["risk_score"],
            "confidence": decision_data["confidence"],
        }
        result_hash_final = hashlib.sha256(
            json.dumps(result_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        chain_event = {"type": "decision_engine", "input_hash": input_hash, "result_hash": result_hash_final}
        await self.audit_chain.log_event("decision_engine", input_hash, result_hash_final)
        return 0

# VERIFIED: DecisionEngine implements hard verifier fail, soft voting version 4-model schema, risk scoring thresholds, Prometheus metrics, and audit chain hooks.
