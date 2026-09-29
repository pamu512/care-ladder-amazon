"""Privacy helpers: blur faces/person regions and silhouette visualization."""

from __future__ import annotations

import cv2
import numpy as np


def _person_mask(frame: np.ndarray) -> np.ndarray:
    """Binary mask of skin-like or non-background person regions (uint8 0/255)."""
    ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
    # Classic skin range in YCrCb
    skin = cv2.inRange(ycrcb, (0, 133, 77), (255, 173, 127))

    # Broader chromatic foreground (covers synthetic test blob and clothing tones)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    chroma = cv2.inRange(hsv, (0, 20, 40), (180, 255, 255))

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, luma = cv2.threshold(gray, 40, 255, cv2.THRESH_BINARY)

    mask = cv2.bitwise_or(skin, cv2.bitwise_and(chroma, luma))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return mask


def blur_faces(frame: np.ndarray) -> np.ndarray:
    """Blur detected face / person-like regions for privacy (GaussianBlur ROIs).

    Uses skin/threshold masks + contour ROIs (OpenCV 5 has no bundled Haar XML).
    Blurs an expanded ROI so uniform blobs mix with surrounding pixels.
    Returns a BGR frame the same shape as ``frame``.
    """
    if frame is None or frame.size == 0:
        raise ValueError("frame must be a non-empty ndarray")

    out = frame.copy()
    mask = _person_mask(frame)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    h, w = frame.shape[:2]
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        if bw * bh < 64:
            continue
        # Odd kernel sized from ROI; strong privacy blur
        k = max(21, (min(bw, bh) // 2) | 1)
        if k % 2 == 0:
            k += 1
        pad = k // 2
        x0, y0 = max(x - pad, 0), max(y - pad, 0)
        x1, y1 = min(x + bw + pad, w), min(y + bh + pad, h)
        roi = out[y0:y1, x0:x1]
        if roi.size == 0:
            continue
        out[y0:y1, x0:x1] = cv2.GaussianBlur(roi, (k, k), 0)

    return out


def to_silhouette(frame: np.ndarray) -> np.ndarray:
    """Grayscale person-mask silhouette (filled contours), not a full-color photo.

    Returns a single-channel uint8 image (0 background, 255 person).
    """
    if frame is None or frame.size == 0:
        raise ValueError("frame must be a non-empty ndarray")

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 40, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    sil = np.zeros(gray.shape, dtype=np.uint8)
    cv2.drawContours(sil, contours, -1, 255, thickness=cv2.FILLED)
    return sil
