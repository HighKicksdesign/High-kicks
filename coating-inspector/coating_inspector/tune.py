"""Step 6: tune the coating colour range on YOUR photos with sliders.
Run:  python -m coating_inspector.tune --image samples/approved/approved_1.png
Click the photo to print a pixel's HSV value (and its distance from the previous click, for calibration).
Keys:  s = save the sliders to config.yaml,  q or Esc = quit."""
from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

import cv2
import numpy as np

from .common import load_config, read_image
from .segment import find_borders, segment_coating

SLIDERS_WINDOW = "coating tuner - sliders"
PHOTO_WINDOW = "coating tuner - photo"
SLIDERS = [  # (label, config key, list index or None, maximum)
    ("H min", "hsv_lower", 0, 179), ("H max", "hsv_upper", 0, 179),
    ("S min", "hsv_lower", 1, 255), ("S max", "hsv_upper", 1, 255),
    ("V min", "hsv_lower", 2, 255), ("V max", "hsv_upper", 2, 255),
    ("blur", "blur_px", None, 15), ("open", "open_px", None, 10), ("close", "close_px", None, 15),
]


def save_to_config(path, seg: dict) -> None:
    """Write the slider values into config.yaml, keeping its comments."""
    text = Path(path).read_text(encoding="utf-8")
    for key in ("hsv_lower", "hsv_upper"):
        values = [int(v) for v in seg[key]]
        text = re.sub(rf"^(\s*{key}:\s*)\[[^\]]*\]", rf"\g<1>{values}", text, flags=re.M)
    for key in ("blur_px", "open_px", "close_px"):
        text = re.sub(rf"^(\s*{key}:\s*)\d+", rf"\g<1>{int(seg[key])}", text, flags=re.M)
    Path(path).write_text(text, encoding="utf-8")


def preview(image, mask, scale):
    view = image.copy()
    view[mask > 0] = (0.5 * view[mask > 0] + (0, 128, 0)).astype(np.uint8)    # tint coating green
    cv2.drawContours(view, find_borders(mask), -1, (0, 255, 255), max(1, round(1.5 / scale)))
    return cv2.resize(view, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def help_picture():
    picture = np.full((64, 520, 3), 45, np.uint8)
    for row, text in enumerate(["Move the sliders until only the coating is green.",
                                "Click photo = print HSV    s = save to config    q = quit"]):
        cv2.putText(picture, text, (10, 24 + 28 * row), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1,
                    cv2.LINE_AA)
    return picture


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Tune the coating colour range with sliders.")
    ap.add_argument("--image", required=True, help="a photo of a coated board")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args(argv)
    seg = load_config(args.config)["segmentation"]
    image = read_image(args.image)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    scale = min(1.0, 1000 / image.shape[1], 700 / image.shape[0])  # fit the photo on the screen

    # Sliders and photo get separate windows, so the sliders never squeeze the photo.
    cv2.namedWindow(SLIDERS_WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.namedWindow(PHOTO_WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.moveWindow(SLIDERS_WINDOW, 0, 0)
    cv2.moveWindow(PHOTO_WINDOW, 540, 0)
    for label, key, i, top in SLIDERS:
        value = seg[key][i] if i is not None else seg[key]
        cv2.createTrackbar(label, SLIDERS_WINDOW, int(value), top, lambda _: None)
    cv2.imshow(SLIDERS_WINDOW, help_picture())

    last_click = []

    def on_click(event, x, y, flags, param):
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        px = min(int(x / scale), image.shape[1] - 1)
        py = min(int(y / scale), image.shape[0] - 1)
        h, s, v = (int(c) for c in hsv[py, px])
        message = f"pixel ({px}, {py})  HSV = ({h}, {s}, {v})"
        if last_click:
            message += f"   distance from previous click: {math.dist(last_click, (px, py)):.1f} px"
        last_click[:] = [px, py]
        print(message, flush=True)

    cv2.setMouseCallback(PHOTO_WINDOW, on_click)
    shown = None
    while True:
        for label, key, i, _ in SLIDERS:
            value = cv2.getTrackbarPos(label, SLIDERS_WINDOW)
            if i is None:
                seg[key] = value
            else:
                seg[key][i] = value
        state = (tuple(seg["hsv_lower"]), tuple(seg["hsv_upper"]), seg["blur_px"], seg["open_px"], seg["close_px"])
        if state != shown:                                       # only redraw when a slider moved
            cv2.imshow(PHOTO_WINDOW, preview(image, segment_coating(image, seg), scale))
            shown = state
        key = cv2.waitKey(30) & 0xFF
        if key == ord("s"):
            save_to_config(args.config, seg)
            print(f"saved to {args.config}: hsv_lower={seg['hsv_lower']} hsv_upper={seg['hsv_upper']} "
                  f"blur_px={seg['blur_px']} open_px={seg['open_px']} close_px={seg['close_px']}", flush=True)
        closed = any(cv2.getWindowProperty(w, cv2.WND_PROP_VISIBLE) < 1 for w in (SLIDERS_WINDOW, PHOTO_WINDOW))
        if key in (ord("q"), 27) or closed:
            break
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
