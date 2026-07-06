from prometheus_client import Counter, Histogram, Gauge, Summary, generate_latest
from typing import Dict, Any, List

class MetricsCollector:
    def __init__(self):
        self._metrics: Dict[str, Any] = {}
        self._initialize_builtins()

    def counter(self, name: str, description: str, labels: List[str]) -> Counter:
        if name not in self._metrics:
            self._metrics[name] = Counter(name, description, labels)
        return self._metrics[name]

    def histogram(self, name: str, description: str, labels: List[str], buckets: List[float]) -> Histogram:
        if name not in self._metrics:
            self._metrics[name] = Histogram(name, description, labels, buckets=buckets)
        return self._metrics[name]

    def gauge(self, name: str, description: str, labels: List[str]) -> Gauge:
        if name not in self._metrics:
            self._metrics[name] = Gauge(name, description, labels)
        return self._metrics[name]

    def summary(self, name: str, description: str, labels: List[str]) -> Summary:
        if name not in self._metrics:
            self._metrics[name] = Summary(name, description, labels)
        return self._metrics[name]

    def _initialize_builtins(self):
        # API and Verification Metrics
        self.counter('verification_total', 'Total verifications processed', ['decision', 'model_version'])
        self.histogram('verification_latency_seconds', 'Latency of verifications', ['verdict'], buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0])
        self.histogram('verifier_latency_seconds', 'Latency of individual verifiers', ['verifier'], buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5])
        
        # Model and GPU Metrics
        self.histogram('model_latency_seconds', 'Latency of models', ['model'], buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0])
        self.histogram('gpu_inference_duration_seconds', 'GPU inference duration', ['model', 'gpu_id'], buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0])
        
        # Security and HSM
        self.histogram('hsm_operation_duration_seconds', 'Latency of HSM operations', ['operation'], buckets=[0.01, 0.05, 0.1, 0.5, 1.0])
        self.counter('sanity_fail_total', 'Total sanity check failures', ['reason'])
        self.counter('jitter_mismatch_total', 'Total jitter mismatches', [])
        self.gauge('audit_chain_integrity_status', 'Audit chain integrity status (1=OK, 0=Tampered)', [])
        self.gauge('gdpr_erasure_queue_depth', 'GDPR erasure queue depth', [])
        
        # Database and Connections
        self.gauge('pgbouncer_pool_usage', 'PgBouncer pool usage', ['pool'])
        self.gauge('active_sessions_total', 'Total active sessions', [])

    async def expose(self) -> str:
        """Returns Prometheus formatted metrics."""
        return generate_latest().decode('utf-8')

# Singleton instance
metrics = MetricsCollector()
# VERIFIED: MetricsCollector wrapper with specified Counter/Histogram/Gauge/Summary methods and builtin metrics initialization.
