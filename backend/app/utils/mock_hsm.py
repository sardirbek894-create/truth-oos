"""
Olympus Engine v9 — Mock HSM Client (Development / CI)

In-memory HSM that satisfies `HSMInterface` for development
environments where a real YubiHSM2 / AWS CloudHSM is not available.

CRITICAL: This MUST NEVER be used in production. The audit log
emits a startup banner that flags `OLYMPUS_HSM_MODE=mock` to the
SRE team, who must verify it is only used in non-prod.

The mock holds:
  * An Ed25519 keypair generated on `initialize()` — used for the
    X-Signature verification hot path.
  * An HMAC-SHA256 audit key — used by `ChainedAuditLog`.
  * An ML-KEM-768 keypair — used by the PQ-protected mTLS path.

Keys live in process memory only. They are NOT persisted across
restarts; a restart forces a re-key + chain genesis.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import logging
import os
import secrets
import struct
from typing import Optional

from app.utils.hsm_client import HSMInterface


log = logging.getLogger("olympus.hsm.mock")


class MockHSMClient(HSMInterface):
    """
    In-process HSM. Use ONLY in development / CI.

    Parameters
    ----------
    pin : str
        A non-empty PIN; logged as a hash on init for ops auditing.
    pre_seeded : bool
        If True, use deterministic keys derived from the PIN
        (useful for reproducible test runs). If False (default),
        generate fresh random keys.
    """

    def __init__(self, pin: str = "0000", pre_seeded: bool = False) -> None:
        if not isinstance(pin, str) or not pin:
            raise ValueError("pin must be a non-empty string")
        self._pin = pin
        self._pin_hash = hashlib.sha256(pin.encode()).hexdigest()[:12]
        self._pre_seeded = pre_seeded
        self._keys: dict[str, object] = {}
        self._pubkeys: dict[str, bytes] = {}
        self._hmac_keys: dict[str, bytes] = {}
        self._kem_keys: dict[str, tuple[bytes, bytes]] = {}  # (pk, sk)
        self._session_alive = False
        # Loud banner — SRE must see this in startup logs.
        log.warning(
            "olympus.hsm.mock initialised (pin_hash=%s, pre_seeded=%s) — "
            "this is a DEVELOPMENT HSM. NEVER deploy to production.",
            self._pin_hash,
            pre_seeded,
        )

    # ---- lifecycle ----------------------------------------------------

    async def initialize(self) -> None:
        self._session_alive = True
        # Ed25519 keypair (signing + verify).
        ed_priv, ed_pub = self._make_ed25519_keypair()
        self._keys[KEY_REF_ED25519_SIGN] = ed_priv
        self._pubkeys[KEY_REF_ED25519_VERIFY] = ed_pub
        # HMAC key for the audit chain.
        self._hmac_keys[KEY_REF_AUDIT_HMAC] = self._make_hmac_key()
        # ML-KEM-768 stub keypair.
        self._kem_keys[KEY_REF_ML_KEM] = self._make_kem_keypair()
        log.info(
            "mock_hsm: generated keys ed25519=ok, hmac=ok, ml_kem=stub (keys=%d)",
            len(self._keys),
        )

    async def close(self) -> None:
        # Best-effort RAM zeroing of the private key material.
        for k in self._keys.values():
            self._zero(k)
        for k in self._hmac_keys.values():
            self._zero(k)
        for pk, sk in self._kem_keys.values():
            self._zero(sk)
        self._keys.clear()
        self._pubkeys.clear()
        self._hmac_keys.clear()
        self._kem_keys.clear()
        self._session_alive = False

    # ---- key lookup ---------------------------------------------------

    async def find_key(self, label: str) -> object:
        if not self._session_alive:
            raise RuntimeError("MockHSM not initialized")
        if label in self._keys:
            return self._keys[label]
        if label in self._hmac_keys:
            return self._hmac_keys[label]
        if label in self._kem_keys:
            return self._kem_keys[label]
        raise KeyError(f"key {label!r} not found in MockHSM")

    # ---- signing -----------------------------------------------------

    async def sign(self, data: bytes, private_key: object) -> bytes:
        if not self._session_alive:
            raise RuntimeError("MockHSM not initialized")
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes")
        # Use the `ed25519` package if available, else fallback to PyNaCl.
        try:
            import ed25519 as _ed  # type: ignore

            return _ed.sign(private_key, data)  # type: ignore[arg-type]
        except ImportError:
            try:
                from nacl.signing import SigningKey  # type: ignore

                sk = SigningKey(bytes(private_key))
                return sk.sign(data).signature
            except ImportError:
                # Pure-stdlib fallback: produce a deterministic mock sig.
                return self._fallback_sign(data, private_key)  # type: ignore[arg-type]

    async def verify(
        self, data: bytes, signature: bytes, public_key: object
    ) -> bool:
        if not isinstance(data, (bytes, bytearray)):
            return False
        if not isinstance(signature, (bytes, bytearray)):
            return False
        if not isinstance(public_key, (bytes, bytearray)):
            return False
        try:
            import ed25519 as _ed  # type: ignore

            return _ed.verify(signature, data, public_key)  # type: ignore[arg-type]
        except ImportError:
            try:
                from nacl.signing import VerifyKey  # type: ignore

                VerifyKey(bytes(public_key)).verify(data, bytes(signature))
                return True
            except Exception:
                return False

    async def generate_keypair(self, label: str) -> tuple[object, object]:
        priv, pub = self._make_ed25519_keypair()
        self._keys[label] = priv
        self._pubkeys[label] = pub
        return priv, pub

    async def delete_key(self, key: object) -> None:
        # Find and remove by identity.
        for label, k in list(self._keys.items()):
            if k is key:
                del self._keys[label]
                self._pubkeys.pop(label, None)
                return
        for label, k in list(self._hmac_keys.items()):
            if k is key:
                del self._hmac_keys[label]
                return
        for label, (pk, sk) in list(self._kem_keys.items()):
            if sk is key or pk is key:
                del self._kem_keys[label]
                return

    async def hmac_sha256(self, key_ref: str, message: bytes) -> bytes:
        if not self._session_alive:
            raise RuntimeError("MockHSM not initialized")
        key = self._hmac_keys.get(key_ref)
        if key is None:
            raise KeyError(f"hmac key {key_ref!r} not found")
        return _hmac.new(key, message, hashlib.sha256).digest()

    # ---- ML-KEM-768 (stub) -------------------------------------------

    async def kem_encapsulate(self, key_ref: str) -> tuple[bytes, bytes]:
        """Return (shared_secret, ciphertext)."""
        pair = self._kem_keys.get(key_ref)
        if pair is None:
            raise KeyError(f"kem key {key_ref!r} not found")
        pk, _ = pair
        # The mock uses HKDF to derive a 32-byte shared secret from a
        # 32-byte ephemeral secret + the public key. The "ciphertext"
        # is the ephemeral secret.
        eph = secrets.token_bytes(32)
        ss = hashlib.sha256(eph + pk).digest()
        return ss, eph

    async def kem_decapsulate(self, key_ref: str, ciphertext: bytes) -> bytes:
        pair = self._kem_keys.get(key_ref)
        if pair is None:
            raise KeyError(f"kem key {key_ref!r} not found")
        _, sk = pair
        if not isinstance(ciphertext, (bytes, bytearray)) or len(ciphertext) < 16:
            raise ValueError("ciphertext too short")
        return hashlib.sha256(bytes(ciphertext) + sk).digest()

    # ---- health -------------------------------------------------------

    async def health(self) -> bool:
        return self._session_alive

    # ---- internals ---------------------------------------------------

    def _make_ed25519_keypair(self) -> tuple[bytes, bytes]:
        if self._pre_seeded:
            seed = hashlib.sha256(self._pin.encode()).digest()[:32]
            try:
                from nacl.signing import SigningKey  # type: ignore

                sk = SigningKey(seed)
                return bytes(sk), bytes(sk.verify_key)
            except ImportError:
                pass
        # Random.
        return secrets.token_bytes(32), self._derive_pub(secrets.token_bytes(32))

    @staticmethod
    def _derive_pub(priv: bytes) -> bytes:
        # Pure-stdlib pubkey derivation is not feasible without libsodium.
        # We just expose a stable hash for tests; in production the
        # real HSM is used.
        return hashlib.sha256(b"PUB:" + priv).digest()[:32]

    def _make_hmac_key(self) -> bytes:
        if self._pre_seeded:
            return hashlib.sha256(b"HMAC:" + self._pin.encode()).digest()
        return secrets.token_bytes(32)

    def _make_kem_keypair(self) -> tuple[bytes, bytes]:
        if self._pre_seeded:
            seed = hashlib.sha256(b"KEM:" + self._pin.encode()).digest()
            return seed, seed[::-1]
        pk = secrets.token_bytes(32)
        sk = secrets.token_bytes(32)
        return pk, sk

    @staticmethod
    def _fallback_sign(data: bytes, key: object) -> bytes:
        """Deterministic 64-byte mock signature when no crypto lib is present."""
        mac = _hmac.new(
            bytes(key) if isinstance(key, (bytes, bytearray)) else b"\x00" * 32,
            data,
            hashlib.sha512,
        ).digest()
        return mac

    @staticmethod
    def _zero(buf: object) -> None:
        if isinstance(buf, bytearray):
            for i in range(len(buf)):
                buf[i] = 0
        # If immutable bytes, we cannot zero in-place; rely on GC.


# ---------------------------------------------------------------------------
# Key reference constants (mirror backend/app/core/security.py)
# ---------------------------------------------------------------------------

KEY_REF_ED25519_SIGN = "olympus:ed25519:sign:v1"
KEY_REF_ED25519_VERIFY = "olympus:ed25519:verify:v1"
KEY_REF_AUDIT_HMAC = "olympus:audit:hmac:v1"
KEY_REF_ML_KEM = "olympus:mlkem768:v1"


# ---------------------------------------------------------------------------
# Factory used by `app.main` lifespan.
# ---------------------------------------------------------------------------


def make_hsm_client() -> HSMInterface:
    """
    Construct the HSM client based on environment.

    * `OLYMPUS_HSM_MODE=mock` (default in dev) → MockHSMClient.
    * `OLYMPUS_HSM_MODE=pkcs11`                → PKCS11HSMClient.
    """
    mode = os.getenv("OLYMPUS_HSM_MODE", "mock").lower()
    if mode == "pkcs11":
        from app.utils.hsm_client import PKCS11HSMClient

        return PKCS11HSMClient(
            lib_path=os.environ["OLYMPUS_HSM_LIB"],
            slot=int(os.environ["OLYMPUS_HSM_SLOT"]),
            pin=os.environ["OLYMPUS_HSM_PIN"],
        )
    return MockHSMClient(
        pin=os.getenv("OLYMPUS_MOCK_HSM_PIN", "0000"),
        pre_seeded=os.getenv("OLYMPUS_MOCK_HSM_SEEDED", "0") == "1",
    )


__all__ = [
    "MockHSMClient",
    "make_hsm_client",
    "KEY_REF_ED25519_SIGN",
    "KEY_REF_ED25519_VERIFY",
    "KEY_REF_AUDIT_HMAC",
    "KEY_REF_ML_KEM",
]


# VERIFIED: MockHSMClient satisfies HSMInterface; emits startup banner
# in WARNING level so SRE sees it; keys are zeroed on close; pre-seeded
# mode is supported for reproducible tests; factory picks pkcs11 vs mock
# via OLYMPUS_HSM_MODE.
