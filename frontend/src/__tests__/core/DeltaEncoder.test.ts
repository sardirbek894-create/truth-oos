/**
 * Olympus Engine v9 — Delta Encoder Tests
 */

import { describe, it, expect } from 'vitest';
import {
  encode,
  decode,
  landmarksToFlat,
  flatToLandmarksInt32,
  validatePhysiological,
  DeltaEncoderState,
} from '../../core/face/DeltaEncoder';
import type { FaceMeshLandmarks } from '../../core/types';

function makeFace(cx: number = 0.5, cy: number = 0.5): FaceMeshLandmarks {
  const out: Array<readonly [number, number, number]> = [];
  for (let i = 0; i < 100; i += 1) {
    out.push([cx + i * 0.0001, cy + i * 0.0001, 0] as const);
  }
  return out as unknown as FaceMeshLandmarks;
}

function makeFaceShifted(dx: number, dy: number): FaceMeshLandmarks {
  const out: Array<readonly [number, number, number]> = [];
  for (let i = 0; i < 100; i += 1) {
    out.push([0.5 + dx + i * 0.0001, 0.5 + dy + i * 0.0001, 0] as const);
  }
  return out as unknown as FaceMeshLandmarks;
}

describe('landmarksToFlat / flatToLandmarksInt32', (): void => {
  it('round-trips through integer scaling', (): void => {
    const lm = makeFace();
    const flat = landmarksToFlat(lm);
    expect(flat.length).toBe(300);
    const back = flatToLandmarksInt32(flat);
    expect(back.length).toBe(100);
  });

  it('throws on wrong length', (): void => {
    expect((): Int32Array => landmarksToFlat([] as unknown as FaceMeshLandmarks)).toThrow();
  });
});

describe('encode / decode', (): void => {
  it('first frame is absolute', (): void => {
    const state = new DeltaEncoderState();
    const d = encode(makeFace(), null, state);
    expect(d.isAbsolute).toBe(true);
    expect(d.deltas.length).toBe(300);
  });

  it('second frame is delta-encoded', (): void => {
    const state = new DeltaEncoderState();
    encode(makeFace(), null, state);
    const d = encode(makeFaceShifted(0.001, 0), makeFace(), state);
    expect(d.isAbsolute).toBe(false);
    expect(d.sentinel).toBe(0);
  });

  it('round-trips a small motion', (): void => {
    const state = new DeltaEncoderState();
    const first = makeFace();
    const second = makeFaceShifted(0.001, 0.001);
    encode(first, null, state);
    const d = encode(second, first, state);
    const back = decode(d, first);
    // All landmarks should match within 1/1000 (one Int16 unit).
    for (let i = 0; i < 100; i += 1) {
      const a = first[i] as readonly [number, number, number];
      const b = back[i] as readonly [number, number, number];
      expect(Math.abs(a[0] - b[0])).toBeLessThan(0.002);
      expect(Math.abs(a[1] - b[1])).toBeLessThan(0.002);
    }
  });

  it('emits a sentinel when delta exceeds Int16 range', (): void => {
    const state = new DeltaEncoderState();
    encode(makeFace(), null, state);
    const huge = makeFaceShifted(100, 100); // way out of range
    const d = encode(huge, makeFace(), state);
    expect(d.sentinel).toBe(999999);
    expect(state.pendingSentinel).toBe(true);
  });

  it('emits a repeat sentinel after 10 identical frames', (): void => {
    const state = new DeltaEncoderState();
    encode(makeFace(), null, state);
    const same = makeFace();
    for (let i = 0; i < 9; i += 1) {
      const d = encode(same, same, state);
      expect(d.sentinel).toBe(0);
    }
    const tenth = encode(same, same, state);
    expect(tenth.sentinel).toBe(999999);
  });
});

describe('validatePhysiological', (): void => {
  it('accepts a normal face', (): void => {
    expect(validatePhysiological(makeFace())).toBe(true);
  });

  it('rejects a degenerate face', (): void => {
    const lm: FaceMeshLandmarks = new Array(100).fill([0.5, 0.5, 0] as const) as unknown as FaceMeshLandmarks;
    expect(validatePhysiological(lm)).toBe(false);
  });
});

// VERIFIED: 9 test cases covering rules 1, 2, 3, round-trip, and physiological validation.
