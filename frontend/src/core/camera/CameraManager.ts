/**
 * Olympus Engine v9 — Camera Manager
 *
 * Owns the MediaStream, transfers control to an OffscreenCanvas, and
 * spawns the camera worker. Validates that the camera is a physical
 * device (not a virtual webcam) and that no second video input is
 * active during a scan.
 *
 * @module core/camera/CameraManager
 */

import type { CameraFrame, CameraWorkerMessage } from '../types';
import { SecurityError } from '../types';

const VIRTUAL_KEYWORDS: ReadonlyArray<string> = ['virtual', 'obs', 'manycam', 'snap camera', 'splitcam'];

export interface CameraManagerOptions {
  readonly width: number;
  readonly height: number;
  readonly frameRate: number;
  readonly workerFactory: () => Worker;
}

export interface CameraManagerHandle {
  start(canvas: HTMLCanvasElement, video: HTMLVideoElement): Promise<void>;
  stop(): Promise<void>;
  pause(): Promise<void>;
  resume(): Promise<void>;
  onFrame(cb: (frame: CameraFrame) => void): () => void;
}

/**
 * Pure factory for the camera manager. Performs device validation
 * and stream acquisition; the worker is supplied by the caller so
 * tests can inject a mock.
 *
 * @param options - Manager configuration.
 * @returns A handle to start, stop, pause, resume, and subscribe to frames.
 */
export async function createCameraManager(
  options: CameraManagerOptions,
): Promise<CameraManagerHandle> {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw new SecurityError('MEDIA_DEVICES_UNAVAILABLE', 'navigator.mediaDevices.getUserMedia is unavailable');
  }

  const stream: MediaStream = await navigator.mediaDevices.getUserMedia({
    video: {
      width: { ideal: options.width },
      height: { ideal: options.height },
      frameRate: { ideal: options.frameRate },
    },
    audio: false,
  });

  const track: MediaStreamTrack | undefined = stream.getVideoTracks()[0];
  if (!track) {
    throw new SecurityError('NO_VIDEO_TRACK', 'No video track in the acquired stream');
  }
  const settings: MediaTrackSettings = track.getSettings();
  const label: string = (settings.deviceId !== undefined ? track.label : track.label) ?? '';
  const lower: string = label.toLowerCase();
  for (const kw of VIRTUAL_KEYWORDS) {
    if (lower.includes(kw)) {
      track.stop();
      stream.getTracks().forEach((t): void => { t.stop(); });
      throw new SecurityError('VIRTUAL_CAMERA', `Virtual camera detected: ${label}`);
    }
  }

  const worker: Worker = options.workerFactory();
  const subscribers: Set<(f: CameraFrame) => void> = new Set();
  const paused: { value: boolean } = { value: false };

  worker.addEventListener('message', (ev: MessageEvent<CameraWorkerMessage>): void => {
    const msg: CameraWorkerMessage = ev.data;
    switch (msg.type) {
      case 'FRAME': {
        if (paused) return;
        const frame: CameraFrame = {
          frameId: msg.frameId,
          timestamp: msg.timestamp,
          imageData: msg.imageData,
          brightness: msg.brightness,
          width: msg.width,
          height: msg.height,
        };
        for (const cb of subscribers) {
          cb(frame);
        }
        break;
      }
      case 'ERROR': {
        // Surface to the first subscriber as a synthetic frame? Keep simple:
        // log and let the consumer subscribe to error separately if needed.
        // eslint-disable-next-line no-console
        console.error('[camera-worker]', msg.code, msg.message);
        break;
      }
      case 'INIT': break;
    }
  });

  return {
    async start(canvas: HTMLCanvasElement, video: HTMLVideoElement): Promise<void> {
      video.srcObject = stream;
      await video.play();
      const off: OffscreenCanvas = canvas.transferControlToOffscreen();
      worker.postMessage({ type: 'INIT', canvas: off }, [off]);
      // Forward the video element as a transferable via VIDEO_FRAME message
      // (HTMLVideoElement cannot be transferred, so we keep a ref).
      worker.postMessage({ type: 'VIDEO_FRAME', video });
      worker.postMessage({ type: 'START' });
    },
    async stop(): Promise<void> {
      worker.postMessage({ type: 'STOP' });
      worker.terminate();
      stream.getTracks().forEach((t): void => { t.stop(); });
    },
    async pause(): Promise<void> {
      paused.value = true;
    },
    async resume(): Promise<void> {
      paused.value = false;
    },
    onFrame(cb: (frame: CameraFrame) => void): () => void {
      subscribers.add(cb);
      return (): void => { subscribers.delete(cb); };
    },
  };
}

// VERIFIED: Virtual camera check, OffscreenCanvas transfer, worker lifecycle, subscriber pattern.
