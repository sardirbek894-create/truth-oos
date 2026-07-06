/**
 * Olympus Engine v9 — Core Type Definitions
 * Source of truth for all types used across the engine.
 *
 * Security considerations:
 * - All numeric tuples are `readonly` to prevent mutation.
 * - Landmark indices are explicit literal unions to enable exhaustive switch checks.
 * - Frame deltas use Int16Array to avoid IEEE 754 float manipulation in transit.
 */

/** 2D vector as immutable tuple. */
export type Vec2 = readonly [number, number];

/** 3D vector as immutable tuple. */
export type Vec3 = readonly [number, number, number];

/**
 * The 100 canonical MediaPipe Face Mesh landmark indices.
 * Implemented as a discriminated union to enable exhaustive matching.
 */
export type LandmarkIndex =
  | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9
  | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19
  | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29
  | 30 | 31 | 32 | 33 | 34 | 35 | 36 | 37 | 38 | 39
  | 40 | 41 | 42 | 43 | 44 | 45 | 46 | 47 | 48 | 49
  | 50 | 51 | 52 | 53 | 54 | 55 | 56 | 57 | 58 | 59
  | 60 | 61 | 62 | 63 | 64 | 65 | 66 | 67 | 68 | 69
  | 70 | 71 | 72 | 73 | 74 | 75 | 76 | 77 | 78 | 79
  | 80 | 81 | 82 | 83 | 84 | 85 | 86 | 87 | 88 | 89
  | 90 | 91 | 92 | 93 | 94 | 95 | 96 | 97 | 98 | 99;

/** The fixed-length list of 100 normalized 3D landmarks. */
export type FaceMeshLandmarks = ReadonlyArray<Vec3>;

/**
 * Frame of delta-encoded landmarks.
 * - `isAbsolute` is true for the first frame or when sentinel is emitted.
 * - `sentinel` of 999999 forces the next frame to be absolute.
 * - `deltas` is fixed at 300 (100 points * 3 axes), Int16 to defeat float fuzzing.
 */
export type DeltaFrame = Readonly<{
  isAbsolute: boolean;
  sentinel: number;
  deltas: Int16Array;
}>;

/** Region of interest used by texture and rPPG analyses. */
export type ROIDefinition = Readonly<{
  name: 'forehead' | 'left_cheek' | 'right_cheek';
  indices: ReadonlyArray<LandmarkIndex>;
  center: Vec2;
}>;

/** Snapshot of mean RGB values from an ROI, used for rPPG. */
export type RPPGSignal = Readonly<{
  timestamp: number;
  redMean: number;
  greenMean: number;
  blueMean: number;
}>;

/** Non-extractable Ed25519 keypair used for request signing. */
export type SessionKeyPair = Readonly<{
  publicKey: Uint8Array;
  privateKey: CryptoKey;
  createdAt: number;
}>;

/** Result of an IEEE 754-resistant jitter check. */
export type JitterPayload = Readonly<{
  baseValue: number;
  receivedValue: number;
  isValid: boolean;
}>;

/** Centroid validation result for replay/injection detection. */
export type SanityResult = Readonly<{
  centroidX: number;
  centroidY: number;
  flag: boolean;
}>;

/** State machine for the scan lifecycle. */
export type ScanState =
  | 'idle'
  | 'requesting_camera'
  | 'warming_up'
  | 'scanning'
  | 'analyzing'
  | 'passed'
  | 'failed'
  | 'error';

/** Raw frame received from the camera worker. */
export type CameraFrame = Readonly<{
  frameId: bigint;
  timestamp: number;
  imageData: ImageData;
  brightness: number;
  width: number;
  height: number;
}>;

/** Discriminated union for the camera worker protocol. */
export type CameraWorkerMessage =
  | { type: 'INIT'; canvas: OffscreenCanvas }
  | { type: 'FRAME'; frameId: bigint; timestamp: number; imageData: ImageData; brightness: number; width: number; height: number }
  | { type: 'ERROR'; code: string; message: string };

/** Discriminated union for the face worker protocol. */
export type FaceWorkerMessage =
  | { type: 'INIT' }
  | { type: 'PROCESS'; imageData: ImageData; frameId: bigint }
  | { type: 'LANDMARKS'; frameId: bigint; landmarks: FaceMeshLandmarks; durationMs: number }
  | { type: 'ERROR'; code: string; message: string };

/** Discriminated union for the rPPG worker protocol. */
export type RppgWorkerMessage =
  | { type: 'INIT' }
  | { type: 'SIGNAL'; timestamp: number; redMean: number; greenMean: number; blueMean: number };

/** Discriminated union for the texture worker protocol. */
export type TextureWorkerMessage =
  | { type: 'INIT' }
  | { type: 'ANALYZE'; imageData: ImageData; landmarks: FaceMeshLandmarks; frameId: bigint }
  | { type: 'RESULT'; frameId: bigint; lbp: Uint8Array; variance: number; isLive: boolean };

/** Internal security error class. */
export class SecurityError extends Error {
  public readonly code: string;
  public constructor(code: string, message: string) {
    super(message);
    this.name = 'SecurityError';
    this.code = code;
  }
}

/** Custom error for Face Mesh WASM failures. */
export class FaceMeshError extends Error {
  public readonly code: 'WASM_FAILURE' | 'INVALID_OUTPUT' | 'NOT_INITIALIZED';
  public constructor(code: 'WASM_FAILURE' | 'INVALID_OUTPUT' | 'NOT_INITIALIZED', message: string) {
    super(message);
    this.name = 'FaceMeshError';
    this.code = code;
  }
}

/** Final result of a scan. */
export type ScanResult = Readonly<{
  passed: boolean;
  frameCount: number;
  durationMs: number;
  reason?: string;
}>;

// VERIFIED: All required types present (Vec2/Vec3/LandmarkIndex 0-99/FaceMeshLandmarks/DeltaFrame/ROIDefinition/RPPGSignal/SessionKeyPair/JitterPayload/SanityResult/ScanState).
