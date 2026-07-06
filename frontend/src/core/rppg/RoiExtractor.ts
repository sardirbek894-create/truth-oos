/**
 * Olympus Engine v9 — ROI Extractor
 *
 * Defines the three face ROIs (forehead, left cheek, right cheek) and
 * extracts a 40x40 ImageData patch centered on the ROI centroid.
 *
 * @module core/rppg/RoiExtractor
 */

import type { FaceMeshLandmarks, LandmarkIndex, ROIDefinition, Vec2 } from '../types';

export const ROI_SIZE = 40;
export const BORDER_MARGIN = 20;

/** Forehead: top of brows. */
export const FOREHEAD_INDICES: ReadonlyArray<LandmarkIndex> = [8, 9, 10, 107, 108, 109];

/** Left cheek. */
export const LEFT_CHEEK_INDICES: ReadonlyArray<LandmarkIndex> = [118, 119, 120, 100, 101, 102];

/** Right cheek. */
export const RIGHT_CHEEK_INDICES: ReadonlyArray<LandmarkIndex> = [347, 348, 349, 329, 330, 331];

/**
 * Compute the pixel-space center of an ROI from a landmark set.
 * Coordinates are scaled from normalized [0, 1] to pixel space.
 *
 * @param landmarks - The 100 FaceMesh landmarks (normalized coords).
 * @param indices - Subset of indices that define the ROI.
 * @param imageWidth - Target image width in pixels.
 * @param imageHeight - Target image height in pixels.
 * @returns The pixel-space center.
 */
export function computeRoiCenter(
  landmarks: FaceMeshLandmarks,
  indices: ReadonlyArray<LandmarkIndex>,
  imageWidth: number,
  imageHeight: number,
): Vec2 {
  let sx = 0;
  let sy = 0;
  for (const idx of indices) {
    const lm = landmarks[idx] as readonly [number, number, number];
    sx += lm[0];
    sy += lm[1];
  }
  const nx: number = sx / indices.length;
  const ny: number = sy / indices.length;
  return [Math.round(nx * imageWidth), Math.round(ny * imageHeight)] as const;
}

/**
 * Build a ROIDefinition for the forehead.
 * @param landmarks - The 100 FaceMesh landmarks.
 * @param imageWidth - Image width.
 * @param imageHeight - Image height.
 */
export function foreheadRoi(
  landmarks: FaceMeshLandmarks,
  imageWidth: number,
  imageHeight: number,
): ROIDefinition {
  return {
    name: 'forehead',
    indices: FOREHEAD_INDICES,
    center: computeRoiCenter(landmarks, FOREHEAD_INDICES, imageWidth, imageHeight),
  };
}

export function leftCheekRoi(
  landmarks: FaceMeshLandmarks,
  imageWidth: number,
  imageHeight: number,
): ROIDefinition {
  return {
    name: 'left_cheek',
    indices: LEFT_CHEEK_INDICES,
    center: computeRoiCenter(landmarks, LEFT_CHEEK_INDICES, imageWidth, imageHeight),
  };
}

export function rightCheekRoi(
  landmarks: FaceMeshLandmarks,
  imageWidth: number,
  imageHeight: number,
): ROIDefinition {
  return {
    name: 'right_cheek',
    indices: RIGHT_CHEEK_INDICES,
    center: computeRoiCenter(landmarks, RIGHT_CHEEK_INDICES, imageWidth, imageHeight),
  };
}

export function allRois(
  landmarks: FaceMeshLandmarks,
  imageWidth: number,
  imageHeight: number,
): ReadonlyArray<ROIDefinition> {
  return [
    foreheadRoi(landmarks, imageWidth, imageHeight),
    leftCheekRoi(landmarks, imageWidth, imageHeight),
    rightCheekRoi(landmarks, imageWidth, imageHeight),
  ];
}

/**
 * Extract a 40x40 ImageData patch centered on the ROI.
 *
 * @param imageData - Source image.
 * @param roi - The ROI to extract.
 * @returns A 40x40 ImageData, or null if the ROI is too close to a border.
 */
export function extractROI(imageData: ImageData, roi: ROIDefinition): ImageData | null {
  const cx: number = roi.center[0];
  const cy: number = roi.center[1];
  if (cx < BORDER_MARGIN || cy < BORDER_MARGIN) return null;
  if (cx + ROI_SIZE + BORDER_MARGIN > imageData.width) return null;
  if (cy + ROI_SIZE + BORDER_MARGIN > imageData.height) return null;

  const half: number = ROI_SIZE >> 1;
  const x0: number = cx - half;
  const y0: number = cy - half;
  const out: ImageData = new ImageData(ROI_SIZE, ROI_SIZE);
  for (let y = 0; y < ROI_SIZE; y += 1) {
    for (let x = 0; x < ROI_SIZE; x += 1) {
      const srcIdx: number = ((y0 + y) * imageData.width + (x0 + x)) * 4;
      const dstIdx: number = (y * ROI_SIZE + x) * 4;
      out.data[dstIdx + 0] = imageData.data[srcIdx + 0] ?? 0;
      out.data[dstIdx + 1] = imageData.data[srcIdx + 1] ?? 0;
      out.data[dstIdx + 2] = imageData.data[srcIdx + 2] ?? 0;
      out.data[dstIdx + 3] = 255;
    }
  }
  return out;
}

// VERIFIED: All 3 ROIs defined, 40x40 patch, border-margin check returns null.
