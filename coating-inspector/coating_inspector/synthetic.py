"""Step 4: make synthetic photos of a coated board under blue/UV light, so every step can be
run and checked before you have real photos.   Run:  python -m coating_inspector.synthetic"""
from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np

from .common import write_image

PX_PER_MM = 10                      # same as tolerance.pixels_per_mm in config.yaml
WIDTH, HEIGHT = 1200, 900           # photo size, px
BOARD_MM = (100, 70)                # board size, mm
ORIGIN = (100, 100)                 # board's top-left corner in the photo, px
HOLES_MM = [(4, 4), (96, 4), (4, 66), (96, 66)]

# BGR colours as a camera sees them under UV/blue light (no emission filter)
BACKGROUND = (12, 6, 10)
SOLDER_MASK = (75, 22, 48)          # dark violet
COPPER = (140, 55, 105)             # reflects the light: brighter violet
IC_BODY = (28, 16, 22)
PIN = (200, 140, 185)
PART_BODY = (60, 70, 90)
SILKSCREEN = (190, 172, 176)        # white ink glows a little, but is not saturated blue
CONNECTOR = (150, 122, 136)
GLOW = (255, 205, 110)              # the coating's UV tracer glows light blue


class Sample(NamedTuple):
    folder: str
    seed: int
    angle: float                    # rotation in the fixture, degrees counter-clockwise
    shift: tuple                    # shift in the fixture, (x, y) px
    defect: str | None


SAMPLES = {
    "approved_1": Sample("approved", 1, 0.0, (0, 0), None),    # the reference: placed exactly
    "approved_2": Sample("approved", 2, 0.8, (12, -7), None),
    "approved_3": Sample("approved", 3, -0.6, (-9, 10), None),
    "good_1": Sample("test", 4, 1.3, (18, 9), None),
    "good_2": Sample("test", 5, -1.1, (-15, -12), None),
    "missing_coating": Sample("test", 6, 0.5, (8, 14), "missing_coating"),
    "excess_spill": Sample("test", 7, -0.9, (-11, 6), "excess_spill"),
    "keepout_violation": Sample("test", 8, 1.0, (14, -10), "keepout_violation"),
    "shifted_pattern": Sample("test", 9, -0.4, (6, 8), "shifted_pattern"),
}


def P(x_mm, y_mm):
    """Position on the board in mm -> pixel (x, y) in the photo."""
    return int(round(ORIGIN[0] + x_mm * PX_PER_MM)), int(round(ORIGIN[1] + y_mm * PX_PER_MM))


def design_masks():
    """The coating drawing: where coating must go, and the keep-out zone (connector J1)."""
    coat = np.zeros((HEIGHT, WIDTH), np.uint8)
    cv2.rectangle(coat, P(3, 3), P(97, 67), 255, -1)
    cv2.rectangle(coat, P(0, 14), P(19, 56), 0, -1)                 # clearance around J1
    for hole in HOLES_MM:
        cv2.circle(coat, P(*hole), 6 * PX_PER_MM, 0, -1)             # clearance around mounting holes
    keepout = np.zeros_like(coat)
    cv2.rectangle(keepout, P(2.5, 18.5), P(14.5, 51.5), 255, -1)    # connector J1 itself
    return coat, keepout


def _chip(img, centre, size, pins_on_all_sides):
    (cx, cy), (w, h) = centre, size
    n = int(w / 0.8)                                                 # 0.8 mm pin pitch
    for i in range(n):                                               # pins top and bottom
        x = cx - w / 2 + (i + 0.5) * w / n
        cv2.rectangle(img, P(x - 0.2, cy - h / 2 - 1.2), P(x + 0.2, cy + h / 2 + 1.2), PIN, -1)
    if pins_on_all_sides:                                            # pins left and right
        m = int(h / 0.8)
        for i in range(m):
            y = cy - h / 2 + (i + 0.5) * h / m
            cv2.rectangle(img, P(cx - w / 2 - 1.2, y - 0.2), P(cx + w / 2 + 1.2, y + 0.2), PIN, -1)
    cv2.rectangle(img, P(cx - w / 2, cy - h / 2), P(cx + w / 2, cy + h / 2), IC_BODY, -1)


def _draw_board(img):
    """Draw the same board layout on every photo."""
    rng = np.random.default_rng(7)
    cv2.rectangle(img, P(0, 0), P(*BOARD_MM), SOLDER_MASK, -1)
    for _ in range(70):                                              # copper traces
        x, y = rng.uniform(16, 96), rng.uniform(4, 66)
        if rng.random() < 0.5:
            end = (float(np.clip(x + rng.uniform(-25, 25), 2, 98)), y)
        else:
            end = (x, float(np.clip(y + rng.uniform(-20, 20), 2, 68)))
        cv2.line(img, P(x, y), P(*end), COPPER, 3)
    _chip(img, (50, 35), (16, 16), pins_on_all_sides=True)            # U1
    for centre in [(78, 18), (78, 52), (32, 58), (32, 12)]:
        _chip(img, centre, (9, 5), pins_on_all_sides=False)
    for _ in range(45):                                              # resistors and capacitors
        x, y = rng.uniform(22, 92), rng.uniform(8, 62)
        if abs(x - 50) < 12 and abs(y - 35) < 12:
            continue                                                 # keep clear of U1
        w, h = (2.0, 1.25) if rng.random() < 0.5 else (1.25, 2.0)
        cv2.rectangle(img, P(x - w / 2, y - h / 2), P(x + w / 2, y + h / 2), PIN, -1)
        cv2.rectangle(img, P(x - w / 3, y - h / 3), P(x + w / 3, y + h / 3), PART_BODY, -1)
    for text, pos in [("U1", (44, 25)), ("U2", (74, 13)), ("U3", (74, 47)), ("J1", (5, 16)),
                      ("COAT-DEMO REV A", (35, 69))]:
        cv2.putText(img, text, P(*pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, SILKSCREEN, 2, cv2.LINE_AA)
    cv2.rectangle(img, P(3, 19), P(14, 51), CONNECTOR, -1)          # connector J1
    for row in range(10):
        for col in range(2):
            cv2.rectangle(img, P(5.5 + 4 * col, 21 + 3 * row), P(7.5 + 4 * col, 23 + 3 * row), PIN, -1)
    for hole in HOLES_MM:
        cv2.circle(img, P(*hole), 25, COPPER, -1)
        cv2.circle(img, P(*hole), 16, BACKGROUND, -1)


def _smooth_noise(rng, cell_px):
    """Smooth random pattern in [-1, 1] that changes over about `cell_px` pixels."""
    small = rng.uniform(-1, 1, (HEIGHT // cell_px + 2, WIDTH // cell_px + 2)).astype(np.float32)
    return np.clip(cv2.resize(small, (WIDTH, HEIGHT), interpolation=cv2.INTER_CUBIC), -1, 1)


def _soft_ellipse(centre_mm, axes_mm):
    blob = np.zeros((HEIGHT, WIDTH), np.float32)
    axes = (int(axes_mm[0] * PX_PER_MM), int(axes_mm[1] * PX_PER_MM))
    cv2.ellipse(blob, P(*centre_mm), axes, 0, 0, 360, 1.0, -1)
    return cv2.GaussianBlur(blob, (0, 0), 2)


def render_board(sample: Sample) -> np.ndarray:
    rng = np.random.default_rng(sample.seed)
    board = np.full((HEIGHT, WIDTH, 3), BACKGROUND, np.uint8)
    _draw_board(board)
    img = board.astype(np.float32)

    coat, _ = design_masks()
    if sample.defect == "shifted_pattern":
        coat = np.roll(coat, 25, axis=1)                             # spray program 2.5 mm off
    # Signed distance to the coating edge (+ inside, - outside) in px. The real edge wanders ±0.3 mm.
    edge = cv2.distanceTransform(coat, cv2.DIST_L2, 5) - cv2.distanceTransform(255 - coat, cv2.DIST_L2, 5)
    edge += 3.0 * _smooth_noise(rng, 60)
    alpha = np.clip(0.5 + edge / 3.0, 0, 1)                          # coating thins out over ~3 px
    if sample.defect == "missing_coating":
        alpha *= 1 - _soft_ellipse((65, 22), (4, 2.5))
    if sample.defect == "excess_spill":
        alpha = np.maximum(alpha, _soft_ellipse((18, 33), (2.5, 3.5)))
    if sample.defect == "keepout_violation":
        alpha = np.maximum(alpha, _soft_ellipse((8.5, 40), (2, 1.5)))
    ys, xs = np.nonzero(edge > 15)                                   # a few tiny bubbles (acceptable)
    for i in rng.choice(len(xs), 6, replace=False):
        cv2.circle(alpha, (int(xs[i]), int(ys[i])), int(rng.integers(2, 4)), 0.2, -1)
    thickness = 0.85 + 0.15 * _smooth_noise(rng, 80)
    a = alpha[..., None]
    img = img * (1 - 0.7 * a) + np.array(GLOW, np.float32) * (0.9 * thickness[..., None]) * a

    # Where the board sits in the fixture: rotate about the photo centre, then shift.
    m = cv2.getRotationMatrix2D((WIDTH / 2, HEIGHT / 2), sample.angle, 1.0)
    m[:, 2] += sample.shift
    img = cv2.warpAffine(img, m, (WIDTH, HEIGHT), flags=cv2.INTER_LINEAR, borderValue=BACKGROUND)
    # Lamp fall-off towards the corners, lens blur, sensor noise.
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
    r2 = ((xx - WIDTH / 2) ** 2 + (yy - HEIGHT / 2) ** 2) / ((WIDTH / 2) ** 2 + (HEIGHT / 2) ** 2)
    img *= (1 - 0.22 * r2).astype(np.float32)[..., None]
    img = cv2.GaussianBlur(img, (0, 0), 0.8)
    img += rng.normal(0, 4, img.shape).astype(np.float32)
    return np.clip(img, 0, 255).astype(np.uint8)


def make_samples(out_dir="samples") -> Path:
    out = Path(out_dir)
    for name, sample in SAMPLES.items():
        write_image(out / sample.folder / f"{name}.png", render_board(sample))
    write_image(out / "keepout_mask.png", design_masks()[1])
    truth = {name: sample._asdict() for name, sample in SAMPLES.items()}
    (out / "truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    folder = make_samples()
    print(f"made {len(SAMPLES)} photos in {folder}/approved and {folder}/test, plus {folder}/keepout_mask.png")
