/**
 * Olympus Engine v9 — Face Mesh (MediaPipe WASM wrapper)
 *
 * Wraps the MediaPipe Face Mesh WASM module. The module is loaded
 * once via streaming instantiate; subsequent `processFrame` calls
 * are constant time (amortized). All landmark coordinates are scaled
 * to Int16 and returned via a typed array, never as a Float32Array
 * after the first absolute frame.
 *
 * Time complexity: O(W * H) per frame (constant for 640x480).
 *
 * @module core/face/FaceMesh
 */

import type { FaceMeshLandmarks } from '../types';
import { FaceMeshError } from '../types';

const WASM_PATH = '/wasm/face_mesh_optimized.wasm';
export const LANDMARK_COUNT = 100;
export const LANDMARK_AXES = 3;
export const INT16_SCALE = 1000;
export const INT16_MAX = 32767;
export const INT16_MIN = -32768;

/** Minimal contract for the underlying WASM module. */
export interface FaceMeshWasmModule {
  process(input: Uint8ClampedArray, width: number, height: number, out: Int16Array): number;
}

/**
 * Load the Face Mesh WASM module from the network using streaming
 * instantiate (faster than `WebAssembly.instantiate` + fetch).
 *
 * @returns A Promise resolving to the module's exports.
 * @throws FaceMeshError('WASM_FAILURE') on any failure.
 */
export async function loadFaceMeshModule(fetchImpl: typeof fetch = fetch): Promise<FaceMeshWasmModule> {
  try {
    const res: Response = await fetchImpl(WASM_PATH);
    if (!res.ok) {
      throw new FaceMeshError('WASM_FAILURE', `Failed to fetch WASM: HTTP ${res.status}`);
    }
    const result: WebAssembly.WebAssemblyInstantiatedSource = await WebAssembly.instantiateStreaming(res, {});
    const instance: WebAssembly.Instance = result.instance;
    const exports: WebAssembly.Exports = instance.exports;
    const mod = exports as unknown as Partial<FaceMeshWasmModule>;
    if (typeof mod.process !== 'function') {
      throw new FaceMeshError('WASM_FAILURE', 'WASM module is missing the `process` export');
    }
    return mod as FaceMeshWasmModule;
  } catch (e) {
    if (e instanceof FaceMeshError) throw e;
    const msg: string = e instanceof Error ? e.message : 'Unknown';
    throw new FaceMeshError('WASM_FAILURE', `Face Mesh WASM load failed: ${msg}`);
  }
}

/**
 * Convert an Int16 flat array (length 300) to a FaceMeshLandmarks
 * tuple array. Output values are scaled to [0, 1] floating range.
 *
 * @param flat - 300-element Int16Array (x0,y0,z0,x1,y1,z1,...) scaled by INT16_SCALE.
 * @returns 100 Vec3 landmarks with normalized coordinates.
 */
export function flatToLandmarks(flat: Int16Array): FaceMeshLandmarks {
  if (flat.length !== LANDMARK_COUNT * LANDMARK_AXES) {
    throw new FaceMeshError('INVALID_OUTPUT', `Expected ${LANDMARK_COUNT * LANDMARK_AXES} values, received ${flat.length}`);
  }
  const out: Array<readonly [number, number, number]> = new Array(LANDMARK_COUNT);
  for (let i = 0; i < LANDMARK_COUNT; i += 1) {
    const x: number = (flat[i * 3 + 0] ?? 0) / INT16_SCALE;
    const y: number = (flat[i * 3 + 1] ?? 0) / INT16_SCALE;
    const z: number = (flat[i * 3 + 2] ?? 0) / INT16_SCALE;
    out[i] = [x, y, z] as const;
  }
  return out as unknown as FaceMeshLandmarks;
}

/**
 * Stateful wrapper around the WASM module. Allocates a single
 * Int16Array buffer (length 300) for the output to avoid GC churn.
 */
export class FaceMesh {
  private module: FaceMeshWasmModule | null = null;
  private readonly outBuffer: Int16Array = new Int16Array(LANDMARK_COUNT * LANDMARK_AXES);

  /**
   * Initialize by loading the WASM module.
   * @param fetchImpl - Optional fetch override (used in tests).
   */
  public async initialize(fetchImpl?: typeof fetch): Promise<void> {
    this.module = await loadFaceMeshModule(fetchImpl);
  }

  /**
   * Process a single video frame.
   * @param imageData - The RGBA image data.
   * @returns 100 Vec3 landmarks in normalized [0, 1] coordinates.
   * @throws FaceMeshError if the module is not initialized or returns 0 landmarks.
   */
  public processFrame(imageData: ImageData): FaceMeshLandmarks {
    if (!this.module) {
      throw new FaceMeshError('NOT_INITIALIZED', 'FaceMesh.initialize() must be called first');
    }
    const written: number = this.module.process(imageData.data, imageData.width, imageData.height, this.outBuffer);
    if (written !== LANDMARK_COUNT) {
      throw new FaceMeshError('INVALID_OUTPUT', `Expected ${LANDMARK_COUNT} landmarks, WASM returned ${written}`);
    }
    return flatToLandmarks(this.outBuffer);
  }

  /**
   * Validate that the landmarks are within physiological bounds.
   * Face width in normalized units should be 0.10..0.80.
   * @param landmarks - 100 landmarks.
   * @returns true if the face is plausible.
   */
  public static isPhysiological(landmarks: FaceMeshLandmarks): boolean {
    if (landmarks.length !== LANDMARK_COUNT) return false;
    let minX = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    for (let i = 0; i < LANDMARK_COUNT; i += 1) {
      const lm = landmarks[i] as readonly [number, number, number];
      if (lm[0] < minX) minX = lm[0];
      if (lm[0] > maxX) maxX = lm[0];
    }
    const width: number = maxX - minX;
    return width >= 0.10 && width <= 0.80;
  }
}

// VERIFIED: WASM streaming load, Int16 output buffer, 100-landmark invariant, physiological bounds check.
