"""Step 8: build the approved ("golden") coating pattern from photos of approved boards.
Run:  python -m coating_inspector.golden --images samples/approved --keepout samples/keepout_mask.png --out golden"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .align import align_to_reference
from .common import find_images, load_config, read_image, read_mask, write_image
from .segment import find_borders, remove_small_blobs, segment_coating


@dataclass
class Golden:
    reference: np.ndarray           # photo of the first approved board; every photo is aligned to it
    mask: np.ndarray                # 255 = must be coated
    keepout: np.ndarray | None      # 255 = must never be coated
    info: dict


def read_keepout(path) -> np.ndarray:
    """Keep-out zones: a black/white mask, or a copy of reference.png with the zones painted pure magenta."""
    b, g, r = cv2.split(read_image(path))
    painted = (b > 230) & (r > 230) & (g < 40)
    if painted.any():
        return np.where(painted, 255, 0).astype(np.uint8)
    return read_mask(path)


def build_golden(image_paths, cfg, out_dir, keepout_path=None) -> Golden:
    seg = cfg["segmentation"]
    reference = read_image(image_paths[0])
    votes = (segment_coating(reference, seg) > 0).astype(np.float32)
    seen = np.ones_like(votes)
    for path in image_paths[1:]:
        a = align_to_reference(reference, read_image(path), cfg["alignment"])
        votes += (segment_coating(a.image, seg) > 0) & (a.valid > 0)
        seen += a.valid > 0
        print(f"  aligned {Path(path).name}: shifted {a.shift_px[0]:+.1f}, {a.shift_px[1]:+.1f} px, "
              f"rotated {a.rotation_deg:+.2f} deg")
    mask = np.where(votes > cfg["golden"]["min_agreement"] * seen, 255, 0).astype(np.uint8)
    mask = remove_small_blobs(mask, seg["min_area_px"])

    keepout = read_keepout(keepout_path) if keepout_path else None
    if keepout is not None and keepout.shape != mask.shape:
        raise ValueError("the keep-out mask must be the same size as the reference photo")
    if keepout is not None and np.any((mask > 0) & (keepout > 0)):
        print("  WARNING: the approved boards have coating inside a keep-out zone - check the keep-out mask")

    out = Path(out_dir)
    write_image(out / "reference.png", reference)
    write_image(out / "coating_mask.png", mask)
    preview = reference.copy()
    cv2.drawContours(preview, find_borders(mask), -1, (0, 255, 255), 2)          # yellow = approved outline
    if keepout is not None:
        write_image(out / "keepout_mask.png", keepout)
        cv2.drawContours(preview, find_borders(keepout), -1, (255, 0, 255), 2)   # magenta = keep-out
    write_image(out / "preview.png", preview)
    info = {"created": datetime.now().isoformat(timespec="seconds"),
            "images": [str(p) for p in image_paths],
            "keepout": str(keepout_path) if keepout_path else None,
            "segmentation": seg}
    (out / "golden.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return Golden(reference, mask, keepout, info)


def load_golden(folder) -> Golden:
    folder = Path(folder)
    if not (folder / "coating_mask.png").exists():
        raise FileNotFoundError(f"no golden pattern in {folder}/ - build it first with coating_inspector.golden")
    keepout = folder / "keepout_mask.png"
    info = folder / "golden.json"
    return Golden(read_image(folder / "reference.png"),
                  read_mask(folder / "coating_mask.png"),
                  read_mask(keepout) if keepout.exists() else None,
                  json.loads(info.read_text(encoding="utf-8")) if info.exists() else {})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the golden coating pattern from approved boards.")
    ap.add_argument("--images", nargs="+", required=True,
                    help="photos of approved boards (files, folders or wildcards); the first is the reference")
    ap.add_argument("--keepout", help="optional keep-out mask (white = must stay uncoated)")
    ap.add_argument("--out", default="golden")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    paths = find_images(args.images)
    if not paths:
        ap.error("no images found")
    print(f"building the golden pattern from {len(paths)} approved board(s), reference = {paths[0].name}")
    golden = build_golden(paths, cfg, args.out, args.keepout)
    ppm = cfg["tolerance"]["pixels_per_mm"]
    print(f"saved {args.out}/: coated area {cv2.countNonZero(golden.mask) / ppm**2:.0f} mm2, "
          f"{len(find_borders(golden.mask))} outline(s)")
    print(f"open {args.out}/preview.png and check that the yellow outline matches the coating drawing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
