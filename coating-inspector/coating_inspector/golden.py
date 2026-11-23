"""Step 8: build the approved ("golden") coating pattern from photos of approved boards.
Run:  python -m coating_inspector.golden --images samples/approved --keepout samples/keepout_mask.png --out golden"""
from __future__ import annotations  # lets the type hint "np.ndarray | None" work on older Python versions

import argparse  # reads the options typed after the command
import json  # writes golden.json (a record of how the pattern was made)
from dataclasses import dataclass  # @dataclass: a class that simply holds named values
from datetime import datetime  # the date and time recorded in golden.json
from pathlib import Path  # handles file and folder paths

import cv2  # OpenCV: drawing the preview, counting pixels
import numpy as np  # NumPy: arrays and per-pixel maths

from .align import align_to_reference  # lines each approved photo up with the first one
from .common import find_images, load_config, read_image, read_mask, write_image  # file helpers
from .segment import find_borders, remove_small_blobs, segment_coating  # coating detection


@dataclass  # turns the class below into a simple holder of the named values listed in it
class Golden:
    """The approved pattern: what every board is compared with."""
    reference: np.ndarray           # photo of the first approved board; every photo is aligned to it
    mask: np.ndarray                # 255 = must be coated
    keepout: np.ndarray | None      # 255 = must never be coated (None if no keep-out mask was given)
    info: dict                      # how and when the pattern was made (the contents of golden.json)


def read_keepout(path) -> np.ndarray:
    """Read the keep-out zones.

    Accepts either a black/white mask (white = keep-out) or a copy of reference.png with the
    zones painted pure magenta (red 255, green 0, blue 255).

    Args:
        path: the keep-out picture.

    Returns:
        A 0/255 mask: 255 inside the keep-out zones.
    """
    # Split the picture into its blue, green and red channels.
    b, g, r = cv2.split(read_image(path))
    # Pure magenta pixels: lots of blue and red, almost no green.
    painted = (b > 230) & (r > 230) & (g < 40)
    # If anything was painted magenta, those pixels are the zones.
    if painted.any():
        return np.where(painted, 255, 0).astype(np.uint8)  # painted pixels become 255, all others 0
    # Otherwise treat the picture as a black/white mask.
    return read_mask(path)


def build_golden(image_paths, cfg, out_dir, keepout_path=None) -> Golden:
    """Build the golden pattern from photos of approved boards and save it.

    Args:
        image_paths: photos of approved boards; the first one becomes the reference.
        cfg: all settings from config.yaml.
        out_dir: the folder to save the pattern in.
        keepout_path: optional keep-out picture.

    Returns:
        The finished Golden pattern.
    """
    # The segmentation settings are used for every photo.
    seg = cfg["segmentation"]
    # The first approved photo is the reference: all other photos are lined up with it.
    reference = read_image(image_paths[0])
    # Votes per pixel: 1 where the reference is coated, 0 elsewhere (as decimals, for the maths below).
    votes = (segment_coating(reference, seg) > 0).astype(np.float32)
    # How many photos really cover each pixel; the reference covers all of them.
    seen = np.ones_like(votes)
    # Every other approved photo adds its votes.
    for path in image_paths[1:]:
        # Line this photo up with the reference.
        a = align_to_reference(reference, read_image(path), cfg["alignment"])
        # Add 1 where this photo is coated and the pixel is real (not outside the warped photo).
        votes += (segment_coating(a.image, seg) > 0) & (a.valid > 0)
        # Add 1 where this photo has real pixels.
        seen += a.valid > 0
        # Show how this board was placed compared with the reference.
        print(f"  aligned {Path(path).name}: shifted {a.shift_px[0]:+.1f}, {a.shift_px[1]:+.1f} px, "
              f"rotated {a.rotation_deg:+.2f} deg")
    # "Must coat" where more than min_agreement (0.5 = most) of the photos are coated.
    mask = np.where(votes > cfg["golden"]["min_agreement"] * seen, 255, 0).astype(np.uint8)
    # Drop tiny specks from the result.
    mask = remove_small_blobs(mask, seg["min_area_px"])

    # Read the keep-out zones, if a file was given.
    keepout = read_keepout(keepout_path) if keepout_path else None
    # The keep-out picture must match the reference photo pixel for pixel.
    if keepout is not None and keepout.shape != mask.shape:
        raise ValueError("the keep-out mask must be the same size as the reference photo")  # stop with this message
    # Approved boards should never have coating inside a keep-out zone: warn if they do.
    if keepout is not None and np.any((mask > 0) & (keepout > 0)):
        # Warn, but carry on.
        print("  WARNING: the approved boards have coating inside a keep-out zone - check the keep-out mask")

    # Save the pattern into the output folder: the reference photo and the must-coat mask.
    out = Path(out_dir)
    write_image(out / "reference.png", reference)  # the photo every board is lined up with
    write_image(out / "coating_mask.png", mask)  # white = must be coated
    # A preview for a person to check: the reference with the approved outline in yellow ...
    preview = reference.copy()
    cv2.drawContours(preview, find_borders(mask), -1, (0, 255, 255), 2)  # yellow, 2 px thick
    # ... and, if there is one, the keep-out mask saved and its outline drawn in magenta.
    if keepout is not None:
        write_image(out / "keepout_mask.png", keepout)  # save the keep-out mask
        cv2.drawContours(preview, find_borders(keepout), -1, (255, 0, 255), 2)  # magenta, 2 px thick
    write_image(out / "preview.png", preview)  # save the preview picture
    # A record of how the pattern was made: when, from which photos and with which settings.
    info = {"created": datetime.now().isoformat(timespec="seconds"),
            "images": [str(p) for p in image_paths],
            "keepout": str(keepout_path) if keepout_path else None,
            "segmentation": seg}
    # Save that record as golden.json.
    (out / "golden.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    # Hand back the finished pattern.
    return Golden(reference, mask, keepout, info)


def load_golden(folder) -> Golden:
    """Load a golden pattern saved by build_golden.

    Args:
        folder: the folder build_golden wrote to.

    Returns:
        The Golden pattern.
    """
    # Accept a plain text path or a Path object.
    folder = Path(folder)
    # Without coating_mask.png there is no pattern: explain what to do.
    if not (folder / "coating_mask.png").exists():
        # Stop with this message.
        raise FileNotFoundError(f"no golden pattern in {folder}/ - build it first with coating_inspector.golden")
    # The two optional files.
    keepout = folder / "keepout_mask.png"  # the keep-out zones
    info = folder / "golden.json"  # the record of how the pattern was made
    # Read everything; a missing optional file becomes None or an empty record.
    return Golden(read_image(folder / "reference.png"),
                  read_mask(folder / "coating_mask.png"),
                  read_mask(keepout) if keepout.exists() else None,
                  json.loads(info.read_text(encoding="utf-8")) if info.exists() else {})


def main(argv=None) -> int:
    """Command line: python -m coating_inspector.golden --images ... [--keepout ...] [--out ...]

    Args:
        argv: the command-line words; None means "use the ones typed in the terminal".

    Returns:
        0, the exit code for success.
    """
    # Describe the options this command accepts.
    ap = argparse.ArgumentParser(description="Build the golden coating pattern from approved boards.")
    # --images: one or more approved photos, folders or wildcards.
    ap.add_argument("--images", nargs="+", required=True,
                    help="photos of approved boards (files, folders or wildcards); the first is the reference")
    # --keepout: the keep-out picture (optional).
    ap.add_argument("--keepout", help="optional keep-out mask (white = must stay uncoated)")
    ap.add_argument("--out", default="golden")  # --out: where to save the pattern
    ap.add_argument("--config", default="config.yaml")  # --config: the settings file
    # Read what the user typed.
    args = ap.parse_args(argv)
    # Load the settings.
    cfg = load_config(args.config)
    # Turn files, folders and wildcards into a list of photos.
    paths = find_images(args.images)
    # Nothing found: stop with an error message (argparse prints it and exits).
    if not paths:
        ap.error("no images found")  # argparse prints the message and stops the program
    # Say what is about to happen.
    print(f"building the golden pattern from {len(paths)} approved board(s), reference = {paths[0].name}")
    # Build and save the pattern.
    golden = build_golden(paths, cfg, args.out, args.keepout)
    # Report its coated area in mm2 and how many outlines it has.
    ppm = cfg["tolerance"]["pixels_per_mm"]
    # Print the area (pixel count divided by pixels-per-mm squared = mm2) and the number of outlines.
    print(f"saved {args.out}/: coated area {cv2.countNonZero(golden.mask) / ppm**2:.0f} mm2, "
          f"{len(find_borders(golden.mask))} outline(s)")
    # Remind the user to check the preview.
    print(f"open {args.out}/preview.png and check that the yellow outline matches the coating drawing")
    # Exit code 0 = success.
    return 0


# This block runs only when the file is started with  python -m coating_inspector.golden ...
if __name__ == "__main__":
    # Run main() and hand its return value to the operating system as the exit code.
    raise SystemExit(main())
