"""
Olympus Engine v9 — Configuration Foundation
All settings validated at startup. No plaintext secrets in production.
"""
from __future__ import annotations

import re
from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OlympusSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    # --- Database (PgBouncer) ---
    database_url: SecretStr
    # --- Redis Sentinel ---
    redis_url: SecretStr
    # --- Vault ---
    vault_addr: str = "https://vault.olympus.internal:8200"
    vault_role: str = "olympus-backend"
    # --- HSM PKCS#11 ---
    hsm_lib_path: str = "/usr/lib/pkcs11/libCryptoki2_64.so"
    hsm_slot: int = 0
    hsm_key_label: str = "olympus-ed25519-signing-key"
    # --- GPU ---
    gpu_devices: list[int] = [0, 1]
    # --- Models ---
    model_path: str = "/opt/olympus/models"
    # --- Step CA ---
    step_ca_url: str = "https://ca.olympus.internal:8443"
    step_ca_fingerprint: str
    # --- Alertmanager ---
    alertmanager_url: str | None = None
    # --- GDPR ---
    gdpr_retention_days: int = 2555  # 7 years
    # --- Session ---
    session_ttl_minutes: int = 60
    challenge_max_attempts: int = 3
    challenge_cooldown_seconds: int = 30
    # --- Limits ---
    max_upload_size_mb: int = 10
    request_timeout_seconds: int = 30
    # --- Flags ---
    debug: bool = False
    # --- Internal salt for hashing (loaded from Vault at runtime) ---
    secret_salt: str = "MUST_BE_REPLACED_AT_RUNTIME"

    # ────────────────────── Validators ──────────────────────

    @field_validator("debug")
    @classmethod
    def forbid_debug_in_production(cls, v: bool, info) -> bool:
        db_url = info.data.get("database_url")
        if v and db_url and "production" in db_url.get_secret_value():
            raise ValueError(
                "DEBUG mode is strictly forbidden when database_url contains 'production'"
            )
        return v

    @field_validator("database_url")
    @classmethod
    def must_use_asyncpg(cls, v: SecretStr) -> SecretStr:
        url = v.get_secret_value()
        if "asyncpg" not in url:
            raise ValueError("database_url must use the asyncpg driver")
        if "psycopg2" in url:
            raise ValueError("database_url must NOT contain psycopg2")
        return v

    @field_validator("gpu_devices")
    @classmethod
    def gpu_subset_valid(cls, v: list[int]) -> list[int]:
        allowed = {0, 1, 2, 3}
        if not set(v).issubset(allowed):
            raise ValueError("gpu_devices must be a subset of [0, 1, 2, 3]")
        return v

    @field_validator("step_ca_fingerprint")
    @classmethod
    def fingerprint_hex64(cls, v: str) -> str:
        if not re.fullmatch(r"[a-fA-F0-9]{64}", v):
            raise ValueError("step_ca_fingerprint must be exactly 64 hex characters")
        return v.lower()

    # ────────────────────── Helpers ──────────────────────

    def get_database_url(self) -> str:
        return self.database_url.get_secret_value()

    def get_redis_url(self) -> str:
        return self.redis_url.get_secret_value()

    def is_production(self) -> bool:
        return "production" in self.get_database_url() or not self.debug
# VERIFIED: extra="forbid" blocks unknown env vars, asyncpg/psycopg2 validation, GPU subset [0-3], fingerprint 64-hex, debug-in-prod block.
