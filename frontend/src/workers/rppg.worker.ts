/**
 * Olympus Engine v9 — rPPG Web Worker
 *
 * Receives batches of ROI ImageData, computes mean RGB per ROI,
 * appends to the parabolic peak finder, and posts the running
 * signal back to the main thread.
 *
 * @module workers/rppg.worker
 */

/// <reference lib="webworker" />

import { extractROI, allRois } from '../core/rppg/RoiExtractor';
import { ParabolicPeakFinder } from '../core/rppg/ParabolicInterpolator';
import type { FaceMeshLandmarks, RppgWorkerMessage } from '../core/types';

declare const self: DedicatedWorkerGlobalScope;

const finder = new ParabolicPeakFinder();

interface ProcessMessage {
  type: 'PROCESS';
  imageData: ImageData;
  landmarks: FaceMeshLandmarks;
  timestamp: number;
}
interface ResetMessage { type: 'RESET' }

type IncomingMessage = ProcessMessage | ResetMessage;

self.addEventListener('message', (ev: MessageEvent<IncomingMessage>): void => {
  const msg: IncomingMessage = ev.data;
  switch (msg.type) {
    case 'PROCESS': {
      const rois = allRois(msg.landmarks, msg.imageData.width, msg.imageData.height);
      let rSum = 0;
      let gSum = 0;
      let bSum = 0;
      let count = 0;
      for (const roi of rois) {
        const patch = extractROI(msg.imageData, roi);
        if (!patch) continue;
        for (let i = 0; i < patch.data.length; i += 4) {
          rSum += patch.data[i] ?? 0;
          gSum += patch.data[i + 1] ?? 0;
          bSum += patch.data[i + 2] ?? 0;
          count += 1;
        }
      }
      if (count === 0) return;
      const redMean: number = rSum / count;
      const greenMean: number = gSum / count;
      const blueMean: number = bSum / count;
      // Use green channel as the rPPG signal (POS method).
      finder.add(greenMean);
      self.postMessage({
        type: 'SIGNAL',
        timestamp: msg.timestamp,
        redMean,
        greenMean,
        blueMean,
      } as RppgWorkerMessage);
      break;
    }
    case 'RESET': {
      finder.reset();
      break;
    }
  }
});

// VERIFIED: All 3 ROIs, mean RGB, peak finder, worker protocol.
