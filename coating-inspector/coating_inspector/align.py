"""Step 7: line up a board photo with the reference photo, so a board that sits a little shifted
or rotated in the fixture is not reported as a defect.
Quick check:  python -m coating_inspector.align samples/approved/approved_1.png samples/test/good_1.png"""
from __future__ import annotations  # lets newer type hints work on older Python versions

import math  # math.atan2 and math.degrees: work out the rotation angle
import sys  # sys.argv: the words typed after the command
from dataclasses import dataclass  # @dataclass: a class that simply holds named values

import cv2  # OpenCV: features (ORB), matching, RANSAC, warping
import numpy as np  # NumPy: matrices and arrays

from .common import load_config, read_image, write_image  # settings and image-file helpers


class AlignmentError(RuntimeError):
    """Raised when the photo cannot be matched to the reference photo."""


@dataclass  # turns the class below into a simple holder of the named values listed in it
class Alignment:
    """Everything align_to_reference finds out about one photo."""
    image: np.ndarray               # the photo, warped into the reference frame
    valid: np.ndarray               # 255 where the warped photo has real pixels
    matrix: np.ndarray              # 3x3 transform: photo pixel -> reference pixel
    inliers: int                    # matched features that agree with the transform
    shift_px: tuple                 # how far the board moved compared with the reference (x, y)...
    rotation_deg: float             # ...and how much it turned (counter-clockwise)


def _gray(image, scale):
    """Prepare a photo for finding features: grey, optionally shrunk, with faint detail boosted.

    Args:
        image: a BGR photo.
        scale: shrink factor (1.0 = keep the size).

    Returns:
        A grey (one-channel) image.
    """
    # Features need only brightness, not colour.
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Shrink large photos: features are found faster and just as reliably.
    if scale < 1:
        # Shrink by the factor; INTER_AREA gives the cleanest result.
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    # CLAHE raises the contrast region by region, which brings out faint parts and tracks in dark areas.
    return cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)


def estimate_transform(reference, image, al: dict):
    """Work out how to move the photo onto the reference photo.

    ORB finds small distinctive details (corners of parts, pins, text) in both photos, similar
    details are paired up, and RANSAC keeps only the pairs that agree on one movement.

    Args:
        reference: the reference photo (BGR).
        image: the photo to line up (BGR).
        al: the "alignment" section of config.yaml.

    Returns:
        (matrix, inliers): a 3x3 transform from photo pixels to reference pixels, and how many
        feature pairs agree with it.
    """
    # Shrink factors, so neither photo is bigger than work_px on its long side (never enlarged).
    s_ref = min(1.0, al["work_px"] / max(reference.shape[:2]))
    s_img = min(1.0, al["work_px"] / max(image.shape[:2]))  # the same for the photo
    # ORB finds up to max_features details per photo and describes each one as a short binary code.
    orb = cv2.ORB_create(nfeatures=al["max_features"])
    # Find the details (keypoints: their positions) and their codes (descriptors) in both photos.
    kp_ref, des_ref = orb.detectAndCompute(_gray(reference, s_ref), None)
    kp_img, des_img = orb.detectAndCompute(_gray(image, s_img), None)  # the same for the photo being lined up
    # No details at all usually means a black, blank or very blurred photo.
    if des_ref is None or des_img is None:
        raise AlignmentError("no features found - is the photo dark or out of focus?")  # stop with this explanation
    # For every detail in the photo, find the 2 most similar details in the reference
    # (Hamming distance = how many bits of the two codes differ).
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(des_img, des_ref, k=2)
    # Ratio test: keep a match only if it is clearly better than the second-best one.
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    # Too few good matches: probably a different board or a very poor photo.
    if len(good) < al["min_inliers"]:
        # Stop with this explanation.
        raise AlignmentError(f"only {len(good)} matching features - is it the same board type?")
    # Positions of the matched details: src in the photo, dst in the reference.
    src = np.float32([kp_img[m.queryIdx].pt for m in good])
    dst = np.float32([kp_ref[m.trainIdx].pt for m in good])  # where the same details are in the reference
    # Shift + rotation (+ a tiny scale change): right for a fixed camera above a flat board.
    if al["method"] == "similarity":
        # RANSAC tries many random small sets of pairs and keeps the movement that most pairs agree with
        # (within 3 px); "inl" marks which pairs agree.
        affine, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0,
                                                  maxIters=5000, confidence=0.999)
        # Turn the 2x3 result into a 3x3 matrix by adding the row [0, 0, 1] (None if RANSAC failed).
        matrix = None if affine is None else np.vstack([affine, [0, 0, 1]])
    # Perspective as well: for a camera that is not square to the board.
    elif al["method"] == "homography":
        # The same RANSAC idea, with a full 3x3 perspective transform.
        matrix, inl = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    # Any other method name is a typing mistake in config.yaml.
    else:
        raise ValueError(f"unknown alignment method '{al['method']}'")  # stop and show the wrong value
    # Count the agreeing pairs (inl holds a 1 for each of them).
    inliers = 0 if inl is None else int(inl.sum())
    # No result, or too few agreeing pairs: don't trust it.
    if matrix is None or inliers < al["min_inliers"]:
        # Stop with this explanation.
        raise AlignmentError(f"only {inliers} features agree - is it the same board type?")
    # The features were found on resized copies: convert the transform back to full-size pixels
    # (@ multiplies matrices: undo the reference shrink, apply the transform, apply the photo shrink).
    return np.diag([1 / s_ref, 1 / s_ref, 1]) @ matrix @ np.diag([s_img, s_img, 1]), inliers


def align_to_reference(reference, image, al: dict) -> Alignment:
    """Line up a photo with the reference photo.

    Args:
        reference: the reference photo (BGR).
        image: the photo to line up (BGR).
        al: the "alignment" section of config.yaml.

    Returns:
        An Alignment: the warped photo, which of its pixels are real, the transform and a description of it.
    """
    # Size of the reference photo: the warped photo gets exactly this size.
    h, w = reference.shape[:2]
    # With a precise fixture the photos already line up, so no movement is needed ...
    if al["method"] == "none":
        # ... but only if both photos have the same size.
        if image.shape != reference.shape:
            raise AlignmentError("photo size differs from the reference photo")  # stop with this explanation
        # np.eye(3) is the "do nothing" transform; there are no feature pairs to count.
        matrix, inliers = np.eye(3), 0
    # Otherwise work out the movement from the photos themselves.
    else:
        matrix, inliers = estimate_transform(reference, image, al)  # find the movement with ORB features and RANSAC
    # Move every pixel of the photo to its place in the reference frame.
    warped = cv2.warpPerspective(image, matrix, (w, h), flags=cv2.INTER_LINEAR)
    # Move an all-white picture the same way: white = pixels that really came from the photo.
    valid = cv2.warpPerspective(np.full(image.shape[:2], 255, np.uint8), matrix, (w, h), flags=cv2.INTER_NEAREST)
    # Shrink that area by 2 px, to ignore the blurry edge of the warped photo.
    valid = cv2.erode(valid, np.ones((5, 5), np.uint8))
    # Describe the movement: where did the centre of the reference end up in the photo?
    # The inverse matrix maps reference pixels to photo pixels.
    to_photo = np.linalg.inv(matrix)
    # The reference centre as (x, y, 1); the extra 1 lets a 3x3 matrix apply a shift too.
    centre = np.array([w / 2, h / 2, 1.0])
    # Where that point lands in the photo.
    moved = to_photo @ centre
    # Divide by the third number (needed for perspective transforms; it is 1 otherwise).
    moved /= moved[2]
    # The shift is how far the centre moved, in x and in y.
    shift = (float(moved[0] - centre[0]), float(moved[1] - centre[1]))
    # The rotation angle, from the matrix's top row, in degrees (counter-clockwise).
    rotation = math.degrees(math.atan2(to_photo[0, 1], to_photo[0, 0]))
    # Package everything up.
    return Alignment(warped, valid, matrix, inliers, shift, rotation)


def _detail(image):
    """Keep only fine detail (edges of parts and tracks), without slow brightness changes.

    Used for the check picture, so differences in coating thickness don't look like misalignment.

    Args:
        image: a BGR photo.

    Returns:
        A grey image where edges are bright and flat areas are dark.
    """
    # Grey values as decimals, so the subtraction below can go negative.
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    # Photo minus a blurred copy = only the fine detail; abs() makes dark and bright edges both positive.
    detail = np.abs(gray - cv2.GaussianBlur(gray, (0, 0), 3))
    # Stretch so the strongest 0.5 % of the detail becomes white (255), then convert to 8-bit.
    return np.clip(detail * (255 / max(np.percentile(detail, 99.5), 1)), 0, 255).astype(np.uint8)


# This block runs only when the file is started with  python -m coating_inspector.align <ref> <photo>
if __name__ == "__main__":
    # Exactly two photos must be given.
    if len(sys.argv) != 3:
        # Otherwise show how to use it and stop.
        sys.exit("usage: python -m coating_inspector.align <reference photo> <photo>")
    # Read the settings ...
    cfg = load_config()
    # ... and both photos.
    reference, image = read_image(sys.argv[1]), read_image(sys.argv[2])
    # Line up the second photo with the first.
    a = align_to_reference(reference, image, cfg["alignment"])
    # Report how many features agreed and how the board was placed.
    print(f"{a.inliers} matching features: board shifted {a.shift_px[0]:+.1f}, {a.shift_px[1]:+.1f} px "
          f"and rotated {a.rotation_deg:+.2f} deg compared with the reference")
    # Check picture: the aligned photo's detail in blue + green (= cyan), the reference's detail in red.
    # Detail present in both looks white; misaligned detail shows up as red/cyan doubles.
    write_image("out/align_check.png", cv2.merge([_detail(a.image), _detail(a.image), _detail(reference)]))
    # Tell the user where the check picture is.
    print("saved out/align_check.png (white parts = lined up, red/cyan doubled parts = not lined up)")
