"""Step 9: compare a board's coating with the golden pattern and decide PASS or FAIL."""
from __future__ import annotations  # lets newer type hints work on older Python versions

from dataclasses import dataclass, field  # @dataclass holds named values; field() sets options for one value

import cv2  # OpenCV: erode/dilate, connected areas, distance transform
import numpy as np  # NumPy: per-pixel True/False maths

from .align import Alignment, align_to_reference  # lines the photo up with the golden reference photo
from .segment import disk, find_borders, segment_coating  # round brush, outlines, coating detection


@dataclass  # turns the class below into a simple holder of the named values listed in it
class Defect:
    """One defect found on a board."""
    kind: str                       # "missing", "excess" or "keepout"
    area_mm2: float                 # its size in square millimetres
    box: tuple                      # x, y, width, height in pixels of the golden reference photo


@dataclass  # turns the class below into a simple holder of the named values listed in it
class Comparison:
    """The result of comparing one board with the golden pattern."""
    passed: bool                    # True = PASS, False = FAIL
    reasons: list                   # why it failed, in words (empty when it passed)
    metrics: dict                   # measurements: coverage, outline match, edge deviation, areas ...
    defects: list                   # the Defect objects found
    layers: dict = field(repr=False)    # masks used to draw the result picture (left out when printed)


@dataclass  # turns the class below into a simple holder of the named values listed in it
class Inspection:
    """Everything known about one inspected photo."""
    aligned: np.ndarray             # the photo, lined up with the golden reference photo
    mask: np.ndarray                # the coating found in the photo
    alignment: Alignment            # how the photo was lined up
    comparison: Comparison          # the PASS/FAIL result and measurements


def inspect_image(image, golden, cfg) -> Inspection:
    """Inspect one photo: line it up, find its coating and compare it with the golden pattern.

    Args:
        image: the board photo (BGR).
        golden: the Golden pattern.
        cfg: all settings from config.yaml.

    Returns:
        An Inspection with the aligned photo, the coating mask, the alignment and the result.
    """
    # 1. Line the photo up with the golden reference photo.
    alignment = align_to_reference(golden.reference, image, cfg["alignment"])
    # 2. Find the coating in the lined-up photo.
    mask = segment_coating(alignment.image, cfg["segmentation"])
    # 3. Compare that coating with the golden pattern.
    comparison = compare_masks(mask, golden.mask, alignment.valid, golden.keepout, cfg["tolerance"])
    # Bundle everything together for the report.
    return Inspection(alignment.image, mask, alignment, comparison)


def _edge_pixels(mask):
    """Find the outline pixels of a mask.

    Args:
        mask: a 0/255 mask.

    Returns:
        A True/False array: True on the outline (1 px wide).
    """
    # Start with an all-black picture.
    edges = np.zeros(mask.shape, np.uint8)
    # Draw every outline in white, 1 px wide.
    cv2.drawContours(edges, find_borders(mask), -1, 255, 1)
    # True where an outline was drawn.
    return edges > 0


def _distance_to(pixels):
    """For every pixel, measure the distance in px to the nearest True pixel of `pixels`.

    Args:
        pixels: a True/False array (for example an outline).

    Returns:
        A decimal array of distances in pixels.
    """
    # distanceTransform measures the distance to the nearest 0 (black) pixel, so the True pixels become 0.
    # DIST_L2 = straight-line distance; DIST_MASK_PRECISE = exact rather than approximate.
    return cv2.distanceTransform(np.where(pixels, 0, 255).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)


def _blobs(region, kind, min_area_px, px_per_mm):
    """Split a region into separate areas and keep those big enough to count as defects.

    Args:
        region: a True/False array, for example "should be coated but is not".
        kind: the defect type to record ("missing", "excess" or "keepout").
        min_area_px: the smallest area that counts, in pixels.
        px_per_mm: for converting areas to mm2.

    Returns:
        (defects, mask): a list of Defect objects, and a True/False mask of just those areas.
    """
    # Number every separate area and measure its bounding box and size.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(region.astype(np.uint8), connectivity=8)
    # Which area numbers to keep: none yet.
    keep = np.zeros(count, bool)
    # The defects found so far: none yet.
    defects = []
    # Check every area (number 0 is the background, so start at 1).
    for i in range(1, count):
        # Its bounding box (x, y, width, height) and area in pixels, as plain whole numbers.
        x, y, w, h, area = (int(v) for v in stats[i])
        # Big enough to count?
        if area >= min_area_px:
            # Keep it in the mask ...
            keep[i] = True
            # ... and record it as a defect, with its area converted to mm2.
            defects.append(Defect(kind, round(area / px_per_mm**2, 2), (x, y, w, h)))
    # The defects, and a mask that is True only on the kept areas.
    return defects, keep[labels]


def compare_masks(test_mask, golden_mask, valid, keepout, tol) -> Comparison:
    """Compare a board's coating with the golden pattern.

    Args:
        test_mask: the coating found on the board (0/255), lined up with the golden pattern.
        golden_mask: where coating must be (0/255).
        valid: 255 where the board photo has real pixels.
        keepout: the keep-out zones (0/255), or None.
        tol: the "tolerance" section of config.yaml.

    Returns:
        A Comparison with PASS/FAIL, reasons, measurements, defects and drawing layers.
    """
    # The photo's scale.
    ppm = tol["pixels_per_mm"]
    # The allowed edge wander, converted from mm to pixels (at least 1 px).
    band = max(1, round(tol["border_mm"] * ppm))
    # Only judge the pixels the photo really covers.
    inside = valid > 0
    # The board's coating, as True/False.
    test = (test_mask > 0) & inside
    # Where the golden pattern has coating, as True/False.
    golden = (golden_mask > 0) & inside
    # The keep-out zones as True/False (all False when there are none).
    keep_out = (keepout > 0) & inside if keepout is not None else np.zeros_like(test)
    # "Must coat": the golden area shrunk by the tolerance band (erode = shrink).
    must_coat = (cv2.erode(golden_mask, disk(band)) > 0) & inside
    # "May coat": the golden area grown by the tolerance band (dilate = grow).
    may_coat = cv2.dilate(golden_mask, disk(band)) > 0

    # The smallest defect that counts, converted from mm2 to pixels.
    min_px = tol["min_defect_mm2"] * ppm**2
    # Missing coating: must be coated, but is not (~ means "not").
    missing, missing_px = _blobs(must_coat & ~test, "missing", min_px, ppm)
    # Excess coating: coated where not even "may coat" (keep-out zones are counted separately below).
    excess, excess_px = _blobs(test & ~may_coat & ~keep_out, "excess", min_px, ppm)
    # Keep-out defects: coated inside a keep-out zone, with their own (smaller) minimum size.
    in_keepout, keepout_px = _blobs(test & keep_out, "keepout", tol["keepout_min_mm2"] * ppm**2, ppm)

    # Outline comparison: from every edge pixel, how far is the nearest edge pixel of the other outline?
    # Ignore outline pixels within 3 px of the photo's edge, where outlines are cut off artificially.
    usable = cv2.erode(valid, disk(3)) > 0
    # The outline pixels of the board's coating and of the golden pattern.
    test_edge, golden_edge = _edge_pixels(test_mask), _edge_pixels(golden_mask)
    # Defaults for when there is no outline at all (for example when no coating is found).
    dev_test = np.zeros(test_mask.shape, np.float32)
    deviations = np.array([])  # an empty list of distances
    # Only measure when both outlines exist.
    if test_edge.any() and golden_edge.any():
        # Every pixel's distance to the approved edge (read off at the measured edge below).
        dev_test = _distance_to(golden_edge)
        # Every pixel's distance to the measured edge (read off at the approved edge below).
        dev_golden = _distance_to(test_edge)
        # All the distances, both ways: measured -> approved and approved -> measured.
        deviations = np.concatenate([dev_test[test_edge & usable], dev_golden[golden_edge & usable]])
    # Were there any distances to summarise?
    found = deviations.size > 0

    # The measurements, rounded for the report (float() turns NumPy numbers into plain Python numbers).
    metrics = {
        # Share of the must-coat area that is coated, in %.
        "coverage_pct": round(float(100 * (must_coat & test).sum() / max(must_coat.sum(), 1)), 2),
        # Share of the outline points that lie within the tolerance band, in %.
        "outline_match_pct": round(float(100 * np.mean(deviations <= band)), 2) if found else 0.0,
        # 95 % of the outline points are closer than this to the other outline, in mm.
        "edge_deviation_p95_mm": round(float(np.percentile(deviations, 95) / ppm), 3) if found else None,
        # The largest outline distance, in mm.
        "edge_deviation_max_mm": round(float(deviations.max() / ppm), 3) if found else None,
        # Overlap of coating and golden pattern: shared area / combined area (1.0 = identical).
        "iou": round(float((golden & test).sum() / max((golden | test).sum(), 1)), 4),
        # The coated area on the board, in mm2.
        "coated_area_mm2": round(float(test.sum() / ppm**2), 1),
        # The coated area in the golden pattern, in mm2.
        "golden_area_mm2": round(float(golden.sum() / ppm**2), 1),
    }
    # Collect every reason to fail, in words.
    reasons = []
    # No coating at all usually means the light or the colour settings are wrong.
    if not test.any():
        reasons.append("no coating found - check the light and the colour settings")  # add this reason to the list
    # Coating inside a keep-out zone.
    if in_keepout:
        reasons.append(f"coating in keep-out zone ({len(in_keepout)})")  # the reason, with how many were found
    # Missing coating.
    if missing:
        reasons.append(f"missing coating ({len(missing)})")  # the reason, with how many were found
    # Coating outside the pattern.
    if excess:
        reasons.append(f"coating outside pattern ({len(excess)})")  # the reason, with how many were found
    # Too little of the must-coat area is coated, even if no single gap is big enough to count.
    if metrics["coverage_pct"] < tol["min_coverage_pct"]:
        # The reason, with the measured and the required %.
        reasons.append(f"coverage {metrics['coverage_pct']}% < {tol['min_coverage_pct']}%")
    # Too much of the outline is outside the tolerance band (for example a shifted pattern).
    if metrics["outline_match_pct"] < tol["min_outline_match_pct"]:
        # The reason, with the measured %.
        reasons.append(f"only {metrics['outline_match_pct']}% of outline within {tol['border_mm']} mm")

    # Masks for the result picture: the defect areas, plus the measured outline split into pixels within
    # tolerance (edge_ok, drawn green) and outside it (edge_bad, drawn red).
    layers = {"missing": missing_px, "excess": excess_px, "keepout": keepout_px,
              "edge_ok": test_edge & usable & (dev_test <= band),
              "edge_bad": test_edge & usable & (dev_test > band)}
    # PASS when there is no reason to fail; keep-out defects are listed first.
    return Comparison(not reasons, reasons, metrics, in_keepout + missing + excess, layers)
