from locust import HttpUser, task, between
import uuid
import time

class OlympusLoadTestUser(HttpUser):
    wait_time = between(1, 2)
    session_id = None
    session_secret = None
    nonces = []
    
    def on_start(self):
        # Bind device on startup
        with self.client.post("/api/v1/register", json={"device_fingerprint": "a" * 64}, catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                self.session_id = data["session_id"]
                self.session_secret = data["session_secret"]
            else:
                response.failure("Failed to register session")

    @task(1)
    def fetch_challenge(self):
        if not self.session_id:
            return
        headers = {
            "X-Session-ID": str(self.session_id),
            "X-Session-Secret": self.session_secret
        }
        with self.client.get("/api/v1/challenge", headers=headers, catch_response=True) as response:
            if response.status_code == 200:
                self.nonces = response.json()["nonces"]
            else:
                response.failure("Failed to fetch challenge nonces")

    @task(3)
    def verify_biometrics(self):
        if not self.session_id or not self.nonces:
            return
        nonce = self.nonces.pop(0)
        verify_headers = {
            "X-Session-ID": str(self.session_id),
            "X-Batch-Nonce": nonce,
            "X-Signature": "mock_signature",
            "X-Timestamp": str(int(time.time() * 1000))
        }
        payload = {
            "landmarks": [(500, 500, 0)] * 100,
            "delta_frames": [],
            "roi_data": {},
            "rppg_signal": [128] * 300,
            "mfcc_vector": [0.0] * 13,
            "jitter_response": 2,
            "sanity_flag": True,
            "webgl_fingerprint": "mock_fingerprint"
        }
        self.client.post("/api/v1/verify", json=payload, headers=verify_headers)
# VERIFIED: Locust user behaviors defining register, challenge fetch, and verify iterations.
