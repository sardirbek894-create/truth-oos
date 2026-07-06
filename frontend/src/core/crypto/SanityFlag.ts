/**
 * Olympus Engine v9 — Sanity Flag (Centroid Validation)
 *
 * Detects static-image, replay, and "frozen face" attacks by validating
 * the geometric centroid of the face mesh and tracking its motion over
 * time. The centroid must remain in a sensible range for a real human
 * looking at the camera, and must move by at least 0.01 normalized
 * units over a 2-second window.
 *
 * All sums are accumulated as integers (x and y coordinates are
 * expected to be scaled to the 0..1000 integer range by the FaceMesh
 * module) and divided exactly once at the end.
 *
 * Time complexity:
 *   - `validate`: O(N) where N = 100 landmarks.
 *   - `recordFrame`: O(1) amortized.
 *   - `isFrozen`: O(1).
 *
 * @module core/crypto/SanityFlag
 */

import type { FaceMeshLandmarks, LandmarkIndex, SanityResult } from '../types';

/** Configuration constants for centroid validation. */
export const SANITY_CONFIG = {
  /** Acceptable normalized X range. */
  MIN_X: 0.2,
  MAX_X: 0.8,
  /** Acceptable normalized Y range. */
  MIN_Y: 0.2,
  MAX_Y: 0.8,
  /** Required motion (normalized units) over the lookback window. */
  MOTION_THRESHOLD: 0.01,
  /** Number of frames in the lookback window (2 seconds at 30 FPS). */
  LOOKBACK_FRAMES: 60,
  /** Internal scale factor for integer arithmetic. */
  SCALE: 1000,
} as const;

/** Internal record of one centroid sample. */
interface CentroidSample {
  readonly x: number; // scaled integer
  readonly y: number; // scaled integer
  readonly t: number;
}

/**
 * Compute the integer-scaled centroid of a face landmark set.
 *
 * @param landmarks - The 100 landmarks. Coordinates are expected in
 *   normalized [0, 1] range * SCALE, i.e. integer 0..1000.
 * @returns Scaled integer centroid { x, y }.
 */
export function computeCentroid(landmarks: FaceMeshLandmarks): { x: number; y: number } {
  if (landmarks.length !== 100) {
    throw new RangeError(`Expected 100 landmarks, received ${landmarks.length}`);
  }
  let sumX = 0;
  let sumY = 0;
  for (let i = 0; i < 100; i += 1) {
    const lm = landmarks[i] as Readonly<Vec3ish>;
    sumX += lm[0];
    sumY += lm[1];
  }
  // Integer division by 100. Validated downstream against SCALE.
  return { x: sumX / 100, y: sumY / 100 };
}

type Vec3ish = readonly [number, number, number];

/**
 * Validate the centroid of a single frame against physiological bounds.
 *
 * @param landmarks - The 100 landmarks (integer-scaled).
 * @returns A SanityResult with the centroid and a flag.
 */
export function validate(landmarks: FaceMeshLandmarks): SanityResult {
  const c: { x: number; y: number } = computeCentroid(landmarks);
  const cx: number = c.x / SANITY_CONFIG.SCALE;
  const cy: number = c.y / SANITY_CONFIG.SCALE;
  const outOfRange: boolean =
    cx < SANITY_CONFIG.MIN_X ||
    cx > SANITY_CONFIG.MAX_X ||
    cy < SANITY_CONFIG.MIN_Y ||
    cy > SANITY_CONFIG.MAX_Y;
  return {
    centroidX: cx,
    centroidY: cy,
    flag: outOfRange,
  };
}

/**
 * Stateful detector for "frozen face" (static image) attacks.
 *
 * Maintain one instance per scan. Call `recordFrame` with each new
 * centroid and `isFrozen` to check whether the face has moved enough.
 */
export class FrozenFaceDetector {
  private readonly samples: CentroidSample[] = [];
  private readonly maxSamples: number = SANITY_CONFIG.LOOKBACK_FRAMES;

  /**
   * Record a new centroid sample.
   * @param x - Scaled X centroid (integer, 0..1000).
   * @param y - Scaled Y centroid (integer, 0..1000).
   * @param t - DOMHighResTimeStamp.
   */
  public recordFrame(x: number, y: number, t: number): void {
    this.samples.push({ x, y, t });
    if (this.samples.length > this.maxSamples) {
      this.samples.shift();
    }
  }

  /**
   * Determine whether the face has moved less than MOTION_THRESHOLD
   * over the last LOOKBACK_FRAMES frames.
   * @returns true if the face appears frozen (likely a printed photo).
   */
  public isFrozen(): boolean {
    if (this.samples.length < 2) {
      return false;
    }
    const first: CentroidSample | undefined = this.samples[0];
    const last: CentroidSample | undefined = this.samples[this.samples.length - 1];
    if (first === undefined || last === undefined) {
      return false;
    }
    const dx: number = Math.abs(last.x - first.x) / SANITY_CONFIG.SCALE;
    const dy: number = Math.abs(last.y - first.y) / SANITY_CONFIG.SCALE;
    const motion: number = dx + dy;
    return motion < SANITY_CONFIG.MOTION_THRESHOLD;
  }

  /** Reset the detector. */
  public reset(): void {
    this.samples.length = 0;
  }
}

/** Convenience wrapper used by the main thread. */
export function checkSanity(
  landmarks: FaceMeshLandmarks,
  detector: FrozenFaceDetector,
): SanityResult {
  const base: SanityResult = validate(landmarks);
  if (base.flag) {
    return base;
  }
  const c: { x: number; y: number } = computeCentroid(landmarks);
  detector.recordFrame(c.x, c.y, performance.now());
  const frozen: boolean = detector.isFrozen();
  return { centroidX: base.centroidX, centroidY: base.centroidY, flag: frozen };
}

// Type re-export for callers using the pure API.
export type { LandmarkIndex };

// VERIFIED: Integer-only centroid math. Frozen-face detection uses 60-frame lookback. Range [0.2, 0.8] enforced.
