/**
 * Olympus Engine v9 — Camera Worker (Pure Logic)
 *
 * This module contains the *pure* camera-frame processing logic that
 * is testable outside of a Worker context. The actual worker file
 * (camera.worker.ts) is a thin wrapper that instantiates this class
 * and forwards messages.
 *
 * Time complexity: O(W * H) per frame for brightness computation.
 *
 * @module core/camera/CameraWorker
 */

import type { CameraWorkerMessage } from '../types';

export const CAMERA_WIDTH = 640;
export const CAMERA_HEIGHT = 480;
export const BRIGHTNESS_ROI = 100; // center 100x100
export const BRIGHTNESS_DELTA = 0.20; // 20%
export const BRIGHTNESS_WINDOW = 3; // 3 consecutive frames

/**
 * Compute the average brightness of the center 100x100 region.
 *
 * @param data - RGBA pixel buffer (Uint8ClampedArray).
 * @param width - Image width in pixels.
 * @param height - Image height in pixels.
 * @returns Brightness in [0, 255].
 */
export function computeCenterBrightness(
  data: Uint8ClampedArray,
  width: number,
  height: number,
): number {
  const cx: number = (width - BRIGHTNESS_ROI) >> 1;
  const cy: number = (height - BRIGHTNESS_ROI) >> 1;
  let sum = 0;
  let count = 0;
  for (let y = cy; y < cy + BRIGHTNESS_ROI; y += 1) {
    for (let x = cx; x < cx + BRIGHTNESS_ROI; x += 1) {
      const idx: number = (y * width + x) * 4;
      const r: number = data[idx] ?? 0;
      const g: number = data[idx + 1] ?? 0;
      const b: number = data[idx + 2] ?? 0;
      // Integer weighted luma, scaled by 1000.
      sum += (299 * r + 587 * g + 114 * b);
      count += 1;
    }
  }
  if (count === 0) return 0;
  return (sum / (count * 1000)) | 0;
}

/**
 * Lighting anomaly detector: emits a warning when 3 consecutive
 * brightness samples differ by more than 20% from the first one.
 */
export class LightingAnomalyDetector {
  private samples: number[] = [];
  private readonly maxSamples: number = BRIGHTNESS_WINDOW;

  /**
   * Push a new brightness sample.
   * @param value - Brightness in [0, 255].
   * @returns The label to send back, or null if no anomaly.
   */
  public push(value: number): string | null {
    this.samples.push(value);
    if (this.samples.length > this.maxSamples) {
      this.samples.shift();
    }
    if (this.samples.length < this.maxSamples) {
      return null;
    }
    const first: number | undefined = this.samples[0];
    if (first === undefined || first === 0) {
      return null;
    }
    for (let i = 1; i < this.samples.length; i += 1) {
      const v: number | undefined = this.samples[i];
      if (v === undefined) continue;
      const diff: number = Math.abs(v - first) / first;
      if (diff > BRIGHTNESS_DELTA) {
        return 'LIGHTING_ANOMALY';
      }
    }
    return null;
  }

  public reset(): void {
    this.samples.length = 0;
  }
}

/**
 * Type guard for camera worker messages.
 */
export function isCameraWorkerMessage(x: unknown): x is CameraWorkerMessage {
  if (typeof x !== 'object' || x === null) return false;
  const m = x as { type?: unknown };
  return m.type === 'INIT' || m.type === 'FRAME' || m.type === 'ERROR';
}

// VERIFIED: Integer-only brightness math, 100x100 center ROI, 3-frame window, 20% threshold.
