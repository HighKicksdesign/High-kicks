"""Step 7: line up a board photo with the reference photo, so a board that sits a little shifted
or rotated in the fixture is not reported as a defect.
Quick check:  python -m coating_inspector.align samples/approved/approved_1.png samples/test/good_1.png"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass

import cv2
import numpy as np

from .common import load_config, read_image, write_image


class AlignmentError(RuntimeError):
    """The photo could not be matched to the reference photo."""


@dataclass
class Alignment:
    image: np.ndarray               # the photo, warped into the reference frame
    valid: np.ndarray               # 255 where the warped photo has real pixels
    matrix: np.ndarray              # 3x3 transform: photo pixel -> reference pixel
    inliers: int                    # matched features that agree with the transform
    shift_px: tuple                 # how far the board moved compared with the reference (x, y)...
    rotation_deg: float             # ...and how much it turned (counter-clockwise)


def _gray(image, scale):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if scale < 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)   # bring out faint detail


def estimate_transform(reference, image, al: dict):
    """Match ORB features between the photos and fit a transform with RANSAC."""
    s_ref = min(1.0, al["work_px"] / max(reference.shape[:2]))
    s_img = min(1.0, al["work_px"] / max(image.shape[:2]))
    orb = cv2.ORB_create(nfeatures=al["max_features"])
    kp_ref, des_ref = orb.detectAndCompute(_gray(reference, s_ref), None)
    kp_img, des_img = orb.detectAndCompute(_gray(image, s_img), None)
    if des_ref is None or des_img is None:
        raise AlignmentError("no features found - is the photo dark or out of focus?")
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(des_img, des_ref, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(good) < al["min_inliers"]:
        raise AlignmentError(f"only {len(good)} matching features - is it the same board type?")
    src = np.float32([kp_img[m.queryIdx].pt for m in good])
    dst = np.float32([kp_ref[m.trainIdx].pt for m in good])
    if al["method"] == "similarity":                 # shift + rotation: fixed camera, flat board
        affine, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0,
                                                  maxIters=5000, confidence=0.999)
        matrix = None if affine is None else np.vstack([affine, [0, 0, 1]])
    elif al["method"] == "homography":               # also perspective: camera not square to the board
        matrix, inl = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    else:
        raise ValueError(f"unknown alignment method '{al['method']}'")
    inliers = 0 if inl is None else int(inl.sum())
    if matrix is None or inliers < al["min_inliers"]:
        raise AlignmentError(f"only {inliers} features agree - is it the same board type?")
    # The features were found on resized copies: convert the transform back to full-size pixels.
    return np.diag([1 / s_ref, 1 / s_ref, 1]) @ matrix @ np.diag([s_img, s_img, 1]), inliers


def align_to_reference(reference, image, al: dict) -> Alignment:
    h, w = reference.shape[:2]
    if al["method"] == "none":                       # precise fixture: photos already line up
        if image.shape != reference.shape:
            raise AlignmentError("photo size differs from the reference photo")
        matrix, inliers = np.eye(3), 0
    else:
        matrix, inliers = estimate_transform(reference, image, al)
    warped = cv2.warpPerspective(image, matrix, (w, h), flags=cv2.INTER_LINEAR)
    valid = cv2.warpPerspective(np.full(image.shape[:2], 255, np.uint8), matrix, (w, h), flags=cv2.INTER_NEAREST)
    valid = cv2.erode(valid, np.ones((5, 5), np.uint8))            # ignore the blurry edge of the warp
    # Describe the movement: where did the centre of the reference end up in the photo?
    to_photo = np.linalg.inv(matrix)
    centre = np.array([w / 2, h / 2, 1.0])
    moved = to_photo @ centre
    moved /= moved[2]
    shift = (float(moved[0] - centre[0]), float(moved[1] - centre[1]))
    rotation = math.degrees(math.atan2(to_photo[0, 1], to_photo[0, 0]))
    return Alignment(warped, valid, matrix, inliers, shift, rotation)


def _detail(image):
    """Fine detail only (edges of parts and tracks), without slow brightness changes."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    detail = np.abs(gray - cv2.GaussianBlur(gray, (0, 0), 3))
    return np.clip(detail * (255 / max(np.percentile(detail, 99.5), 1)), 0, 255).astype(np.uint8)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python -m coating_inspector.align <reference photo> <photo>")
    cfg = load_config()
    reference, image = read_image(sys.argv[1]), read_image(sys.argv[2])
    a = align_to_reference(reference, image, cfg["alignment"])
    print(f"{a.inliers} matching features: board shifted {a.shift_px[0]:+.1f}, {a.shift_px[1]:+.1f} px "
          f"and rotated {a.rotation_deg:+.2f} deg compared with the reference")
    # Check picture: parts and tracks white where the photos line up, red/cyan doubles where they do not.
    write_image("out/align_check.png", cv2.merge([_detail(a.image), _detail(a.image), _detail(reference)]))
    print("saved out/align_check.png (white parts = lined up, red/cyan doubled parts = not lined up)")
