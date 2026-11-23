"""Step 9: draw the result picture and write the JSON report."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from .segment import disk, find_borders

FILL = {"missing": (0, 0, 255), "excess": (0, 165, 255), "keepout": (255, 0, 255)}  # BGR: red, orange, magenta
WHITE, GREEN, RED = (255, 255, 255), (0, 220, 0), (0, 0, 255)
LEGEND = ("white = approved outline | green/red = measured outline in/out of tolerance | "
          "fill: red = missing, orange = excess, magenta = keep-out")


def _text_bar(img, text, colour, scale, at_bottom=False):
    """Write `text` on a coloured bar across the top (or bottom) of the picture."""
    font, thick = cv2.FONT_HERSHEY_SIMPLEX, max(1, round(2 * scale))
    (tw, th), base = cv2.getTextSize(text, font, scale, thick)
    if tw > img.shape[1] - 20:                                       # shrink long text to fit
        scale *= (img.shape[1] - 20) / tw
        thick = max(1, round(2 * scale))
        (tw, th), base = cv2.getTextSize(text, font, scale, thick)
    height = th + base + 16
    top = img.shape[0] - height if at_bottom else 0
    cv2.rectangle(img, (0, top), (img.shape[1], top + height), colour, -1)
    cv2.putText(img, text, (10, top + th + 8), font, scale, WHITE, thick, cv2.LINE_AA)


def draw_overlay(inspection, golden) -> np.ndarray:
    comp = inspection.comparison
    img = (inspection.aligned * 0.7).astype(np.uint8)                # darken so the marks stand out
    scale = max(img.shape[:2]) / 1200                                # size the marks to the photo
    line = max(1, round(2 * scale))
    for kind, colour in FILL.items():                                # fill the defect areas
        area = comp.layers[kind]
        img[area] = (0.4 * img[area] + 0.6 * np.array(colour)).astype(np.uint8)
    if golden.keepout is not None:
        cv2.drawContours(img, find_borders(golden.keepout), -1, FILL["keepout"], line)
    cv2.drawContours(img, find_borders(golden.mask), -1, WHITE, line)               # approved outline
    for key, colour in (("edge_ok", GREEN), ("edge_bad", RED)):                    # measured outline
        img[cv2.dilate(comp.layers[key].astype(np.uint8), disk(max(1, line // 2))) > 0] = colour
    font, text_scale = cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale
    for d in comp.defects:
        x, y, w, h = d.box
        pad = 4 * line
        cv2.rectangle(img, (x - pad, y - pad), (x + w + pad, y + h + pad), FILL[d.kind], line)
        label = f"{d.kind} {d.area_mm2:.1f} mm2"
        (tw, th), _ = cv2.getTextSize(label, font, text_scale, line)
        tx = min(max(0, x - pad), img.shape[1] - tw - 4)             # keep the label inside the picture
        ty = max(th + 4, y - pad - 6)
        cv2.rectangle(img, (tx - 2, ty - th - 4), (tx + tw + 2, ty + 4), (0, 0, 0), -1)
        cv2.putText(img, label, (tx, ty), font, text_scale, FILL[d.kind], line, cv2.LINE_AA)
    verdict = "PASS" if comp.passed else "FAIL: " + "; ".join(comp.reasons)
    _text_bar(img, verdict, (0, 130, 0) if comp.passed else (0, 0, 190), 0.9 * scale)
    _text_bar(img, LEGEND, (40, 40, 40), 0.5 * scale, at_bottom=True)
    return img


def write_report(path, image_path, inspection) -> None:
    comp, al = inspection.comparison, inspection.alignment
    report = {
        "image": str(image_path),
        "result": "PASS" if comp.passed else "FAIL",
        "reasons": comp.reasons,
        "metrics": comp.metrics,
        "defects": [asdict(d) for d in comp.defects],
        "alignment": {"inliers": al.inliers,
                      "shift_px": [round(v, 2) for v in al.shift_px],
                      "rotation_deg": round(al.rotation_deg, 3)},
    }
    Path(path).write_text(json.dumps(report, indent=2), encoding="utf-8")
