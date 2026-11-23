"""Step 5: find the glowing coating and trace its borders.
Quick check:  python -m coating_inspector.segment samples/approved/approved_1.png"""
from __future__ import annotations

import sys

import cv2
import numpy as np

from .common import load_config, read_image, write_image


def disk(radius: int) -> np.ndarray:
    """Round brush for the morphology operations."""
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def segment_coating(image: np.ndarray, seg: dict) -> np.ndarray:
    """Mask of the coated pixels (uint8, 255 = coating), using the colour range in config.yaml."""
    if seg["blur_px"] > 1:
        k = seg["blur_px"] // 2 * 2 + 1                              # kernel size must be odd
        image = cv2.GaussianBlur(image, (k, k), 0)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(seg["hsv_lower"], np.uint8), np.array(seg["hsv_upper"], np.uint8))
    if seg["open_px"] > 0:                                           # remove specks of noise
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, disk(seg["open_px"]))
    if seg["close_px"] > 0:                                          # fill pinholes and small gaps
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, disk(seg["close_px"]))
    return remove_small_blobs(mask, seg["min_area_px"])


def remove_small_blobs(mask: np.ndarray, min_area_px: int) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = stats[:, cv2.CC_STAT_AREA] >= min_area_px
    keep[0] = False                                                  # label 0 is the background
    return np.where(keep[labels], 255, 0).astype(np.uint8)


def find_borders(mask: np.ndarray) -> list:
    """Outlines of the coated areas (outer edges and holes) as OpenCV contours."""
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    return list(contours)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m coating_inspector.segment <photo>")
    cfg = load_config()
    image = read_image(sys.argv[1])
    mask = segment_coating(image, cfg["segmentation"])
    borders = find_borders(mask)
    preview = image.copy()
    cv2.drawContours(preview, borders, -1, (0, 255, 255), 2)        # yellow outline
    write_image("out/mask.png", mask)
    write_image("out/borders.png", preview)
    ppm = cfg["tolerance"]["pixels_per_mm"]
    print(f"coated area: {cv2.countNonZero(mask) / ppm**2:.0f} mm2 in {len(borders)} outline(s)")
    print("saved out/mask.png and out/borders.png")
