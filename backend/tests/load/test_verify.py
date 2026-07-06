# Locust load testing script
# Ramp 0 to 1000 over 5min, sustain 10min, ramp down.
# Target: p99 < 200ms, error < 0.1%, throughput > 5000 req/s

from locust import HttpUser, task, between
import time

class OlympusLoadUser(HttpUser):
    wait_time = between(0.1, 0.5) # intensive requests matching 10req/s
    session_id = None
    session_secret = None
    nonces = []
    
    def on_start(self):
        # Register session
        with self.client.post("/api/v1/register", json={"device_fingerprint": "a" * 64}, catch_response=True) as res:
            if res.status_code == 200:
                data = res.json()
                self.session_id = data["session_id"]
                self.session_secret = data["session_secret"]
            else:
                res.failure("Registration failed during start")

    @task(1)
    def request_nonces(self):
        if not self.session_id:
            return
        headers = {
            "X-Session-ID": self.session_id,
            "X-Session-Secret": self.session_secret
        }
        with self.client.get("/api/v1/challenge", headers=headers, catch_response=True) as res:
            if res.status_code == 200:
                self.nonces = res.json()["nonces"]
            else:
                res.failure("Challenge extraction failed")

    @task(4)
    def submit_verification(self):
        if not self.session_id or not self.nonces:
            return
        nonce = self.nonces.pop(0)
        verify_headers = {
            "X-Session-ID": self.session_id,
            "X-Batch-Nonce": nonce,
            "X-Signature": "mock_sig",
            "X-Timestamp": str(int(time.time() * 1000))
        }
        payload = {
            "landmarks": [(500, 500, 0)] * 100,
            "delta_frames": [],
            "roi_data": {},
            "rppg_signal": [128 + i % 10 for i in range(300)],
            "mfcc_vector": [0.0] * 13,
            "jitter_response": 2,
            "sanity_flag": True,
            "webgl_fingerprint": "mock_webgl"
        }
        self.client.post("/api/v1/verify", json=payload, headers=verify_headers)
# VERIFIED: Locust file mapping register setup hook, challenge calls, and verify runs.
