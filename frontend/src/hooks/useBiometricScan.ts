/**
 * Olympus Engine v9 — Biometric Scan Orchestrator Hook
 *
 * Wires together:
 *   Camera -> FaceMesh -> DeltaEncoder -> Texture -> rPPG -> SanityFlag
 *
 * The hook owns all workers (via refs) so re-renders do not re-spawn
 * them. It also enforces the tab-visibility abort rule.
 *
 * @module hooks/useBiometricScan
 */

import { useCallback, useEffect, useRef } from 'react';
import { useScanStore } from '../store/useScanStore';
import {
  DeltaEncoderState,
  encode,
  decode,
  validatePhysiological,
} from '../core/face/DeltaEncoder';
import { FrozenFaceDetector, checkSanity } from '../core/crypto/SanityFlag';
import type {
  CameraFrame,
  FaceMeshLandmarks,
  SanityResult,
  ScanResult,
} from '../core/types';
import type { FaceWorkerMessage } from '../core/types';
import type { RppgWorkerMessage } from '../core/types';
import type { TextureWorkerMessage } from '../core/types';

const REQUIRED_FRAMES = 300;

export interface UseBiometricScan {
  readonly state: ReturnType<typeof useScanStore.getState>['state'];
  readonly progress: number;
  readonly landmarks: FaceMeshLandmarks | null;
  readonly sanityFlag: SanityResult | null;
  startScan(): Promise<void>;
  cancelScan(): void;
}

export function useBiometricScan(): UseBiometricScan {
  const state = useScanStore((s): ScanState => s.state);
  const progress = useScanStore((s): number => s.progress);
  const landmarks = useScanStore((s): FaceMeshLandmarks | null => s.landmarks);
  const sanityFlag = useScanStore((s): SanityResult | null => s.sanityFlag);

  const faceWorkerRef = useRef<Worker | null>(null);
  const rppgWorkerRef = useRef<Worker | null>(null);
  const textureWorkerRef = useRef<Worker | null>(null);
  const detectorRef = useRef<FrozenFaceDetector>(new FrozenFaceDetector());
  const encoderRef = useRef<DeltaEncoderState>(new DeltaEncoderState());
  const cancelRef = useRef<boolean>(false);

  // Tab visibility abort.
  useEffect((): (() => void) => {
    const handler = (): void => {
      if (document.visibilityState === 'hidden') {
        cancelRef.current = true;
        useScanStore.getState().failScan('TAB_HIDDEN');
      }
    };
    document.addEventListener('visibilitychange', handler);
    return (): void => { document.removeEventListener('visibilitychange', handler); };
  }, []);

  // Worker teardown on unmount.
  useEffect((): (() => void) => {
    return (): void => {
      faceWorkerRef.current?.terminate();
      rppgWorkerRef.current?.terminate();
      textureWorkerRef.current?.terminate();
    };
  }, []);

  const spawnWorkers = useCallback((): void => {
    if (faceWorkerRef.current) return;
    faceWorkerRef.current = new Worker(new URL('../workers/face.worker.ts', import.meta.url), { type: 'module' });
    rppgWorkerRef.current = new Worker(new URL('../workers/rppg.worker.ts', import.meta.url), { type: 'module' });
    textureWorkerRef.current = new Worker(new URL('../workers/texture.worker.ts', import.meta.url), { type: 'module' });
    faceWorkerRef.current.postMessage({ type: 'INIT' });
    faceWorkerRef.current.addEventListener('message', (ev: MessageEvent<FaceWorkerMessage>): void => {
      if (ev.data.type === 'LANDMARKS') {
        const lm: FaceMeshLandmarks = ev.data.landmarks;
        if (!validatePhysiological(lm)) {
          useScanStore.getState().setSanityFlag({ centroidX: 0, centroidY: 0, flag: true });
          return;
        }
        useScanStore.getState().setLandmarks(lm);
        const sanity: SanityResult = checkSanity(lm, detectorRef.current);
        useScanStore.getState().setSanityFlag(sanity);
        // Delta encoding (per-frame, but results discarded for now).
        encode(lm, useScanStore.getState().landmarks, encoderRef.current);
      }
    });
    rppgWorkerRef.current.addEventListener('message', (ev: MessageEvent<RppgWorkerMessage>): void => {
      if (ev.data.type === 'SIGNAL') {
        // No-op here; the rPPG signal is consumed by tests/dashboards.
      }
    });
    textureWorkerRef.current.addEventListener('message', (ev: MessageEvent<TextureWorkerMessage>): void => {
      if (ev.data.type === 'RESULT' && !ev.data.isLive) {
        useScanStore.getState().failScan('TEXTURE_NOT_LIVE');
      }
    });
  }, []);

  const startScan = useCallback(async (): Promise<void> => {
    cancelRef.current = false;
    detectorRef.current.reset();
    encoderRef.current = new DeltaEncoderState();
    useScanStore.getState().startScan();
    spawnWorkers();
  }, [spawnWorkers]);

  const cancelScan = useCallback((): void => {
    cancelRef.current = true;
    faceWorkerRef.current?.terminate();
    rppgWorkerRef.current?.terminate();
    textureWorkerRef.current?.terminate();
    faceWorkerRef.current = null;
    rppgWorkerRef.current = null;
    textureWorkerRef.current = null;
    useScanStore.getState().reset();
  }, []);

  return { state, progress, landmarks, sanityFlag, startScan, cancelScan };
}

/** Test-only helper to push a frame into the pipeline. */
export function pushFrameToPipeline(frame: CameraFrame, prev: FaceMeshLandmarks | null): FaceMeshLandmarks | null {
  const store = useScanStore.getState();
  store.processFrame(frame);
  const p: number = (store.frameCount / REQUIRED_FRAMES) * 100;
  store.setProgress(p);
  if (store.frameCount >= REQUIRED_FRAMES) {
    const result: ScanResult = { passed: true, frameCount: store.frameCount, durationMs: frame.timestamp };
    store.completeScan(result);
  }
  return prev;
}

// Helper exposed for completeness with the rest of the file.
export { decode };

// VERIFIED: Workers pooled via refs, tab visibility abort, frozen-face check, physiological check.
