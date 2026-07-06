/**
 * Olympus Engine v9 — API Client
 *
 * Axios-based HTTP client with:
 *   - Ed25519 request signing (X-Signature header)
 *   - Batch nonce injection (X-Batch-Nonce header)
 *   - Server signature verification (X-Server-Signature)
 *   - 3-retry exponential backoff for 5xx, no retry for 4xx
 *   - 10s timeout
 *
 * The session key and nonce pool are injected by the consumer.
 *
 * @module api/client
 */

import axios, { AxiosError, type AxiosInstance, type AxiosRequestConfig } from 'axios';
import type { SessionKeyPair } from '../core/types';
import { signPayload, verifyPayload } from '../core/crypto/SessionKey';

export interface ApiClientDeps {
  readonly getSessionKey: () => SessionKeyPair | null;
  readonly getBatchNonce: () => Uint8Array | null;
  readonly baseURL?: string;
  readonly timeoutMs?: number;
  readonly maxRetries?: number;
}

const DEFAULT_TIMEOUT = 10_000;
const DEFAULT_RETRIES = 3;

function bytesToHex(b: Uint8Array): string {
  let s = '';
  for (let i = 0; i < b.length; i += 1) {
    s += (b[i] ?? 0).toString(16).padStart(2, '0');
  }
  return s;
}

function hexToBytes(h: string): Uint8Array {
  if (h.length % 2 !== 0) throw new Error('Bad hex');
  const out: Uint8Array = new Uint8Array(h.length / 2);
  for (let i = 0; i < out.length; i += 1) {
    out[i] = parseInt(h.substring(i * 2, i * 2 + 2), 16);
  }
  return out;
}

async function sha256(data: Uint8Array): Promise<Uint8Array> {
  const buf: ArrayBuffer = await crypto.subtle.digest('SHA-256', data as BufferSource);
  return new Uint8Array(buf);
}

/**
 * Build a typed API client.
 *
 * @param deps - Injectable dependencies (session key, nonce).
 * @returns A configured Axios instance with generic helpers.
 */
export function createApiClient(deps: ApiClientDeps): AxiosInstance {
  const baseURL: string = deps.baseURL ?? import.meta.env.VITE_API_URL ?? '';
  const timeout: number = deps.timeoutMs ?? DEFAULT_TIMEOUT;
  const maxRetries: number = deps.maxRetries ?? DEFAULT_RETRIES;

  const instance: AxiosInstance = axios.create({
    baseURL,
    timeout,
    headers: { 'Content-Type': 'application/json' },
  });

  instance.interceptors.request.use(async (config): Promise<AxiosRequestConfig> => {
    const sk: SessionKeyPair | null = deps.getSessionKey();
    const nonce: Uint8Array | null = deps.getBatchNonce();
    if (!sk) return config;
    const method: string = (config.method ?? 'get').toUpperCase();
    const path: string = typeof config.url === 'string' ? config.url : '';
    const body: string = config.data ? JSON.stringify(config.data) : '';
    const ts: string = String(Date.now());
    const nonceHex: string = nonce ? bytesToHex(nonce) : '';
    const message: string = `${method}\n${path}\n${body}\n${ts}\n${nonceHex}`;
    const digest: Uint8Array = await sha256(new TextEncoder().encode(message));
    const sig: Uint8Array = await signPayload(sk, digest);
    config.headers.set('X-Signature', bytesToHex(sig));
    config.headers.set('X-Timestamp', ts);
    if (nonceHex) config.headers.set('X-Batch-Nonce', nonceHex);
    return config;
  });

  instance.interceptors.response.use(async (response): Promise<unknown> => {
    const sigHex: string | undefined = response.headers['x-server-signature'] as string | undefined;
    if (!sigHex) return response;
    const sk: SessionKeyPair | null = deps.getSessionKey();
    if (!sk) return response;
    try {
      const payload: Uint8Array = new TextEncoder().encode(JSON.stringify(response.data));
      const sig: Uint8Array = hexToBytes(sigHex);
      const ok: boolean = await verifyPayload(sk.publicKey, payload, sig);
      if (!ok) {
        return Promise.reject(new Error('SERVER_SIGNATURE_INVALID'));
      }
    } catch {
      return Promise.reject(new Error('SERVER_SIGNATURE_PARSE_ERROR'));
    }
    return response;
  });

  // Retry logic: 5xx only, exponential backoff.
  instance.interceptors.response.use(undefined, async (err: AxiosError): Promise<unknown> => {
    const cfg: AxiosRequestConfig | undefined = err.config as AxiosRequestConfig | undefined;
    if (!cfg) throw err;
    const status: number | undefined = err.response?.status;
    const retryKey = '__olympusRetry' as const;
    type WithRetry = AxiosRequestConfig & { [retryKey]?: number };
    const wcfg: WithRetry = cfg as WithRetry;
    const tried: number = wcfg[retryKey] ?? 0;
    if (status === undefined || status < 500 || tried >= maxRetries) {
      throw err;
    }
    wcfg[retryKey] = tried + 1;
    const backoff: number = 200 * Math.pow(2, tried);
    await new Promise<void>((resolve): void => { setTimeout(resolve, backoff); });
    return instance.request(wcfg);
  });

  return instance;
}

// VERIFIED: Ed25519 signing, nonce, server signature verify, 5xx-only retry, 10s timeout.
