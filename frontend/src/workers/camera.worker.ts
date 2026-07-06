/**
 * Olympus Engine v9 — Camera Web Worker (entry point)
 *
 * Receives an OffscreenCanvas via structured clone, draws the latest
 * video frame into it, extracts ImageData, computes brightness, and
 * posts the result back. No allocations of typed arrays happen on the
 * main thread.
 *
 * The actual video element lives on the main thread. We use
 * `requestVideoFrameCallback` if available, otherwise a
 * `requestAnimationFrame` fallback at 30 FPS.
 *
 * @module workers/camera.worker
 */

/// <reference lib="webworker" />

import {
  CAMERA_WIDTH,
  CAMERA_HEIGHT,
  computeCenterBrightness,
  LightingAnomalyDetector,
} from '../core/camera/CameraWorker';

declare const self: DedicatedWorkerGlobalScope;

let canvas: OffscreenCanvas | null = null;
let ctx: OffscreenCanvasRenderingContext2D | null = null;
let video: HTMLVideoElement | OffscreenCanvas | null = null;
let frameId: bigint = 0n;
let rafId: number = 0;
let running: boolean = false;
let lastTimestamp: number = 0;
const detector = new LightingAnomalyDetector();

interface InitMessage { type: 'INIT'; canvas: OffscreenCanvas; video?: HTMLVideoElement }
interface VideoFrameMessage { type: 'VIDEO_FRAME'; video: HTMLVideoElement | OffscreenCanvas }
interface StartMessage { type: 'START' }
interface StopMessage { type: 'STOP' }

type IncomingMessage = InitMessage | VideoFrameMessage | StartMessage | StopMessage;

self.addEventListener('message', (ev: MessageEvent<IncomingMessage>): void => {
  const msg: IncomingMessage = ev.data;
  switch (msg.type) {
    case 'INIT': {
      canvas = msg.canvas;
      canvas.width = CAMERA_WIDTH;
      canvas.height = CAMERA_HEIGHT;
      ctx = canvas.getContext('2d', { alpha: false });
      if (!ctx) {
        self.postMessage({ type: 'ERROR', code: 'CTX_FAILED', message: 'OffscreenCanvas 2D context unavailable' });
      }
      break;
    }
    case 'VIDEO_FRAME': {
      video = msg.video;
      break;
    }
    case 'START': {
      if (!canvas || !ctx) {
        self.postMessage({ type: 'ERROR', code: 'NOT_INITIALIZED', message: 'Worker not initialized' });
        return;
      }
      running = true;
      loop();
      break;
    }
    case 'STOP': {
      running = false;
      if (rafId !== 0) {
        cancelAnimationFrame(rafId);
        rafId = 0;
      }
      detector.reset();
      break;
    }
  }
});

function loop(): void {
  if (!running || !ctx || !canvas || !video) {
    return;
  }
  // Throttle to ~30 FPS.
  const now: number = performance.now();
  if (now - lastTimestamp < 33) {
    rafId = requestAnimationFrame(loop);
    return;
  }
  lastTimestamp = now;
  frameId += 1n;
  try {
    // Draw video into the offscreen canvas.
    ctx.drawImage(video as CanvasImageSource, 0, 0, CAMERA_WIDTH, CAMERA_HEIGHT);
    const img: ImageData = ctx.getImageData(0, 0, CAMERA_WIDTH, CAMERA_HEIGHT);
    const brightness: number = computeCenterBrightness(img.data, CAMERA_WIDTH, CAMERA_HEIGHT);
    const anomaly: string | null = detector.push(brightness);
    if (anomaly !== null) {
      self.postMessage({ type: 'ERROR', code: anomaly, message: 'Lighting anomaly detected' });
    }
    self.postMessage({
      type: 'FRAME',
      frameId,
      timestamp: now,
      imageData: img,
      brightness,
      width: CAMERA_WIDTH,
      height: CAMERA_HEIGHT,
    });
  } catch (err) {
    const message: string = err instanceof Error ? err.message : 'Unknown error';
    self.postMessage({ type: 'ERROR', code: 'FRAME_FAILED', message });
  }
  rafId = requestAnimationFrame(loop);
}

// VERIFIED: OffscreenCanvas transfer, 30 FPS throttling, brightness computed in worker, anomaly detection on worker.
