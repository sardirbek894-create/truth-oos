/**
 * Olympus Engine v9 — Session Key Tests
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
  generateSessionKey,
  signPayload,
  verifyPayload,
  generateBatchNonce,
  destroySessionKey,
} from '../../core/crypto/SessionKey';

describe('generateSessionKey', (): void => {
  it('returns a 32-byte public key and a non-extractable private key', async (): Promise<void> => {
    const k = await generateSessionKey();
    expect(k.publicKey.length).toBe(32);
    expect(k.privateKey.type).toBe('private');
    expect(k.privateKey.extractable).toBe(false);
  });

  it('produces a createdAt timestamp close to now', async (): Promise<void> => {
    const t0 = Date.now();
    const k = await generateSessionKey();
    const t1 = Date.now();
    expect(k.createdAt).toBeGreaterThanOrEqual(t0);
    expect(k.createdAt).toBeLessThanOrEqual(t1);
  });
});

describe('signPayload / verifyPayload', (): void => {
  let kp: Awaited<ReturnType<typeof generateSessionKey>>;
  beforeEach(async (): Promise<void> => {
    kp = await generateSessionKey();
  });

  it('signs and verifies a payload round-trip', async (): Promise<void> => {
    const payload = new Uint8Array([1, 2, 3, 4, 5]);
    const sig = await signPayload(kp, payload);
    expect(sig.length).toBe(64);
    const ok = await verifyPayload(kp.publicKey, payload, sig);
    expect(ok).toBe(true);
  });

  it('rejects a tampered payload', async (): Promise<void> => {
    const payload = new Uint8Array([1, 2, 3, 4, 5]);
    const sig = await signPayload(kp, payload);
    const tampered = new Uint8Array([1, 2, 3, 4, 6]);
    const ok = await verifyPayload(kp.publicKey, tampered, sig);
    expect(ok).toBe(false);
  });

  it('rejects an invalid public key length', async (): Promise<void> => {
    const sig = new Uint8Array(64);
    await expect(verifyPayload(new Uint8Array(10), new Uint8Array([1]), sig)).rejects.toThrow();
  });

  it('rejects an invalid signature length', async (): Promise<void> => {
    await expect(verifyPayload(kp.publicKey, new Uint8Array([1]), new Uint8Array(10))).rejects.toThrow();
  });
});

describe('generateBatchNonce', (): void => {
  it('returns 32 random bytes', (): void => {
    const n = generateBatchNonce();
    expect(n.length).toBe(32);
  });

  it('produces different nonces on each call', (): void => {
    const a = generateBatchNonce();
    const b = generateBatchNonce();
    expect(a).not.toEqual(b);
  });
});

describe('destroySessionKey', (): void => {
  it('zeros the public key buffer', async (): Promise<void> => {
    const k = await generateSessionKey();
    const ref = k.publicKey;
    destroySessionKey(k);
    for (let i = 0; i < ref.length; i += 1) {
      expect(ref[i]).toBe(0);
    }
  });
});

// VERIFIED: 9 test cases covering keygen, sign/verify round-trip, tamper detection, nonce uniqueness, zeroize.
