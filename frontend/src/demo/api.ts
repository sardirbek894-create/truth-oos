/**
 * Olympus Engine v9 — Demo API Client
 *
 * A thin fetch() wrapper used by the dev console (`App.tsx`).
 * The production frontend uses `api/client.ts` (Ed25519 signing,
 * retry/backoff, etc.); this one is intentionally minimal so the
 * dev console can run with zero crypto setup.
 */

const baseURL = (import.meta.env.VITE_API_URL as string) ?? '';

export interface HealthResponse {
  status: 'ok' | 'degraded' | 'down';
  db?: { primary: boolean; replicas: number };
  redis?: boolean;
  hsm?: boolean;
  models_loaded?: number;
}

export interface RegisterResponse {
  did: string;
  session_id: string;
  session_secret: string;
}

export interface ChallengeResponse {
  batch_id: string;
  nonces: string[];
  expires_at: string;
}

export interface VerifyResponse {
  decision: 'PASS' | 'CHALLENGE' | 'REJECT';
  risk_score: number;
  reason_code?: string;
  latency_ms?: number;
  verifier_results?: Record<string, unknown>;
  model_results?: Record<string, unknown>;
}

async function request<T>(method: string, path: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
  const res = await fetch(baseURL + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(headers ?? {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${method} ${path} → ${res.status} ${res.statusText}: ${text.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

export const apiClient = {
  health: () => request<HealthResponse>('GET', '/api/v1/health'),

  register: (body: { device_fingerprint: string; device_type: string; os_version: string }) =>
    request<RegisterResponse>('POST', '/api/v1/register', body),

  challenge: (sessionId: string, sessionSecret: string) =>
    request<ChallengeResponse>('GET', '/api/v1/challenge', undefined, {
      'X-Session-ID': sessionId,
      'X-Session-Secret': sessionSecret,
    }),

  verify: (params: { session_id: string; nonce: string; body: Record<string, unknown> }) =>
    request<VerifyResponse>('POST', '/api/v1/verify', params.body, {
      'X-Session-ID': params.session_id,
      'X-Batch-Nonce': params.nonce,
      'X-Signature': 'demo-sig',
      'X-Timestamp': String(Date.now()),
    }),
};
