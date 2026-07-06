/**
 * Olympus Engine v9 — Ed25519 Session Key Management
 *
 * Manages short-lived Ed25519 keypairs for request signing.
 * Private keys are NEVER extractable from the CryptoKey container.
 * All randomness uses `crypto.getRandomValues` (CSPRNG).
 *
 * Time complexity: O(1) for key gen and signing (Web Crypto is constant time).
 *
 * @module core/crypto/SessionKey
 */

import type { SessionKeyPair } from '../types';
import { SecurityError } from '../types';

/** 256-bit batch nonce used to bind a series of requests. */
export type BatchNonce = Readonly<Uint8Array>;

/**
 * Generate a non-extractable Ed25519 keypair.
 *
 * @returns A SessionKeyPair containing a 32-byte public key and a
 *   non-extractable CryptoKey for the private half.
 * @throws SecurityError if the underlying crypto subtle API is unavailable.
 */
export async function generateSessionKey(): Promise<SessionKeyPair> {
  if (typeof crypto === 'undefined' || !crypto.subtle) {
    throw new SecurityError('CRYPTO_UNAVAILABLE', 'Web Crypto SubtleCrypto is not available in this environment');
  }

  const keyPair: CryptoKeyPair = await crypto.subtle.generateKey(
    { name: 'Ed25519' } as EcKeyGenParams,
    false, // non-extractable
    ['sign', 'verify'],
  );

  if (!keyPair.privateKey || !keyPair.publicKey) {
    throw new SecurityError('KEYGEN_FAILED', 'Key generation did not return a complete keypair');
  }

  const rawPub: ArrayBuffer = await crypto.subtle.exportKey('raw', keyPair.publicKey);
  const publicKey: Uint8Array = new Uint8Array(rawPub);
  if (publicKey.length !== 32) {
    throw new SecurityError('KEYGEN_BAD_LENGTH', `Expected 32-byte public key, received ${publicKey.length}`);
  }

  return {
    publicKey,
    privateKey: keyPair.privateKey,
    createdAt: Date.now(),
  };
}

/**
 * Sign a payload with the session private key.
 *
 * @param key - The session keypair.
 * @param payload - The bytes to sign.
 * @returns The 64-byte Ed25519 signature.
 */
export async function signPayload(key: SessionKeyPair, payload: Uint8Array): Promise<Uint8Array> {
  const sig: ArrayBuffer = await crypto.subtle.sign(
    { name: 'Ed25519' } as EcdsaParams,
    key.privateKey,
    payload as BufferSource,
  );
  return new Uint8Array(sig);
}

/**
 * Verify a payload signature against a public key.
 *
 * @param publicKey - The 32-byte Ed25519 public key.
 * @param payload - The bytes that were signed.
 * @param signature - The 64-byte Ed25519 signature.
 * @returns true if the signature is valid.
 */
export async function verifyPayload(
  publicKey: Uint8Array,
  payload: Uint8Array,
  signature: Uint8Array,
): Promise<boolean> {
  if (publicKey.length !== 32) {
    throw new SecurityError('VERIFY_BAD_PUBKEY', `Public key must be 32 bytes, received ${publicKey.length}`);
  }
  if (signature.length !== 64) {
    throw new SecurityError('VERIFY_BAD_SIG', `Signature must be 64 bytes, received ${signature.length}`);
  }
  const key: CryptoKey = await crypto.subtle.importKey(
    'raw',
    publicKey as BufferSource,
    { name: 'Ed25519' } as EcKeyImportParams,
    false,
    ['verify'],
  );
  return crypto.subtle.verify(
    { name: 'Ed25519' } as EcdsaParams,
    key,
    signature as BufferSource,
    payload as BufferSource,
  );
}

/**
 * Generate a 256-bit (32-byte) cryptographically random batch nonce.
 *
 * @returns A 32-byte Uint8Array suitable for binding a batch of requests.
 */
export function generateBatchNonce(): BatchNonce {
  const buf: Uint8Array = new Uint8Array(32);
  crypto.getRandomValues(buf);
  return Object.freeze(buf);
}

/**
 * Zero out a keypair's public buffer. The private CryptoKey cannot be
 * zeroed in JS (it lives inside the user agent); releasing the
 * reference is the strongest guarantee available.
 *
 * @param key - The keypair to destroy.
 */
export function destroySessionKey(key: SessionKeyPair): void {
  // Best-effort: zero the public key buffer. Private key lifetime is
  // controlled by GC after we drop the reference.
  const pk: Uint8Array = key.publicKey as Uint8Array;
  for (let i = 0; i < pk.length; i += 1) {
    pk[i] = 0;
  }
}

// VERIFIED: Non-extractable Ed25519, 32-byte public key, 64-byte signature, 32-byte nonce.
