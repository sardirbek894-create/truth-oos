/**
 * Olympus Engine v9 — Texture Web Worker
 *
 * Receives ImageData + landmarks, extracts the forehead ROI, and
 * runs LBP + Laplacian in parallel (sequentially in this single
 * worker). Posts the combined result back to the main thread.
 *
 * @module workers/texture.worker
 */

/// <reference lib="webworker" />

import { foreheadRoi, extractROI } from '../core/rppg/RoiExtractor';
import { lbpImage } from '../core/texture/LBP';
import { laplacianFromPatch } from '../core/texture/Laplacian';
import type { FaceMeshLandmarks, TextureWorkerMessage } from '../core/types';

declare const self: DedicatedWorkerGlobalScope;

interface AnalyzeMessage {
  type: 'ANALYZE';
  imageData: ImageData;
  landmarks: FaceMeshLandmarks;
  frameId: bigint;
}

type IncomingMessage = AnalyzeMessage;

self.addEventListener('message', (ev: MessageEvent<IncomingMessage>): void => {
  const msg: IncomingMessage = ev.data;
  if (msg.type !== 'ANALYZE') return;
  const roi = foreheadRoi(msg.landmarks, msg.imageData.width, msg.imageData.height);
  const patch = extractROI(msg.imageData, roi);
  if (!patch) {
    self.postMessage({
      type: 'RESULT',
      frameId: msg.frameId,
      lbp: new Uint8Array(0),
      variance: 0,
      isLive: false,
    } as TextureWorkerMessage);
    return;
  }
  const lbp = lbpImage(patch);
  const lap = laplacianFromPatch(patch);
  self.postMessage({
    type: 'RESULT',
    frameId: msg.frameId,
    lbp,
    variance: lap.variance,
    isLive: lap.isLive,
  } as TextureWorkerMessage);
});

// VERIFIED: Forehead ROI, LBP + Laplacian, isLive = liveness flag.
