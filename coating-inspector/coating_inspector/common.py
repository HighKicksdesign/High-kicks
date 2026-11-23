"""Shared helpers: settings and image files."""
from __future__ import annotations

import glob
from pathlib import Path

import cv2
import numpy as np
import yaml

IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def load_config(path="config.yaml") -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - run from the project folder or pass --config")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_image(path) -> np.ndarray:
    """Read a photo as BGR. Unlike cv2.imread, this also works with non-English folder names on Windows."""
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"{path} is not an image OpenCV can read")
    return image


def read_mask(path) -> np.ndarray:
    """Read a black/white mask: 255 where the picture is light, 0 where it is dark."""
    gray = cv2.cvtColor(read_image(path), cv2.COLOR_BGR2GRAY)
    return np.where(gray > 127, 255, 0).astype(np.uint8)


def write_image(path, image) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, data = cv2.imencode(path.suffix or ".png", image)
    if not ok:
        raise ValueError(f"could not save {path}")
    data.tofile(str(path))


def find_images(items) -> list[Path]:
    """Expand files, folders and wildcards (Windows terminals do not expand *.png themselves)."""
    paths = []
    for item in items:
        p = Path(item)
        if p.is_dir():
            paths += sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_TYPES)
        elif any(ch in str(item) for ch in "*?["):
            paths += sorted(Path(f) for f in glob.glob(str(item)))
        else:
            paths.append(p)
    return paths
