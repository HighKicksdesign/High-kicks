"""Step 4: make synthetic photos of a coated board under blue/UV light, so every step can be
run and checked before you have real photos.   Run:  python -m coating_inspector.synthetic

The photos are drawn, not photographed: the board layout is drawn, the glowing coating is
blended on top, the board is shifted and rotated as if placed in a fixture, and lamp
fall-off, lens blur and sensor noise are added."""
from __future__ import annotations  # lets the type hint "str | None" work on older Python versions

import json  # writes truth.json (the exact placement of each sample board)
from pathlib import Path  # handles file and folder paths
from typing import NamedTuple  # NamedTuple: a small record type with named fields

import cv2  # OpenCV: drawing shapes, blurring, warping
import numpy as np  # NumPy: images as arrays, random numbers

from .common import write_image  # our helper that saves an image and creates its folder

PX_PER_MM = 10                      # drawing scale: 10 pixels per millimetre (same as config.yaml)
WIDTH, HEIGHT = 1200, 900           # photo size in pixels
BOARD_MM = (100, 70)                # board size in mm (width, height)
ORIGIN = (100, 100)                 # where the board's top-left corner sits in the photo, in pixels
HOLES_MM = [(4, 4), (96, 4), (4, 66), (96, 66)]  # centres of the four mounting holes, in mm

# Colours as a camera sees them under UV/blue light without a filter. OpenCV order is (blue, green, red).
BACKGROUND = (12, 6, 10)            # almost black: the space around the board
SOLDER_MASK = (75, 22, 48)          # dark violet: bare board under UV light
COPPER = (140, 55, 105)             # brighter violet: copper reflects the light
IC_BODY = (28, 16, 22)              # near black: plastic chip packages
PIN = (200, 140, 185)               # pale violet: shiny pins and solder pads
PART_BODY = (60, 70, 90)            # dull brown-grey: resistor and capacitor bodies
SILKSCREEN = (190, 172, 176)        # whitish: printed labels glow a little but are not saturated blue
CONNECTOR = (150, 122, 136)         # grey-violet: the plastic housing of connector J1
GLOW = (255, 205, 110)              # light blue: the coating's UV tracer glowing


class Sample(NamedTuple):
    """How one sample photo is made."""
    folder: str                     # sub-folder of samples/: "approved" or "test"
    seed: int                       # random-number seed, so the same photo is made every time
    angle: float                    # rotation in the fixture, degrees counter-clockwise
    shift: tuple                    # shift in the fixture, (x, y) in pixels
    defect: str | None              # which defect to draw, or None for a good board


# The nine sample photos: name -> how to make it.
SAMPLES = {
    "approved_1": Sample("approved", 1, 0.0, (0, 0), None),     # the reference: placed exactly
    "approved_2": Sample("approved", 2, 0.8, (12, -7), None),   # approved, slightly shifted and turned
    "approved_3": Sample("approved", 3, -0.6, (-9, 10), None),  # approved, shifted and turned the other way
    "good_1": Sample("test", 4, 1.3, (18, 9), None),            # good board: should PASS
    "good_2": Sample("test", 5, -1.1, (-15, -12), None),        # good board: should PASS
    "missing_coating": Sample("test", 6, 0.5, (8, 14), "missing_coating"),        # a patch without coating
    "excess_spill": Sample("test", 7, -0.9, (-11, 6), "excess_spill"),            # coating runs toward J1
    "keepout_violation": Sample("test", 8, 1.0, (14, -10), "keepout_violation"),  # coating on connector J1
    "shifted_pattern": Sample("test", 9, -0.4, (6, 8), "shifted_pattern"),        # whole pattern 2.5 mm off
}


def P(x_mm, y_mm):
    """Convert a position on the board in mm into a pixel position in the photo.

    Args:
        x_mm, y_mm: distance from the board's top-left corner, in mm.

    Returns:
        (x, y) in whole pixels, which is what OpenCV's drawing functions need.
    """
    # Scale mm to pixels, add the board's offset in the photo, and round to whole pixels.
    return int(round(ORIGIN[0] + x_mm * PX_PER_MM)), int(round(ORIGIN[1] + y_mm * PX_PER_MM))


def design_masks():
    """Draw the coating drawing: where coating must go, and the keep-out zone (connector J1).

    Returns:
        (coat, keepout): two masks the size of the photo, 255 inside the area and 0 outside.
    """
    # Start with an all-black (0) picture: nothing is coated yet.
    coat = np.zeros((HEIGHT, WIDTH), np.uint8)
    # Coat the whole board except a 3 mm margin along every edge (thickness -1 = filled).
    cv2.rectangle(coat, P(3, 3), P(97, 67), 255, -1)
    # Leave a clear area around connector J1 by painting it back to 0.
    cv2.rectangle(coat, P(0, 14), P(19, 56), 0, -1)
    # Leave a clear circle of radius 6 mm around each mounting hole.
    for hole in HOLES_MM:
        cv2.circle(coat, P(*hole), 6 * PX_PER_MM, 0, -1)  # a filled black circle
    # The keep-out mask starts black too, the same size as the coating mask.
    keepout = np.zeros_like(coat)
    # Mark connector J1 itself (plus 0.5 mm) as a zone that must never be coated.
    cv2.rectangle(keepout, P(2.5, 18.5), P(14.5, 51.5), 255, -1)
    # Return both masks.
    return coat, keepout


def _chip(img, centre, size, pins_on_all_sides):
    """Draw a chip: a black body with pins sticking out.

    Args:
        img: the picture to draw on (changed in place).
        centre: (x, y) of the chip's centre, in mm.
        size: (width, height) of the chip body, in mm.
        pins_on_all_sides: True for pins on all four sides, False for top and bottom only.
    """
    # Unpack the centre and the size into four separate numbers.
    (cx, cy), (w, h) = centre, size
    # How many pins fit along the width at a 0.8 mm pitch.
    n = int(w / 0.8)
    # Draw the pins along the top and bottom edges.
    for i in range(n):
        # x position of pin i, spaced evenly across the chip's width.
        x = cx - w / 2 + (i + 0.5) * w / n
        # A thin bar from above the chip to below it; the body drawn last hides its middle,
        # so only the two ends stay visible as pins.
        cv2.rectangle(img, P(x - 0.2, cy - h / 2 - 1.2), P(x + 0.2, cy + h / 2 + 1.2), PIN, -1)
    # Draw pins on the left and right edges too, if asked.
    if pins_on_all_sides:
        # How many pins fit along the height.
        m = int(h / 0.8)
        # Same trick as above, with horizontal bars.
        for i in range(m):
            # y position of pin i, spaced evenly down the chip's height.
            y = cy - h / 2 + (i + 0.5) * h / m
            # A thin horizontal bar across the chip; its two ends become the pins.
            cv2.rectangle(img, P(cx - w / 2 - 1.2, y - 0.2), P(cx + w / 2 + 1.2, y + 0.2), PIN, -1)
    # Finally the black body on top, which hides the middle of every bar.
    cv2.rectangle(img, P(cx - w / 2, cy - h / 2), P(cx + w / 2, cy + h / 2), IC_BODY, -1)


def _draw_board(img):
    """Draw the board layout, the same on every photo.

    Args:
        img: the picture to draw on (changed in place).
    """
    # A fixed seed makes the "random" traces and parts identical on every photo.
    rng = np.random.default_rng(7)
    # The board itself: a filled dark-violet rectangle.
    cv2.rectangle(img, P(0, 0), P(*BOARD_MM), SOLDER_MASK, -1)
    # 70 copper traces.
    for _ in range(70):
        # A random starting point on the board, in mm.
        x, y = rng.uniform(16, 96), rng.uniform(4, 66)
        # Half of the traces run sideways ...
        if rng.random() < 0.5:
            # ... up to 25 mm left or right; np.clip keeps the end on the board.
            end = (float(np.clip(x + rng.uniform(-25, 25), 2, 98)), y)
        # ... and the other half run up or down.
        else:
            # ... up to 20 mm, also kept on the board.
            end = (x, float(np.clip(y + rng.uniform(-20, 20), 2, 68)))
        # Draw the trace 3 pixels (0.3 mm) wide.
        cv2.line(img, P(x, y), P(*end), COPPER, 3)
    # The big chip U1 in the middle, with pins on all four sides.
    _chip(img, (50, 35), (16, 16), pins_on_all_sides=True)
    # Four smaller chips with pins on two sides.
    for centre in [(78, 18), (78, 52), (32, 58), (32, 12)]:
        _chip(img, centre, (9, 5), pins_on_all_sides=False)  # 9 x 5 mm, pins on two sides
    # 45 attempts at placing small resistors and capacitors.
    for _ in range(45):
        # A random position, in mm.
        x, y = rng.uniform(22, 92), rng.uniform(8, 62)
        # Skip positions on top of U1.
        if abs(x - 50) < 12 and abs(y - 35) < 12:
            continue  # skip to the next attempt
        # Half lie horizontally (2 x 1.25 mm), half vertically (1.25 x 2 mm).
        w, h = (2.0, 1.25) if rng.random() < 0.5 else (1.25, 2.0)
        # The solder pads: a shiny rectangle the full size of the part ...
        cv2.rectangle(img, P(x - w / 2, y - h / 2), P(x + w / 2, y + h / 2), PIN, -1)
        # ... with the smaller body on top, so the pads show at both ends.
        cv2.rectangle(img, P(x - w / 3, y - h / 3), P(x + w / 3, y + h / 3), PART_BODY, -1)
    # Printed labels (silkscreen): each text and its position in mm.
    for text, pos in [("U1", (44, 25)), ("U2", (74, 13)), ("U3", (74, 47)), ("J1", (5, 16)),
                      ("COAT-DEMO REV A", (35, 69))]:
        # Draw the text; LINE_AA smooths its edges.
        cv2.putText(img, text, P(*pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, SILKSCREEN, 2, cv2.LINE_AA)
    # Connector J1's plastic housing on the left.
    cv2.rectangle(img, P(3, 19), P(14, 51), CONNECTOR, -1)
    # Its 10 rows ...
    for row in range(10):
        # ... of 2 pins.
        for col in range(2):
            # One 2 x 2 mm pin, on a grid 4 mm apart sideways and 3 mm apart downwards.
            cv2.rectangle(img, P(5.5 + 4 * col, 21 + 3 * row), P(7.5 + 4 * col, 23 + 3 * row), PIN, -1)
    # The four mounting holes.
    for hole in HOLES_MM:
        # A copper ring of radius 25 px (2.5 mm) ...
        cv2.circle(img, P(*hole), 25, COPPER, -1)
        # ... with the drilled hole (radius 1.6 mm) showing the dark background.
        cv2.circle(img, P(*hole), 16, BACKGROUND, -1)


def _smooth_noise(rng, cell_px):
    """Make a smooth random pattern, used for the wandering coating edge and its thickness.

    Args:
        rng: the random-number generator.
        cell_px: roughly how many pixels it takes for the pattern to change.

    Returns:
        A decimal array the size of the photo with values from -1 to 1.
    """
    # A small grid of random numbers between -1 and 1 (one per cell, plus a spare row and column).
    small = rng.uniform(-1, 1, (HEIGHT // cell_px + 2, WIDTH // cell_px + 2)).astype(np.float32)
    # Enlarge it to the photo size with smooth (cubic) interpolation, and keep the values in -1..1.
    return np.clip(cv2.resize(small, (WIDTH, HEIGHT), interpolation=cv2.INTER_CUBIC), -1, 1)


def _soft_ellipse(centre_mm, axes_mm):
    """Make an ellipse with a blurry edge, used to draw the defects.

    Args:
        centre_mm: (x, y) centre, in mm.
        axes_mm: (half-width, half-height), in mm.

    Returns:
        A decimal array the size of the photo: 1 inside the ellipse, 0 outside, soft in between.
    """
    # Start with an all-zero picture of decimal numbers.
    blob = np.zeros((HEIGHT, WIDTH), np.float32)
    # Convert the ellipse's half-width and half-height from mm to pixels.
    axes = (int(axes_mm[0] * PX_PER_MM), int(axes_mm[1] * PX_PER_MM))
    # Draw a filled ellipse with value 1.0 (not rotated, from 0 to 360 degrees, thickness -1 = filled).
    cv2.ellipse(blob, P(*centre_mm), axes, 0, 0, 360, 1.0, -1)
    # Blur it so the edge fades out over a few pixels, like real coating.
    return cv2.GaussianBlur(blob, (0, 0), 2)


def render_board(sample: Sample) -> np.ndarray:
    """Make one synthetic photo.

    Args:
        sample: how to make it (random seed, placement, defect).

    Returns:
        The photo: an array of shape (900, 1200, 3) with BGR values 0-255.
    """
    # Each sample has its own seed, so its edge, bubbles and noise differ but are repeatable.
    rng = np.random.default_rng(sample.seed)
    # An 8-bit colour picture filled with the background colour.
    board = np.full((HEIGHT, WIDTH, 3), BACKGROUND, np.uint8)
    # Draw the board layout onto it.
    _draw_board(board)
    # Switch to decimal numbers, so the blending maths below doesn't round off.
    img = board.astype(np.float32)

    # Get the coating drawing (the keep-out mask is not needed here, hence the _).
    coat, _ = design_masks()
    # For the shifted-pattern defect, move the whole coating 25 px (2.5 mm) to the right.
    if sample.defect == "shifted_pattern":
        coat = np.roll(coat, 25, axis=1)  # axis=1 = sideways
    # Signed distance to the coating edge in px: positive inside the coating, negative outside.
    # (distanceTransform gives each pixel's distance to the nearest black pixel.)
    edge = cv2.distanceTransform(coat, cv2.DIST_L2, 5) - cv2.distanceTransform(255 - coat, cv2.DIST_L2, 5)
    # Make the edge wander by up to 3 px (0.3 mm) either way, like a real spray edge.
    edge += 3.0 * _smooth_noise(rng, 60)
    # Coating strength from 0 to 1: 1 well inside, 0 outside, fading over about 3 px at the edge.
    alpha = np.clip(0.5 + edge / 3.0, 0, 1)
    # Missing-coating defect: remove the coating inside an 8 x 5 mm ellipse.
    if sample.defect == "missing_coating":
        alpha *= 1 - _soft_ellipse((65, 22), (4, 2.5))  # 1 - ellipse is 0 inside it, so the coating there goes
    # Excess defect: add a blob of coating that runs from the edge toward connector J1.
    if sample.defect == "excess_spill":
        alpha = np.maximum(alpha, _soft_ellipse((18, 33), (2.5, 3.5)))  # keep the larger value: coating plus blob
    # Keep-out defect: add a drop of coating on connector J1.
    if sample.defect == "keepout_violation":
        alpha = np.maximum(alpha, _soft_ellipse((8.5, 40), (2, 1.5)))  # keep the larger value: coating plus drop
    # Find all pixels more than 15 px inside the coating ...
    ys, xs = np.nonzero(edge > 15)
    # ... and put a tiny thin spot (a bubble) at 6 of them, chosen at random. They are too small to fail.
    for i in rng.choice(len(xs), 6, replace=False):
        # A filled circle of radius 2-3 px where the coating is only 20 % strong.
        cv2.circle(alpha, (int(xs[i]), int(ys[i])), int(rng.integers(2, 4)), 0.2, -1)
    # The coating thickness varies smoothly between 0.7 and 1.0.
    thickness = 0.85 + 0.15 * _smooth_noise(rng, 80)
    # Add a third axis, so alpha can multiply all three colour channels at once.
    a = alpha[..., None]
    # Blend: where coated, the board shows through darker (the coating is clear) and the blue glow is added.
    img = img * (1 - 0.7 * a) + np.array(GLOW, np.float32) * (0.9 * thickness[..., None]) * a

    # Where the board sits in the fixture: a rotation about the photo centre ...
    m = cv2.getRotationMatrix2D((WIDTH / 2, HEIGHT / 2), sample.angle, 1.0)
    # ... plus a shift, added to the matrix's last column.
    m[:, 2] += sample.shift
    # Move the picture accordingly; uncovered corners get the background colour.
    img = cv2.warpAffine(img, m, (WIDTH, HEIGHT), flags=cv2.INTER_LINEAR, borderValue=BACKGROUND)
    # Coordinate grids: yy holds each pixel's row number, xx its column number.
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
    # Squared distance from the photo centre, scaled to 0 at the centre and 1 in the corners.
    r2 = ((xx - WIDTH / 2) ** 2 + (yy - HEIGHT / 2) ** 2) / ((WIDTH / 2) ** 2 + (HEIGHT / 2) ** 2)
    # Lamp fall-off: up to 22 % darker in the corners.
    img *= (1 - 0.22 * r2).astype(np.float32)[..., None]
    # Lens blur: a slight Gaussian blur.
    img = cv2.GaussianBlur(img, (0, 0), 0.8)
    # Sensor noise: random variation with a standard deviation of 4 brightness levels.
    img += rng.normal(0, 4, img.shape).astype(np.float32)
    # Keep the values within 0..255 and convert back to the 8-bit image type.
    return np.clip(img, 0, 255).astype(np.uint8)


def make_samples(out_dir="samples") -> Path:
    """Make all sample photos, the keep-out mask and truth.json.

    Args:
        out_dir: the folder to write them to.

    Returns:
        The folder, as a Path.
    """
    # Accept a plain text path or a Path object.
    out = Path(out_dir)
    # Make and save each of the nine photos in its sub-folder (approved/ or test/).
    for name, sample in SAMPLES.items():
        write_image(out / sample.folder / f"{name}.png", render_board(sample))  # for example samples/test/good_1.png
    # Save the keep-out mask (the second mask returned by design_masks).
    write_image(out / "keepout_mask.png", design_masks()[1])
    # Record each photo's settings (placement, defect), so the alignment can be checked against them.
    truth = {name: sample._asdict() for name, sample in SAMPLES.items()}
    # Write that record as readable JSON text.
    (out / "truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    # Tell the caller where everything went.
    return out


# This block runs only when the file is started with  python -m coating_inspector.synthetic
if __name__ == "__main__":
    # Make the samples in the default folder, samples/.
    folder = make_samples()
    # Report what was made.
    print(f"made {len(SAMPLES)} photos in {folder}/approved and {folder}/test, plus {folder}/keepout_mask.png")
