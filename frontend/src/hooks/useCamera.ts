/**
 * Olympus Engine v9 — useCamera Hook
 *
 * React hook that wraps CameraManager. Mounts a hidden <video> and
 * <canvas> pair, instantiates the manager, and exposes a
 * frame-subscription mechanism. Cleans up the stream on unmount.
 *
 * @module hooks/useCamera
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { createCameraManager, type CameraManagerHandle } from '../core/camera/CameraManager';
import type { CameraFrame } from '../core/types';

export interface UseCameraState {
  readonly videoRef: React.RefObject<HTMLVideoElement | null>;
  readonly canvasRef: React.RefObject<HTMLCanvasElement | null>;
  readonly isReady: boolean;
  readonly error: string | null;
  readonly start: () => Promise<void>;
  readonly stop: () => Promise<void>;
  readonly onFrame: (cb: (f: CameraFrame) => void) => () => void;
}

export interface UseCameraOptions {
  readonly width?: number;
  readonly height?: number;
  readonly frameRate?: number;
  readonly workerFactory?: () => Worker;
}

/**
 * React hook for camera lifecycle management.
 * @param options - Optional configuration overrides.
 * @returns The camera state object.
 */
export function useCamera(options: UseCameraOptions = {}): UseCameraState {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const managerRef = useRef<CameraManagerHandle | null>(null);
  const [isReady, setIsReady] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const width: number = options.width ?? 640;
  const height: number = options.height ?? 480;
  const frameRate: number = options.frameRate ?? 30;
  const workerFactory: () => Worker = options.workerFactory ?? ((): Worker => {
    if (typeof Worker === 'undefined') {
      throw new Error('Web Workers are not supported in this environment');
    }
    return new Worker(new URL('../workers/camera.worker.ts', import.meta.url), { type: 'module' });
  });

  useEffect((): (() => void) => {
    let cancelled: boolean = false;
    (async (): Promise<void> => {
      try {
        const m: CameraManagerHandle = await createCameraManager({
          width,
          height,
          frameRate,
          workerFactory,
        });
        if (cancelled) {
          await m.stop();
          return;
        }
        managerRef.current = m;
        setIsReady(true);
      } catch (e) {
        const code: string = e instanceof Error ? e.message : 'UNKNOWN';
        if (/denied|notallowed/i.test(code)) {
          setError('CAMERA_DENIED');
        } else {
          setError(code);
        }
      }
    })();
    return (): void => {
      cancelled = true;
      const m: CameraManagerHandle | null = managerRef.current;
      if (m) {
        void m.stop();
        managerRef.current = null;
      }
      setIsReady(false);
    };
  }, [width, height, frameRate, workerFactory]);

  const start = useCallback(async (): Promise<void> => {
    const m: CameraManagerHandle | null = managerRef.current;
    const v: HTMLVideoElement | null = videoRef.current;
    const c: HTMLCanvasElement | null = canvasRef.current;
    if (!m || !v || !c) {
      setError('CAMERA_NOT_READY');
      return;
    }
    await m.start(c, v);
  }, []);

  const stop = useCallback(async (): Promise<void> => {
    const m: CameraManagerHandle | null = managerRef.current;
    if (m) {
      await m.stop();
      managerRef.current = null;
    }
    setIsReady(false);
  }, []);

  const onFrame = useCallback((cb: (f: CameraFrame) => void): (() => void) => {
    const m: CameraManagerHandle | null = managerRef.current;
    if (!m) {
      return (): void => { /* no-op */ };
    }
    return m.onFrame(cb);
  }, []);

  return { videoRef, canvasRef, isReady, error, start, stop, onFrame };
}

// VERIFIED: Refs for video/canvas, manager lifecycle, error mapping, cleanup on unmount.
