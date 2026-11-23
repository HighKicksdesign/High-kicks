"""Step 9: compare a board's coating with the golden pattern and decide PASS or FAIL."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .align import Alignment, align_to_reference
from .segment import disk, find_borders, segment_coating


@dataclass
class Defect:
    kind: str                       # "missing", "excess" or "keepout"
    area_mm2: float
    box: tuple                      # x, y, width, height in pixels of the golden reference photo


@dataclass
class Comparison:
    passed: bool
    reasons: list
    metrics: dict
    defects: list
    layers: dict = field(repr=False)    # masks used to draw the result picture


@dataclass
class Inspection:
    aligned: np.ndarray             # the photo, lined up with the golden reference photo
    mask: np.ndarray                # coating found in the photo
    alignment: Alignment
    comparison: Comparison


def inspect_image(image, golden, cfg) -> Inspection:
    """Align the photo, find its coating and compare it with the golden pattern."""
    alignment = align_to_reference(golden.reference, image, cfg["alignment"])
    mask = segment_coating(alignment.image, cfg["segmentation"])
    comparison = compare_masks(mask, golden.mask, alignment.valid, golden.keepout, cfg["tolerance"])
    return Inspection(alignment.image, mask, alignment, comparison)


def _edge_pixels(mask):
    edges = np.zeros(mask.shape, np.uint8)
    cv2.drawContours(edges, find_borders(mask), -1, 255, 1)
    return edges > 0


def _distance_to(pixels):
    """Distance (px) from every pixel to the nearest True pixel in `pixels`."""
    return cv2.distanceTransform(np.where(pixels, 0, 255).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)


def _blobs(region, kind, min_area_px, px_per_mm):
    """Connected areas of `region` at least `min_area_px` big -> (list of defects, mask of those areas)."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(region.astype(np.uint8), connectivity=8)
    keep = np.zeros(count, bool)
    defects = []
    for i in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area >= min_area_px:
            keep[i] = True
            defects.append(Defect(kind, round(area / px_per_mm**2, 2), (x, y, w, h)))
    return defects, keep[labels]


def compare_masks(test_mask, golden_mask, valid, keepout, tol) -> Comparison:
    ppm = tol["pixels_per_mm"]
    band = max(1, round(tol["border_mm"] * ppm))                    # allowed edge wander, px
    inside = valid > 0                                               # pixels the photo really covers
    test = (test_mask > 0) & inside
    golden = (golden_mask > 0) & inside
    keep_out = (keepout > 0) & inside if keepout is not None else np.zeros_like(test)
    must_coat = (cv2.erode(golden_mask, disk(band)) > 0) & inside   # golden shrunk by the tolerance
    may_coat = cv2.dilate(golden_mask, disk(band)) > 0              # golden grown by the tolerance

    min_px = tol["min_defect_mm2"] * ppm**2
    missing, missing_px = _blobs(must_coat & ~test, "missing", min_px, ppm)
    excess, excess_px = _blobs(test & ~may_coat & ~keep_out, "excess", min_px, ppm)
    in_keepout, keepout_px = _blobs(test & keep_out, "keepout", tol["keepout_min_mm2"] * ppm**2, ppm)

    # Outline comparison: from every edge pixel, how far is the nearest edge pixel of the other outline?
    usable = cv2.erode(valid, disk(3)) > 0
    test_edge, golden_edge = _edge_pixels(test_mask), _edge_pixels(golden_mask)
    dev_test = np.zeros(test_mask.shape, np.float32)
    deviations = np.array([])
    if test_edge.any() and golden_edge.any():
        dev_test = _distance_to(golden_edge)                         # measured edge -> approved edge
        dev_golden = _distance_to(test_edge)                         # approved edge -> measured edge
        deviations = np.concatenate([dev_test[test_edge & usable], dev_golden[golden_edge & usable]])
    found = deviations.size > 0

    metrics = {
        "coverage_pct": round(float(100 * (must_coat & test).sum() / max(must_coat.sum(), 1)), 2),
        "outline_match_pct": round(float(100 * np.mean(deviations <= band)), 2) if found else 0.0,
        "edge_deviation_p95_mm": round(float(np.percentile(deviations, 95) / ppm), 3) if found else None,
        "edge_deviation_max_mm": round(float(deviations.max() / ppm), 3) if found else None,
        "iou": round(float((golden & test).sum() / max((golden | test).sum(), 1)), 4),
        "coated_area_mm2": round(float(test.sum() / ppm**2), 1),
        "golden_area_mm2": round(float(golden.sum() / ppm**2), 1),
    }
    reasons = []
    if not test.any():
        reasons.append("no coating found - check the light and the colour settings")
    if in_keepout:
        reasons.append(f"coating in keep-out zone ({len(in_keepout)})")
    if missing:
        reasons.append(f"missing coating ({len(missing)})")
    if excess:
        reasons.append(f"coating outside pattern ({len(excess)})")
    if metrics["coverage_pct"] < tol["min_coverage_pct"]:
        reasons.append(f"coverage {metrics['coverage_pct']}% < {tol['min_coverage_pct']}%")
    if metrics["outline_match_pct"] < tol["min_outline_match_pct"]:
        reasons.append(f"only {metrics['outline_match_pct']}% of outline within {tol['border_mm']} mm")

    layers = {"missing": missing_px, "excess": excess_px, "keepout": keepout_px,
              "edge_ok": test_edge & usable & (dev_test <= band),
              "edge_bad": test_edge & usable & (dev_test > band)}
    return Comparison(not reasons, reasons, metrics, in_keepout + missing + excess, layers)
