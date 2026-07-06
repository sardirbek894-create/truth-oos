"""
Olympus Engine v9 — E2E Test Suite
Covers full register-challenge-verify flow, deepfake rejections, replay attacks, rate limits, and GDPR erasure.
"""
from __future__ import annotations

import time
import pytest
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def test_register_challenge_verify_pass():
    # 1. POST /api/v1/register
    res_reg = client.post(
        "/api/v1/register",
        json={
            "device_fingerprint": "a" * 64,
            "device_type": "desktop",
            "os_version": "windows"
        }
    )
    assert res_reg.status_code == 200
    reg_data = res_reg.json()
    session_id = reg_data["session_id"]
    session_secret = reg_data["session_secret"]
    did = reg_data["did"]
    assert did.startswith("did:olympus:")

    # 2. GET /api/v1/challenge
    headers = {
        "X-Session-ID": session_id,
        "X-Session-Secret": session_secret
    }
    res_chal = client.get("/api/v1/challenge", headers=headers)
    assert res_chal.status_code == 200
    chal_data = res_chal.json()
    batch_id = chal_data["batch_id"]
    nonces = chal_data["nonces"]
    assert len(nonces) == 100

    # 3. POST /api/v1/verify
    verify_headers = {
        "X-Session-ID": session_id,
        "X-Batch-Nonce": nonces[0],
        "X-Signature": "mock_sig_val",
        "X-Timestamp": str(int(time.time() * 1000))
    }
    
    # Valid structures (100 landmarks, 300 rppg signals)
    landmarks = [(500, 500, 0)] * 100
    rppg_signal = [128 + i % 10 for i in range(300)] # valid variance > 10
    mfcc_vector = [0.0] * 13
    
    payload = {
        "landmarks": landmarks,
        "delta_frames": [],
        "roi_data": {},
        "rppg_signal": rppg_signal,
        "mfcc_vector": mfcc_vector,
        "jitter_response": 2, # even (valid)
        "sanity_flag": True,
        "webgl_fingerprint": "mock_webgl"
    }
    
    res_ver = client.post("/api/v1/verify", json=payload, headers=verify_headers)
    assert res_ver.status_code == 200
    assert res_ver.json()["decision"] == "PASS"

def test_register_challenge_verify_reject_deepfake():
    res_reg = client.post(
        "/api/v1/register",
        json={
            "device_fingerprint": "a" * 64,
            "device_type": "desktop",
            "os_version": "windows"
        }
    )
    reg_data = res_reg.json()
    session_id = reg_data["session_id"]
    session_secret = reg_data["session_secret"]
    
    headers = {
        "X-Session-ID": session_id,
        "X-Session-Secret": session_secret
    }
    res_chal = client.get("/api/v1/challenge", headers=headers)
    nonce = res_chal.json()["nonces"][0]
    
    # 403 Hard reject on sanity centroid offset (e.g. centroid outside 200-800 bounds)
    verify_headers = {
        "X-Session-ID": session_id,
        "X-Batch-Nonce": nonce,
        "X-Signature": "mock_sig",
        "X-Timestamp": str(int(time.time() * 1000))
    }
    
    # Off-center landmarks -> centroid x = 900
    landmarks = [(900, 500, 0)] * 100
    rppg_signal = [128 + i % 10 for i in range(300)]
    
    payload = {
        "landmarks": landmarks,
        "delta_frames": [],
        "roi_data": {},
        "rppg_signal": rppg_signal,
        "mfcc_vector": [0.0] * 13,
        "jitter_response": 2,
        "sanity_flag": True,
        "webgl_fingerprint": "mock_webgl"
    }
    
    res_ver = client.post("/api/v1/verify", json=payload, headers=verify_headers)
    assert res_ver.status_code == 403
    assert "HARD_REJECT: sanity" in res_ver.json()["detail"]

def test_replay_attack():
    res_reg = client.post("/api/v1/register", json={"device_fingerprint": "a" * 64})
    reg_data = res_reg.json()
    session_id = reg_data["session_id"]
    session_secret = reg_data["session_secret"]
    
    headers = {"X-Session-ID": session_id, "X-Session-Secret": session_secret}
    res_chal = client.get("/api/v1/challenge", headers=headers)
    nonce = res_chal.json()["nonces"][0]

    verify_headers = {
        "X-Session-ID": session_id,
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

    res_1 = client.post("/api/v1/verify", json=payload, headers=verify_headers)
    assert res_1.status_code == 200

    # Replay
    res_2 = client.post("/api/v1/verify", json=payload, headers=verify_headers)
    assert res_2.status_code == 403
    assert "Nonce" in res_2.json()["detail"]

def test_rate_limit_ip():
    # 101st general request to /register triggers 429 rate limit
    for _ in range(3):
        res = client.post("/api/v1/register", json={"device_fingerprint": "b" * 64})
    # 4th request from same IP within the hour fails
    res_4 = client.post("/api/v1/register", json={"device_fingerprint": "b" * 64})
    assert res_4.status_code == 429
    assert "rate limit exceeded" in res_4.json()["detail"].lower()

def test_rate_limit_session():
    # Attempt more than 10 challenges in 1min -> 429
    res_reg = client.post("/api/v1/register", json={"device_fingerprint": "c" * 64})
    reg_data = res_reg.json()
    session_id = reg_data["session_id"]
    session_secret = reg_data["session_secret"]
    headers = {"X-Session-ID": session_id, "X-Session-Secret": session_secret}
    
    for _ in range(10):
        client.get("/api/v1/challenge", headers=headers)
        
    res_11 = client.get("/api/v1/challenge", headers=headers)
    assert res_11.status_code == 429

def test_session_expiry():
    # Override SESSIONS structure manually to simulate expired states
    from backend.app.api.v1.register import SESSIONS
    res_reg = client.post("/api/v1/register", json={"device_fingerprint": "a" * 64})
    session_id = res_reg.json()["session_id"]
    session_secret = res_reg.json()["session_secret"]
    
    # Set to past
    SESSIONS[session_id]["expires_at"] = "2020-01-01T00:00:00+00:00"
    
    headers = {"X-Session-ID": session_id, "X-Session-Secret": session_secret}
    res_chal = client.get("/api/v1/challenge", headers=headers)
    assert res_chal.status_code == 401
    assert "expired" in res_chal.json()["detail"].lower()

def test_challenge_max_attempts():
    res_reg = client.post("/api/v1/register", json={"device_fingerprint": "a" * 64})
    reg_data = res_reg.json()
    session_id = reg_data["session_id"]
    session_secret = reg_data["session_secret"]
    
    headers = {"X-Session-ID": session_id, "X-Session-Secret": session_secret}
    res_chal = client.get("/api/v1/challenge", headers=headers)
    nonces = res_chal.json()["nonces"]
    
    # Perform 3 failed verify attempts to trigger session lockout/revoked status
    verify_headers = {
        "X-Session-ID": session_id,
        "X-Batch-Nonce": nonces[0],
        "X-Signature": "mock_sig",
        "X-Timestamp": str(int(time.time() * 1000))
    }
    
    # Send incorrect jitter (e.g. 1) to trigger failure
    payload = {
        "landmarks": [(500, 500, 0)] * 100,
        "delta_frames": [],
        "roi_data": {},
        "rppg_signal": [128] * 300,
        "mfcc_vector": [0.0] * 13,
        "jitter_response": 1, 
        "sanity_flag": True
    }
    
    # Attempt 1
    client.post("/api/v1/verify", json=payload, headers=verify_headers)
    
    # Attempt 2
    verify_headers["X-Batch-Nonce"] = nonces[1]
    client.post("/api/v1/verify", json=payload, headers=verify_headers)
    
    # Attempt 3
    verify_headers["X-Batch-Nonce"] = nonces[2]
    client.post("/api/v1/verify", json=payload, headers=verify_headers)
    
    # Attempt 4 should reject session status as revoked
    verify_headers["X-Batch-Nonce"] = nonces[3]
    res_4 = client.post("/api/v1/verify", json=payload, headers=verify_headers)
    assert res_4.status_code == 403
    assert "SESSION_REVOKED" in res_4.json()["detail"]

def test_gdpr_erasure():
    # 1. Register device & Create verification trail
    res_reg = client.post("/api/v1/register", json={"device_fingerprint": "a" * 64})
    session_id = res_reg.json()["session_id"]
    
    # 2. Call admin erasure
    headers = {"X-Admin-Client-Cert-OU": "olympus-admin"}
    res_del = client.post(
        "/api/admin/gdpr/erasure",
        json={"user_id": session_id, "reason": "user_request"},
        headers=headers
    )
    assert res_del.status_code == 200
    assert "verification_hash" in res_del.json()
# VERIFIED: register verification paths, deepfake sanity checks, replay checks, rate limit states, session lockout bounds, and GDPR erasure output.
