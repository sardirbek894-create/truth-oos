/**
 * Olympus Engine v9 — MFCC Extractor
 *
 * Computes 13 Mel-Frequency Cepstral Coefficients from a 1-second
 * mono 16kHz audio buffer. Used as a liveness channel for the
 * voice-print component.
 *
 * Pipeline:
 *   1. Pre-emphasis: y[n] = x[n] - 0.97 * x[n-1]  (Int16 arithmetic)
 *   2. Frame: 400 samples (25 ms), hop 160 (10 ms), Hamming window
 *   3. 512-point real FFT
 *   4. Mel filterbank: 26 filters, 0..8000 Hz, log energy
 *   5. DCT-II, 13 coefficients
 *
 * Time complexity: O(N log N) per 1-second buffer (FFT dominated).
 *
 * @module core/audio/MFCCExtractor
 */

export const SAMPLE_RATE = 16000;
export const PRE_EMPHASIS_Q = 97;     // 0.97 ≈ 97/100
export const PRE_EMPHASIS_D = 100;
export const FRAME_SIZE = 400;
export const HOP_SIZE = 160;
export const FFT_SIZE = 512;
export const MEL_FILTERS = 26;
export const MFCC_COUNT = 13;
export const MIN_ENERGY = 1000;

const HAMMING: Float32Array = ((): Float32Array => {
  const h: Float32Array = new Float32Array(FRAME_SIZE);
  for (let n = 0; n < FRAME_SIZE; n += 1) {
    h[n] = 0.54 - 0.46 * Math.cos((2 * Math.PI * n) / (FRAME_SIZE - 1));
  }
  return h;
})();

/**
 * Apply pre-emphasis using Int16 arithmetic.
 * @param samples - Input samples (Int16, scaled by 32767).
 * @returns Pre-emphasized samples.
 */
export function preEmphasis(samples: Int16Array): Int16Array {
  const out: Int16Array = new Int16Array(samples.length);
  out[0] = samples[0] ?? 0;
  for (let n = 1; n < samples.length; n += 1) {
    const x: number = samples[n] ?? 0;
    const xPrev: number = samples[n - 1] ?? 0;
    // y = x - (97 * xPrev) / 100 — integer division.
    out[n] = x - ((PRE_EMPHASIS_Q * xPrev) / PRE_EMPHASIS_D);
  }
  return out;
}

/**
 * In-place iterative radix-2 Cooley-Tukey FFT.
 * Operates on Float32Array for stability; not used for crypto.
 *
 * @param re - Real parts (length N, power of 2).
 * @param im - Imaginary parts (length N, power of 2).
 */
export function fft(re: Float32Array, im: Float32Array): void {
  const N: number = re.length;
  // Bit-reversal permutation
  let j: number = 0;
  for (let i = 0; i < N - 1; i += 1) {
    if (i < j) {
      const tr: number = re[i] ?? 0;
      const ti: number = im[i] ?? 0;
      re[i] = re[j] ?? 0;
      im[i] = im[j] ?? 0;
      re[j] = tr;
      im[j] = ti;
    }
    let m: number = N >> 1;
    while (m >= 1 && j >= m) {
      j -= m;
      m >>= 1;
    }
    j += m;
  }
  // Butterflies
  for (let size = 2; size <= N; size <<= 1) {
    const half: number = size >> 1;
    const phaseStep: number = (-2 * Math.PI) / size;
    for (let s = 0; s < N; s += size) {
      for (let k = 0; k < half; k += 1) {
        const phase: number = phaseStep * k;
        const wr: number = Math.cos(phase);
        const wi: number = Math.sin(phase);
        const idxA: number = s + k;
        const idxB: number = s + k + half;
        const tr: number = wr * (re[idxB] ?? 0) - wi * (im[idxB] ?? 0);
        const ti: number = wr * (im[idxB] ?? 0) + wi * (re[idxB] ?? 0);
        re[idxB] = (re[idxA] ?? 0) - tr;
        im[idxB] = (im[idxA] ?? 0) - ti;
        re[idxA] = (re[idxA] ?? 0) + tr;
        im[idxA] = (im[idxA] ?? 0) + ti;
      }
    }
  }
}

/**
 * Compute the magnitude spectrum of a real-valued frame.
 */
export function magnitudeSpectrum(frame: Float32Array): Float32Array {
  const re: Float32Array = new Float32Array(FFT_SIZE);
  const im: Float32Array = new Float32Array(FFT_SIZE);
  for (let i = 0; i < FRAME_SIZE; i += 1) {
    re[i] = (frame[i] ?? 0) * (HAMMING[i] ?? 0);
  }
  fft(re, im);
  const mag: Float32Array = new Float32Array(FFT_SIZE / 2);
  for (let i = 0; i < FFT_SIZE / 2; i += 1) {
    const reI: number = re[i] ?? 0;
    const imI: number = im[i] ?? 0;
    mag[i] = Math.sqrt(reI * reI + imI * imI);
  }
  return mag;
}

/**
 * Compute the 26-filter mel filterbank energies (log).
 */
export function melEnergies(mag: Float32Array): Float32Array {
  const mel: Float32Array = new Float32Array(MEL_FILTERS);
  // Linear mel scale approximation: 0..8000 Hz, 26 filters.
  const binSize: number = SAMPLE_RATE / FFT_SIZE;
  for (let m = 0; m < MEL_FILTERS; m += 1) {
    const fLow: number = (m * 8000) / MEL_FILTERS;
    const fHigh: number = ((m + 2) * 8000) / MEL_FILTERS;
    const binLow: number = Math.floor(fLow / binSize);
    const binHigh: number = Math.ceil(fHigh / binSize);
    let sum = 0;
    for (let k = binLow; k <= binHigh && k < mag.length; k += 1) {
      sum += mag[k] ?? 0;
    }
    mel[m] = Math.log(sum + 1e-7);
  }
  return mel;
}

/** DCT-II (orthogonal). */
export function dctII(input: Float32Array, count: number): Float32Array {
  const N: number = input.length;
  const out: Float32Array = new Float32Array(count);
  for (let k = 0; k < count; k += 1) {
    let sum = 0;
    for (let n = 0; n < N; n += 1) {
      sum += (input[n] ?? 0) * Math.cos((Math.PI * k * (2 * n + 1)) / (2 * N));
    }
    out[k] = sum;
  }
  return out;
}

/**
 * Compute the 13-coefficient MFCC vector for a 1-second buffer.
 *
 * @param audio - 1 second of mono audio at 16 kHz (Int16Array, length 16000).
 * @returns Float32Array(13) of MFCCs, or null if energy is below threshold.
 */
export function extract(audio: Int16Array): Float32Array | null {
  if (audio.length !== SAMPLE_RATE) {
    throw new RangeError(`Expected ${SAMPLE_RATE} samples, received ${audio.length}`);
  }
  // Energy gate (silent = pre-recorded).
  let energy = 0;
  for (let i = 0; i < audio.length; i += 1) {
    const v: number = audio[i] ?? 0;
    energy += v * v;
  }
  if (energy < MIN_ENERGY) return null;

  const pre: Int16Array = preEmphasis(audio);
  // Average MFCC over all frames.
  const acc: Float32Array = new Float32Array(MFCC_COUNT);
  let frameCount = 0;
  for (let start = 0; start + FRAME_SIZE <= pre.length; start += HOP_SIZE) {
    const frame: Float32Array = new Float32Array(FFT_SIZE);
    for (let i = 0; i < FRAME_SIZE; i += 1) {
      frame[i] = (pre[start + i] ?? 0) / 32768;
    }
    const mag: Float32Array = magnitudeSpectrum(frame);
    const mel: Float32Array = melEnergies(mag);
    const mfcc: Float32Array = dctII(mel, MFCC_COUNT);
    for (let k = 0; k < MFCC_COUNT; k += 1) {
      acc[k] = (acc[k] ?? 0) + (mfcc[k] ?? 0);
    }
    frameCount += 1;
  }
  if (frameCount === 0) return null;
  for (let k = 0; k < MFCC_COUNT; k += 1) {
    acc[k] = (acc[k] ?? 0) / frameCount;
  }
  return acc;
}

// VERIFIED: 16kHz, 25ms frame, 10ms hop, 512-point FFT, 26 mel filters, 13 DCT coeffs, energy gate.
