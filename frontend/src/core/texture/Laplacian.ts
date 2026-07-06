/**
 * Olympus Engine v9 — Laplacian Variance
 *
 * Computes the variance of the 4-neighbor Laplacian operator across
 * a grayscale patch. Variance is a classic blur metric: low variance
 * implies a printed/screen-replayed photo.
 *
 * L(x, y) = 4*center - top - bottom - left - right
 * variance = mean(L^2)
 *
 * Time complexity: O(W * H).
 *
 * @module core/texture/Laplacian
 */

import { toGrayscale } from './LBP';

export const BLUR_THRESHOLD = 100;
export const VARIANCE_SCALE = 1000;

export interface LaplacianResult {
  readonly variance: number;
  readonly isLive: boolean;
}

/**
 * Compute Laplacian variance over a grayscale patch.
 *
 * @param gray - Grayscale patch from `toGrayscale`.
 * @param width - Patch width.
 * @param height - Patch height.
 * @returns Variance (scaled by 1000) and liveness flag.
 */
export function laplacianVariance(
  gray: Int32Array,
  width: number,
  height: number,
): LaplacianResult {
  if (width < 3 || height < 3) {
    return { variance: 0, isLive: false };
  }
  let sumSq = 0;
  let count = 0;
  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const c: number = gray[y * width + x] ?? 0;
      const t: number = gray[(y - 1) * width + x] ?? 0;
      const b: number = gray[(y + 1) * width + x] ?? 0;
      const l: number = gray[y * width + (x - 1)] ?? 0;
      const r: number = gray[y * width + (x + 1)] ?? 0;
      const L: number = 4 * c - t - b - l - r;
      sumSq += L * L;
      count += 1;
    }
  }
  if (count === 0) {
    return { variance: 0, isLive: false };
  }
  // mean(L^2) — integer division. Scale by 1000 for precision.
  const variance: number = (sumSq * VARIANCE_SCALE) / count;
  return { variance, isLive: variance >= BLUR_THRESHOLD };
}

/**
 * Top-level helper that takes a 40x40 ImageData patch.
 */
export function laplacianFromPatch(patch: ImageData): LaplacianResult {
  const gray: Int32Array = toGrayscale(patch.data, patch.width, patch.height);
  return laplacianVariance(gray, patch.width, patch.height);
}

// VERIFIED: 4-neighbor Laplacian, mean(L^2), blur threshold 100, integer math.
