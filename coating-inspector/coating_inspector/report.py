"""Step 9: draw the result picture and write the JSON report."""
from __future__ import annotations  # lets newer type hints work on older Python versions

import json  # writes the JSON report
from dataclasses import asdict  # turns a Defect into a plain dictionary for the JSON report
from pathlib import Path  # handles file paths

import cv2  # OpenCV: drawing outlines, boxes and text
import numpy as np  # NumPy: per-pixel colour blending

from .segment import disk, find_borders  # round brush and outline tracing

FILL = {"missing": (0, 0, 255), "excess": (0, 165, 255), "keepout": (255, 0, 255)}  # BGR: red, orange, magenta
WHITE, GREEN, RED = (255, 255, 255), (0, 220, 0), (0, 0, 255)  # more colours, also in BGR order
LEGEND = ("white = approved outline | green/red = measured outline in/out of tolerance | "
          "fill: red = missing, orange = excess, magenta = keep-out")  # text for the bar at the bottom


def _text_bar(img, text, colour, scale, at_bottom=False):
    """Write text on a coloured bar across the top (or bottom) of the picture.

    Args:
        img: the picture to draw on (changed in place).
        text: the text to write.
        colour: the bar's colour (BGR).
        scale: the text size; reduced automatically if the text is too wide.
        at_bottom: True for the bottom of the picture, False for the top.
    """
    # The font, and a line thickness that grows with the text size.
    font, thick = cv2.FONT_HERSHEY_SIMPLEX, max(1, round(2 * scale))
    # Measure the text: its width, its height, and how far letters such as "g" hang below the line.
    (tw, th), base = cv2.getTextSize(text, font, scale, thick)
    # Too wide for the picture? Shrink the text so it fits with 10 px to spare on each side.
    if tw > img.shape[1] - 20:
        scale *= (img.shape[1] - 20) / tw  # shrink the text size in proportion
        thick = max(1, round(2 * scale))  # line thickness for the new size
        (tw, th), base = cv2.getTextSize(text, font, scale, thick)  # measure again
    # The bar's height: the text, the part hanging below the line, and 16 px of padding.
    height = th + base + 16
    # The bar's top edge: at the bottom of the picture or at the very top.
    top = img.shape[0] - height if at_bottom else 0
    # Draw the filled bar across the full width ...
    cv2.rectangle(img, (0, top), (img.shape[1], top + height), colour, -1)
    # ... and the white text on it.
    cv2.putText(img, text, (10, top + th + 8), font, scale, WHITE, thick, cv2.LINE_AA)


def draw_overlay(inspection, golden) -> np.ndarray:
    """Draw the result picture for one board.

    Args:
        inspection: the Inspection of the board.
        golden: the Golden pattern it was compared with.

    Returns:
        The lined-up photo with defects filled in colour, both outlines, labels and a PASS/FAIL bar.
    """
    # The comparison holds the defects and the drawing layers.
    comp = inspection.comparison
    # Start from the lined-up photo, darkened to 70 % so the coloured marks stand out.
    img = (inspection.aligned * 0.7).astype(np.uint8)
    # Size factor for lines and text: 1.0 for a 1200 px photo, bigger for bigger photos.
    scale = max(img.shape[:2]) / 1200
    # Line thickness in pixels (at least 1).
    line = max(1, round(2 * scale))
    # Fill each kind of defect area with its colour.
    for kind, colour in FILL.items():
        # The True/False mask of this kind's defect areas.
        area = comp.layers[kind]
        # Mix 40 % photo with 60 % colour, so the board stays visible underneath.
        img[area] = (0.4 * img[area] + 0.6 * np.array(colour)).astype(np.uint8)
    # Outline the keep-out zones in magenta, if there are any.
    if golden.keepout is not None:
        # Trace the zones and draw their outlines.
        cv2.drawContours(img, find_borders(golden.keepout), -1, FILL["keepout"], line)
    # Draw the approved outline in white.
    cv2.drawContours(img, find_borders(golden.mask), -1, WHITE, line)
    # Draw the measured outline on top: green where it is within tolerance, red where it is not.
    for key, colour in (("edge_ok", GREEN), ("edge_bad", RED)):
        # Thicken the 1 px outline (dilate) so it is visible, then paint those pixels.
        img[cv2.dilate(comp.layers[key].astype(np.uint8), disk(max(1, line // 2))) > 0] = colour
    # The font and text size for the defect labels.
    font, text_scale = cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale
    # Box and label each defect.
    for d in comp.defects:
        # The defect's bounding box.
        x, y, w, h = d.box
        # Draw the box a little larger than the defect, so it doesn't cover it.
        pad = 4 * line
        # Draw the box in the defect's colour.
        cv2.rectangle(img, (x - pad, y - pad), (x + w + pad, y + h + pad), FILL[d.kind], line)
        # The label, for example "missing 28.8 mm2".
        label = f"{d.kind} {d.area_mm2:.1f} mm2"
        # Measure the label, so it can be kept inside the picture.
        (tw, th), _ = cv2.getTextSize(label, font, text_scale, line)
        # Put the label above the box, moved left or down if it would leave the picture.
        tx = min(max(0, x - pad), img.shape[1] - tw - 4)
        ty = max(th + 4, y - pad - 6)  # just above the box, but never above the picture's top
        # A black background makes the label readable on any part of the board ...
        cv2.rectangle(img, (tx - 2, ty - th - 4), (tx + tw + 2, ty + 4), (0, 0, 0), -1)
        # ... with the label written in the defect's colour.
        cv2.putText(img, label, (tx, ty), font, text_scale, FILL[d.kind], line, cv2.LINE_AA)
    # The verdict text: PASS, or FAIL followed by the reasons.
    verdict = "PASS" if comp.passed else "FAIL: " + "; ".join(comp.reasons)
    # Write it on a green (PASS) or red (FAIL) bar at the top.
    _text_bar(img, verdict, (0, 130, 0) if comp.passed else (0, 0, 190), 0.9 * scale)
    # The colour legend goes on a dark bar at the bottom.
    _text_bar(img, LEGEND, (40, 40, 40), 0.5 * scale, at_bottom=True)
    # The finished picture.
    return img


def write_report(path, image_path, inspection) -> None:
    """Write the JSON report for one board.

    Args:
        path: where to save the report (.json).
        image_path: the photo that was inspected (recorded in the report).
        inspection: the Inspection of the board.
    """
    # Short names for the two parts used below.
    comp, al = inspection.comparison, inspection.alignment
    # Everything worth keeping, as dictionaries, lists, text and numbers (the things JSON can store).
    report = {
        "image": str(image_path),                                  # which photo
        "result": "PASS" if comp.passed else "FAIL",               # the verdict
        "reasons": comp.reasons,                                   # why it failed (empty if it passed)
        "metrics": comp.metrics,                                   # the measurements
        "defects": [asdict(d) for d in comp.defects],              # each defect as a dictionary
        "alignment": {"inliers": al.inliers,                       # how well the photo lined up ...
                      "shift_px": [round(v, 2) for v in al.shift_px],  # ... how far the board was shifted
                      "rotation_deg": round(al.rotation_deg, 3)},  # ... and how much it was rotated
    }
    # Save it as indented, readable JSON text.
    Path(path).write_text(json.dumps(report, indent=2), encoding="utf-8")
