"""Shared helpers used by the other modules: reading the settings file and reading and
writing image files."""
from __future__ import annotations  # lets type hints such as list[Path] work on older Python versions

import glob  # finds files that match a wildcard pattern such as photos/*.png
from pathlib import Path  # Path objects handle file and folder paths the same way on every system

import cv2  # OpenCV: decodes and encodes image files
import numpy as np  # NumPy: every image is a NumPy array of numbers
import yaml  # PyYAML: reads the settings file config.yaml

# File endings that count as photos when a whole folder is given.
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def load_config(path="config.yaml") -> dict:
    """Read the settings file.

    Args:
        path: the YAML settings file; by default config.yaml in the current folder.

    Returns:
        The settings as nested dictionaries, for example cfg["tolerance"]["border_mm"] -> 1.0.
    """
    # Accept either a plain text path or a Path object.
    path = Path(path)
    # A missing file would cause a confusing error later, so stop here with a clear message.
    if not path.exists():
        # Stop with this message.
        raise FileNotFoundError(f"{path} not found - run from the project folder or pass --config")
    # Open the file as text ("with" closes it again automatically) ...
    with open(path, encoding="utf-8") as f:
        # ... and turn the YAML text into Python dictionaries, lists and numbers.
        return yaml.safe_load(f)


def read_image(path) -> np.ndarray:
    """Read a photo from disk.

    Unlike cv2.imread, this also works with non-English characters in Windows folder names.

    Args:
        path: the image file (PNG, JPG, BMP, TIFF ...).

    Returns:
        The photo as an array of shape (height, width, 3): blue, green and red values 0-255 per pixel.
    """
    # Read the file's raw bytes into a NumPy array (this works with any folder name).
    data = np.fromfile(str(path), dtype=np.uint8)
    # Decode those bytes into a colour image; OpenCV stores colours in BGR order, not RGB.
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    # imdecode returns None when the bytes are not a picture it understands.
    if image is None:
        raise ValueError(f"{path} is not an image OpenCV can read")  # stop with this message
    # Hand the image back to the caller.
    return image


def read_mask(path) -> np.ndarray:
    """Read a black-and-white mask picture.

    Args:
        path: the mask file; white marks the area, black marks everything else.

    Returns:
        An array of shape (height, width): 255 where the picture is light, 0 where it is dark.
    """
    # Read the picture in colour, then convert it to one grey value per pixel.
    gray = cv2.cvtColor(read_image(path), cv2.COLOR_BGR2GRAY)
    # Light pixels (above 127) become 255, dark ones 0; uint8 is the 0-255 number type OpenCV expects.
    return np.where(gray > 127, 255, 0).astype(np.uint8)


def write_image(path, image) -> None:
    """Save an image, creating its folder if needed.

    Args:
        path: where to save it; the file ending (.png, .jpg ...) chooses the format.
        image: the image array to save.
    """
    # Accept either a plain text path or a Path object.
    path = Path(path)
    # Create the folder and any missing parent folders; no error if it already exists.
    path.parent.mkdir(parents=True, exist_ok=True)
    # Encode the image into file bytes, in the format given by the file ending (PNG if there is none).
    ok, data = cv2.imencode(path.suffix or ".png", image)
    # imencode returns ok = False if it could not encode the image.
    if not ok:
        raise ValueError(f"could not save {path}")  # stop with this message
    # Write the bytes to disk (this works with any folder name, like read_image).
    data.tofile(str(path))


def find_images(items) -> list[Path]:
    """Turn a list of files, folders and wildcards into a list of image files.

    Windows terminals pass *.png to Python without expanding it, so wildcards are expanded here.

    Args:
        items: file paths, folder paths and/or patterns such as photos/*.png.

    Returns:
        The image files as Path objects, sorted by name within each folder or pattern.
    """
    # Start with an empty list and add to it for each item.
    paths = []
    # Look at each item the user typed.
    for item in items:
        # Make a Path object, so we can ask whether it is a folder.
        p = Path(item)
        # A folder: take every file in it with a known image ending, sorted by name.
        if p.is_dir():
            paths += sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_TYPES)  # add them to the list
        # A wildcard pattern (it contains *, ? or [): let glob find the matching files.
        elif any(ch in str(item) for ch in "*?["):
            paths += sorted(Path(f) for f in glob.glob(str(item)))  # add the matches, sorted by name
        # Anything else is a single file: use it as it is.
        else:
            paths.append(p)  # add the single file
    # Hand the complete list back.
    return paths
