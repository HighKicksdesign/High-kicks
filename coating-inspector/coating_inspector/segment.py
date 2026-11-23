"""Step 5: find the glowing coating and trace its borders.
Quick check:  python -m coating_inspector.segment samples/approved/approved_1.png"""
from __future__ import annotations  # lets newer type hints work on older Python versions

import sys  # sys.argv holds the words typed after the command; sys.exit stops the program

import cv2  # OpenCV: colour conversion, colour thresholds, morphology, contours
import numpy as np  # NumPy: images as arrays

from .common import load_config, read_image, write_image  # our settings and image-file helpers


def disk(radius: int) -> np.ndarray:
    """Make a round "brush" for the morphology operations (open, close, erode, dilate).

    Args:
        radius: brush radius in pixels.

    Returns:
        A (2*radius+1) x (2*radius+1) array with 1s in a filled circle.
    """
    # OpenCV builds the circle-shaped brush (MORPH_ELLIPSE) in the requested size.
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def segment_coating(image: np.ndarray, seg: dict) -> np.ndarray:
    """Find the coated pixels in a photo.

    Args:
        image: the photo, BGR, shape (height, width, 3).
        seg: the "segmentation" section of config.yaml.

    Returns:
        A mask of shape (height, width): 255 where there is coating, 0 elsewhere.
    """
    # Smooth the sensor noise first, if blur_px is more than 1.
    if seg["blur_px"] > 1:
        # GaussianBlur needs an odd kernel size: 4 -> 5, 5 -> 5, 6 -> 7.
        k = seg["blur_px"] // 2 * 2 + 1
        # Average each pixel with its neighbours, weighted like a bell curve.
        image = cv2.GaussianBlur(image, (k, k), 0)
    # Convert BGR to HSV: hue (which colour), saturation (how strong), value (how bright).
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    # Keep the pixels whose H, S and V are all inside the range: 255 = inside (coating), 0 = outside.
    mask = cv2.inRange(hsv, np.array(seg["hsv_lower"], np.uint8), np.array(seg["hsv_upper"], np.uint8))
    # Opening (shrink, then grow back) removes specks smaller than the brush.
    if seg["open_px"] > 0:
        # Apply it with a round brush of radius open_px.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, disk(seg["open_px"]))
    # Closing (grow, then shrink back) fills pinholes and gaps smaller than the brush.
    if seg["close_px"] > 0:
        # Apply it with a round brush of radius close_px.
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, disk(seg["close_px"]))
    # Finally drop any remaining blobs that are too small to be coating.
    return remove_small_blobs(mask, seg["min_area_px"])


def remove_small_blobs(mask: np.ndarray, min_area_px: int) -> np.ndarray:
    """Delete separate white areas smaller than min_area_px.

    Args:
        mask: a 0/255 mask.
        min_area_px: the smallest area to keep, in pixels.

    Returns:
        A new 0/255 mask without the small areas.
    """
    # Give every separate white area its own number (label) and measure it; stats holds the areas.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    # For each label: True if its area is big enough.
    keep = stats[:, cv2.CC_STAT_AREA] >= min_area_px
    # Label 0 is the black background, which is never kept.
    keep[0] = False
    # Look up every pixel's label in "keep": kept areas become 255, everything else 0.
    return np.where(keep[labels], 255, 0).astype(np.uint8)


def find_borders(mask: np.ndarray) -> list:
    """Trace the outlines of the coated areas.

    Args:
        mask: a 0/255 mask.

    Returns:
        A list of contours (outer edges and the edges of holes); each is an array of (x, y) points.
    """
    # RETR_LIST returns every outline, including hole edges; CHAIN_APPROX_NONE keeps every edge pixel.
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    # Return a plain Python list (newer OpenCV versions return a tuple).
    return list(contours)


# This block runs only when the file is started with  python -m coating_inspector.segment <photo>
if __name__ == "__main__":
    # Exactly one photo must be given after the command.
    if len(sys.argv) != 2:
        sys.exit("usage: python -m coating_inspector.segment <photo>")  # otherwise show how to use it and stop
    # Read the settings ...
    cfg = load_config()
    # ... and the photo named after the command.
    image = read_image(sys.argv[1])
    # Find the coating ...
    mask = segment_coating(image, cfg["segmentation"])
    # ... and its borders.
    borders = find_borders(mask)
    # Draw on a copy, so the original photo stays unchanged.
    preview = image.copy()
    # Draw all the borders (-1 = every contour) in yellow (BGR 0, 255, 255), 2 px thick.
    cv2.drawContours(preview, borders, -1, (0, 255, 255), 2)
    # Save the mask and the preview, so you can look at them.
    write_image("out/mask.png", mask)  # the black/white coating mask
    write_image("out/borders.png", preview)  # the photo with the borders drawn on it
    # Pixels per mm, to convert the coated pixel count into mm2.
    ppm = cfg["tolerance"]["pixels_per_mm"]
    # Report the coated area and the number of outlines.
    print(f"coated area: {cv2.countNonZero(mask) / ppm**2:.0f} mm2 in {len(borders)} outline(s)")
    print("saved out/mask.png and out/borders.png")  # tell the user where the pictures are
