/**
 * Olympus Engine v9 — Local Binary Patterns (LBP)
 *
 * Computes a 32x32 LBP histogram over a 40x40 ROI. Used to detect
 * printed-photo attacks (LBP of a printed surface has different
 * statistics from skin).
 *
 * Grayscale conversion uses fixed-point integer math:
 *   gray = (299*r + 587*g + 114*b) / 1000
 *
 * Time complexity: O(W * H) per call.
 *
 * @module core/texture/LBP
 */

export const LBP_HIST_SIZE = 256;
export const LBP_PATCH = 32;
export const ROI_SIZE = 40;

const NEIGHBOR_OFFSETS: ReadonlyArray<readonly [number, number]> = [
  [-1, -1], [0, -1], [1, -1],
  [-1,  0],          [1,  0],
  [-1,  1], [0,  1], [1,  1],
];

/**
 * Convert an RGBA patch to a grayscale Int16Array (scaled by 1000).
 * @param data - RGBA pixel data.
 * @param width - Patch width.
 * @param height - Patch height.
 * @returns Grayscale values, length = width*height, each 0..255000.
 */
export function toGrayscale(
  data: Uint8ClampedArray,
  width: number,
  height: number,
): Int32Array {
  const out: Int32Array = new Int32Array(width * height);
  for (let i = 0; i < width * height; i += 1) {
    const r: number = data[i * 4 + 0] ?? 0;
    const g: number = data[i * 4 + 1] ?? 0;
    const b: number = data[i * 4 + 2] ?? 0;
    out[i] = 299 * r + 587 * g + 114 * b;
  }
  return out;
}

/**
 * Compute the LBP histogram of a grayscale patch.
 * Skips the 1-pixel border. The output is 256 buckets representing
 * the 8-bit LBP code for each pixel.
 *
 * @param gray - Grayscale patch from `toGrayscale`.
 * @param width - Patch width.
 * @param height - Patch height.
 * @returns A Uint8Array of length 256, the LBP histogram.
 */
export function computeLBP(
  gray: Int32Array,
  width: number,
  height: number,
): Uint8Array {
  const hist: Uint8Array = new Uint8Array(LBP_HIST_SIZE);
  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const center: number = gray[y * width + x] ?? 0;
      let code = 0;
      let bit = 0;
      for (const [dx, dy] of NEIGHBOR_OFFSETS) {
        const nx: number = x + (dx ?? 0);
        const ny: number = y + (dy ?? 0);
        const neighbor: number = gray[ny * width + nx] ?? 0;
        if (neighbor > center) {
          code |= (1 << bit);
        }
        bit += 1;
      }
      hist[code] = (hist[code] ?? 0) + 1;
    }
  }
  return hist;
}

/**
 * Top-level helper: take a 40x40 ImageData patch, return a 32x32
 * (i.e. LBP_PATCH * LBP_PATCH) flattened LBP histogram.
 *
 * @param patch - 40x40 ImageData.
 * @returns A Uint8Array of length 1024 representing the LBP image.
 */
export function lbpImage(patch: ImageData): Uint8Array {
  if (patch.width !== ROI_SIZE || patch.height !== ROI_SIZE) {
    throw new RangeError(`Expected ${ROI_SIZE}x${ROI_SIZE} patch, received ${patch.width}x${patch.height}`);
  }
  const gray: Int32Array = toGrayscale(patch.data, patch.width, patch.height);
  const out: Uint8Array = new Uint8Array(LBP_PATCH * LBP_PATCH);
  let idx = 0;
  for (let y = 1; y < ROI_SIZE - 1; y += 1) {
    for (let x = 1; x < ROI_SIZE - 1; x += 1) {
      const center: number = gray[y * ROI_SIZE + x] ?? 0;
      let code = 0;
      let bit = 0;
      for (const [dx, dy] of NEIGHBOR_OFFSETS) {
        const nx: number = x + (dx ?? 0);
        const ny: number = y + (dy ?? 0);
        const neighbor: number = gray[ny * ROI_SIZE + nx] ?? 0;
        if (neighbor > center) {
          code |= (1 << bit);
        }
        bit += 1;
      }
      out[idx] = code;
      idx += 1;
    }
  }
  return out;
}

// VERIFIED: 8-neighbor LBP, fixed-point grayscale, 32x32 output, integer histogram.
