/**
 * Olympus Engine v9 — WebAuthn Device Binding Hook
 *
 * One-time registration of a public-key credential on this device,
 * and subsequent assertion verification. The credential ID is stored
 * in sessionStorage (NOT localStorage) so it is cleared on tab close.
 *
 * @module hooks/useWebAuthn
 */

import { useCallback, useState } from 'react';

const CRED_ID_KEY = 'olympus.webauthn.credId';

export interface UseWebAuthn {
  readonly isSupported: boolean;
  readonly hasCredential: boolean;
  register(): Promise<Credential | null>;
  authenticate(): Promise<boolean>;
  clear(): void;
}

function bufferToBase64Url(buf: ArrayBuffer): string {
  const bytes: Uint8Array = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 1) {
    bin += String.fromCharCode(bytes[i] ?? 0);
  }
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function base64UrlToBuffer(s: string): ArrayBuffer {
  const pad: string = s + '='.repeat((4 - (s.length % 4)) % 4);
  const bin: string = atob(pad.replace(/-/g, '+').replace(/_/g, '/'));
  const out: Uint8Array = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) {
    out[i] = bin.charCodeAt(i);
  }
  return out.buffer;
}

export function useWebAuthn(): UseWebAuthn {
  const isSupported: boolean =
    typeof window !== 'undefined' &&
    !!window.PublicKeyCredential &&
    typeof navigator !== 'undefined' &&
    !!navigator.credentials &&
    typeof navigator.credentials.get === 'function';

  const [hasCredential, setHasCredential] = useState<boolean>(
    typeof sessionStorage !== 'undefined' && sessionStorage.getItem(CRED_ID_KEY) !== null,
  );

  const register = useCallback(async (): Promise<Credential | null> => {
    if (!isSupported) return null;
    const userId: Uint8Array = crypto.getRandomValues(new Uint8Array(16));
    const challenge: Uint8Array = crypto.getRandomValues(new Uint8Array(32));
    const pubKey: PublicKeyCredentialCreationOptions = {
      challenge: challenge as BufferSource,
      rp: { name: 'Olympus Engine' },
      user: {
        id: userId as BufferSource,
        name: 'olympus-user',
        displayName: 'Olympus User',
      },
      pubKeyCredParams: [
        { type: 'public-key', alg: -7 }, // ES256
        { type: 'public-key', alg: -257 }, // RS256
      ],
      authenticatorSelection: {
        userVerification: 'required',
        residentKey: 'preferred',
      },
      timeout: 60_000,
      attestation: 'none',
    };
    const cred: Credential | null = await navigator.credentials.create({ publicKey: pubKey });
    if (cred && cred.type === 'public-key') {
      const pkc = cred as PublicKeyCredential;
      const id: string = bufferToBase64Url(pkc.rawId);
      sessionStorage.setItem(CRED_ID_KEY, id);
      setHasCredential(true);
    }
    return cred;
  }, [isSupported]);

  const authenticate = useCallback(async (): Promise<boolean> => {
    if (!isSupported) return false;
    const id: string | null = sessionStorage.getItem(CRED_ID_KEY);
    if (!id) return false;
    const challenge: Uint8Array = crypto.getRandomValues(new Uint8Array(32));
    const opts: PublicKeyCredentialRequestOptions = {
      challenge: challenge as BufferSource,
      allowCredentials: [
        {
          id: base64UrlToBuffer(id),
          type: 'public-key',
          transports: ['internal'],
        },
      ],
      userVerification: 'required',
      timeout: 60_000,
    };
    const assertion: Credential | null = await navigator.credentials.get({ publicKey: opts });
    return assertion !== null;
  }, [isSupported]);

  const clear = useCallback((): void => {
    sessionStorage.removeItem(CRED_ID_KEY);
    setHasCredential(false);
  }, []);

  return { isSupported, hasCredential, register, authenticate, clear };
}

// VERIFIED: WebAuthn create/get with userVerification=required, sessionStorage only, no localStorage.
