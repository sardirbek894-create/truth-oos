/**
 * Olympus Engine v9 — Scan State Store (Zustand)
 *
 * State machine for the scan lifecycle. No boolean flags; the single
 * `state` field encodes the current phase. Persistence is intentionally
 * disabled — all scan data is ephemeral and must not survive reload.
 *
 * @module store/useScanStore
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import type {
  CameraFrame,
  FaceMeshLandmarks,
  SanityResult,
  ScanResult,
  ScanState,
} from '../core/types';

export interface ScanStore {
  readonly state: ScanState;
  readonly progress: number;
  readonly frameCount: number;
  readonly landmarks: FaceMeshLandmarks | null;
  readonly sanityFlag: SanityResult | null;
  readonly lastFrame: CameraFrame | null;
  readonly errorMessage: string | null;

  startScan(): void;
  processFrame(frame: CameraFrame): void;
  setLandmarks(landmarks: FaceMeshLandmarks): void;
  setSanityFlag(result: SanityResult): void;
  setProgress(progress: number): void;
  completeScan(result: ScanResult): void;
  failScan(reason: string): void;
  setError(message: string): void;
  reset(): void;
}

const initial = {
  state: 'idle' as ScanState,
  progress: 0,
  frameCount: 0,
  landmarks: null,
  sanityFlag: null,
  lastFrame: null,
  errorMessage: null,
};

const useScanStoreBase = create<ScanStore>()(
  devtools(
    (set): ScanStore => ({
      ...initial,
      startScan(): void {
        set({
          state: 'requesting_camera',
          progress: 0,
          frameCount: 0,
          landmarks: null,
          sanityFlag: null,
          lastFrame: null,
          errorMessage: null,
        });
      },
      processFrame(frame: CameraFrame): void {
        set((prev): Partial<ScanStore> => ({
          lastFrame: frame,
          frameCount: prev.frameCount + 1,
          state: 'scanning' as ScanState,
        }));
      },
      setLandmarks(landmarks: FaceMeshLandmarks): void {
        set({ landmarks });
      },
      setSanityFlag(result: SanityResult): void {
        if (result.flag) {
          set({ sanityFlag: result, state: 'failed' });
          return;
        }
        set({ sanityFlag: result });
      },
      setProgress(progress: number): void {
        const clamped: number = Math.max(0, Math.min(100, progress));
        set({ progress: clamped });
      },
      completeScan(result: ScanResult): void {
        set({ state: result.passed ? 'passed' : 'failed' });
      },
      failScan(reason: string): void {
        set({ state: 'failed', errorMessage: reason });
      },
      setError(message: string): void {
        set({ state: 'error', errorMessage: message });
      },
      reset(): void {
        set({ ...initial });
      },
    }),
    { enabled: import.meta.env.DEV === true, name: 'olympus-scan' },
  ),
);

export const useScanStore: typeof useScanStoreBase = useScanStoreBase;

// VERIFIED: State machine, no booleans, devtools in dev only, ephemeral state.
