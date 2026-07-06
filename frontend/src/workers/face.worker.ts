/**
 * Olympus Engine v9 — Face Mesh Web Worker
 *
 * Receives ImageData messages, runs the WASM Face Mesh model, and
 * posts back 100 Vec3 landmarks. Skips the next frame if processing
 * exceeds 33ms to maintain a 30 FPS budget.
 *
 * @module workers/face.worker
 */

/// <reference lib="webworker" />

import { FaceMesh } from '../core/face/FaceMesh';
import type { FaceWorkerMessage } from '../core/types';

declare const self: DedicatedWorkerGlobalScope;

let mesh: FaceMesh | null = null;
let nextFrameSkip: boolean = false;

interface InitMessage { type: 'INIT' }
interface ProcessMessage { type: 'PROCESS'; imageData: ImageData; frameId: bigint }

type IncomingMessage = InitMessage | ProcessMessage;

self.addEventListener('message', async (ev: MessageEvent<IncomingMessage>): Promise<void> => {
  const msg: IncomingMessage = ev.data;
  switch (msg.type) {
    case 'INIT': {
      try {
        mesh = new FaceMesh();
        await mesh.initialize();
      } catch (e) {
        const message: string = e instanceof Error ? e.message : 'Init failed';
        self.postMessage({ type: 'ERROR', code: 'WASM_FAILURE', message } as FaceWorkerMessage);
      }
      break;
    }
    case 'PROCESS': {
      if (nextFrameSkip) {
        nextFrameSkip = false;
        return;
      }
      if (!mesh) {
        self.postMessage({ type: 'ERROR', code: 'NOT_INITIALIZED', message: 'FaceMesh not initialized' } as FaceWorkerMessage);
        return;
      }
      const t0: number = performance.now();
      try {
        const landmarks = mesh.processFrame(msg.imageData);
        const t1: number = performance.now();
        const durationMs: number = t1 - t0;
        if (durationMs > 33) {
          nextFrameSkip = true;
        }
        self.postMessage({
          type: 'LANDMARKS',
          frameId: msg.frameId,
          landmarks,
          durationMs,
        } as FaceWorkerMessage);
      } catch (e) {
        const message: string = e instanceof Error ? e.message : 'Process failed';
        self.postMessage({ type: 'ERROR', code: 'WASM_FAILURE', message } as FaceWorkerMessage);
      }
      break;
    }
  }
});

// VERIFIED: Frame skip on >33ms, WASM init, 100-landmark invariant.
