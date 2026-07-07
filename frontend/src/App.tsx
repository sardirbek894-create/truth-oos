import { useEffect, useState } from 'react';
import { apiClient, type HealthResponse, type RegisterResponse, type ChallengeResponse, type VerifyResponse } from './demo/api';
import { useScanStore } from './store/useScanStore';

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [session, setSession] = useState<RegisterResponse | null>(null);
  const [challenge, setChallenge] = useState<ChallengeResponse | null>(null);
  const [verify, setVerify] = useState<VerifyResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scanState = useScanStore((s) => s.state);

  const refresh = async () => {
    setBusy('health'); setError(null);
    try { setHealth(await apiClient.health()); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(null); }
  };

  useEffect(() => { refresh(); }, []);

  const handleRegister = async () => {
    setBusy('register'); setError(null);
    try {
      const fp = Array.from(crypto.getRandomValues(new Uint8Array(32)))
        .map((b) => b.toString(16).padStart(2, '0')).join('');
      setSession(await apiClient.register({
        device_fingerprint: fp, device_type: 'desktop', os_version: 'web',
      }));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(null); }
  };

  const handleChallenge = async () => {
    if (!session) return;
    setBusy('challenge'); setError(null);
    try {
      setChallenge(await apiClient.challenge(session.session_id, session.session_secret));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(null); }
  };

  const handleVerify = async () => {
    if (!session || !challenge) return;
    setBusy('verify'); setError(null);
    try {
      const landmarks: [number, number, number][] = Array.from({ length: 100 }, (_, i) => [500 + (i % 5), 500 + (i % 7), 0]);
      const rppg_signal = Array.from({ length: 300 }, (_, i) => 128 + (i % 11));
      setVerify(await apiClient.verify({
        session_id: session.session_id,
        nonce: challenge.nonces[0],
        body: {
          landmarks, delta_frames: [], roi_data: {},
          rppg_signal, mfcc_vector: Array(13).fill(0),
          jitter_response: 2, sanity_flag: true, webgl_fingerprint: 'mock_webgl',
        },
      }));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(null); }
  };

  return (
    <div className="app">
      <h1>Olympus Engine v9</h1>
      <p className="subtitle">Bank-grade biometric liveness detection — dev console</p>

      {error && (
        <div className="card" style={{ borderColor: 'var(--danger)' }}>
          <h2 style={{ color: 'var(--danger)' }}>Error</h2>
          <pre style={{ whiteSpace: 'pre-wrap' }}>{error}</pre>
        </div>
      )}

      <div className="card">
        <h2>System Health</h2>
        <div className="kv">
          <span className="k">Status</span>
          <span className="v">
            {health ? <span className={`status ${health.status === 'ok' ? 'ok' : 'warn'}`}>{health.status}</span> : '—'}
          </span>
          <span className="k">DB primary</span>
          <span className="v">{health?.db?.primary ? '✓' : '✗'}</span>
          <span className="k">Redis</span>
          <span className="v">{health?.redis ? '✓' : '✗'}</span>
          <span className="k">HSM</span>
          <span className="v">{health?.hsm ? '✓' : '✗'}</span>
          <span className="k">AI models</span>
          <span className="v">{health?.models_loaded ?? '—'}</span>
        </div>
        <button className="btn" onClick={refresh} disabled={busy === 'health'}>
          {busy === 'health' ? '…' : 'Refresh'}
        </button>
      </div>

      <div className="card">
        <h2>1. Register Session</h2>
        <button className="btn" onClick={handleRegister} disabled={busy === 'register'}>
          {busy === 'register' ? '…' : 'POST /api/v1/register'}
        </button>
        {session && (
          <div className="kv" style={{ marginTop: '1rem' }}>
            <span className="k">DID</span><span className="v">{session.did}</span>
            <span className="k">Session ID</span><span className="v">{session.session_id}</span>
          </div>
        )}
      </div>

      <div className="card">
        <h2>2. Request Challenge</h2>
        <button className="btn" onClick={handleChallenge} disabled={!session || busy === 'challenge'}>
          {busy === 'challenge' ? '…' : 'GET /api/v1/challenge'}
        </button>
        {challenge && (
          <div className="kv" style={{ marginTop: '1rem' }}>
            <span className="k">Batch ID</span><span className="v">{challenge.batch_id}</span>
            <span className="k">Nonces</span><span className="v">{challenge.nonces.length} (first: {challenge.nonces[0]?.slice(0, 16)}…)</span>
          </div>
        )}
      </div>

      <div className="card">
        <h2>3. Verify</h2>
        <button className="btn" onClick={handleVerify} disabled={!challenge || busy === 'verify'}>
          {busy === 'verify' ? '…' : 'POST /api/v1/verify'}
        </button>
        {verify && (
          <div className="kv" style={{ marginTop: '1rem' }}>
            <span className="k">Decision</span>
            <span className="v">
              <span className={`status ${verify.decision === 'PASS' ? 'ok' : verify.decision === 'CHALLENGE' ? 'warn' : 'err'}`}>
                {verify.decision}
              </span>
            </span>
            <span className="k">Risk score</span><span className="v">{verify.risk_score?.toFixed(3) ?? '—'}</span>
            <span className="k">Reason</span><span className="v">{verify.reason_code ?? '—'}</span>
            <span className="k">Latency</span><span className="v">{verify.latency_ms?.toFixed(1) ?? '—'} ms</span>
          </div>
        )}
        <pre>{verify ? JSON.stringify(verify, null, 2) : '// press Verify to call /api/v1/verify'}</pre>
      </div>

      <div className="card">
        <h2>Scan State Machine</h2>
        <p>Current: <span className={`status ${scanState === 'idle' ? 'idle' : 'ok'}`}>{scanState}</span></p>
        <p style={{ color: '#8a92a3', fontSize: '0.85rem' }}>
          Zustand state from <code>useScanStore</code> — idle → requesting → warming → scanning → analyzing → passed/failed/error
        </p>
      </div>
    </div>
  );
}
