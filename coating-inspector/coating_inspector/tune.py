"""Step 6: tune the coating colour range on YOUR photos with sliders.
Run:  python -m coating_inspector.tune --image samples/approved/approved_1.png
Click the photo to print a pixel's HSV value (and its distance from the previous click, for calibration).
Keys:  s = save the sliders to config.yaml,  q or Esc = quit."""
from __future__ import annotations  # lets newer type hints work on older Python versions

import argparse  # reads the options typed after the command (--image, --config)
import math  # math.dist: the distance between two points
import re  # regular expressions: find and replace the values inside config.yaml
from pathlib import Path  # handles file paths

import cv2  # OpenCV: windows, sliders, mouse clicks, drawing
import numpy as np  # NumPy: images as arrays

from .common import load_config, read_image  # settings and image-file helpers
from .segment import find_borders, segment_coating  # the same coating detection the inspection uses

SLIDERS_WINDOW = "coating tuner - sliders"  # title of the window with the sliders
PHOTO_WINDOW = "coating tuner - photo"  # title of the window with the photo
SLIDERS = [  # (label, config key, list index or None, maximum)
    ("H min", "hsv_lower", 0, 179), ("H max", "hsv_upper", 0, 179),  # hue limits (OpenCV hue runs 0-179)
    ("S min", "hsv_lower", 1, 255), ("S max", "hsv_upper", 1, 255),  # saturation limits
    ("V min", "hsv_lower", 2, 255), ("V max", "hsv_upper", 2, 255),  # brightness limits
    ("blur", "blur_px", None, 15), ("open", "open_px", None, 10), ("close", "close_px", None, 15),  # clean-up
]


def save_to_config(path, seg: dict) -> None:
    """Write the slider values into config.yaml, keeping all its comments.

    Only the numbers are replaced, so the file keeps its layout and explanations.

    Args:
        path: the settings file to update.
        seg: the segmentation settings with the new values.
    """
    # Read the whole settings file as text.
    text = Path(path).read_text(encoding="utf-8")
    # The two colour limits are lists such as [85, 80, 110].
    for key in ("hsv_lower", "hsv_upper"):
        # Make sure they are plain whole numbers.
        values = [int(v) for v in seg[key]]
        # Replace the [...] after "hsv_lower:" with the new list; \g<1> keeps the "hsv_lower: " part.
        text = re.sub(rf"^(\s*{key}:\s*)\[[^\]]*\]", rf"\g<1>{values}", text, flags=re.M)
    # The three clean-up settings are single numbers.
    for key in ("blur_px", "open_px", "close_px"):
        # Replace the number after "blur_px:" (and so on) with the new value.
        text = re.sub(rf"^(\s*{key}:\s*)\d+", rf"\g<1>{int(seg[key])}", text, flags=re.M)
    # Save the updated text back to the file.
    Path(path).write_text(text, encoding="utf-8")


def preview(image, mask, scale):
    """Make the picture shown in the photo window.

    Args:
        image: the full-size photo.
        mask: the coating found in it (0/255).
        scale: how much to shrink the picture to fit on the screen (1.0 = full size).

    Returns:
        The shrunken photo with the coating tinted green and its border drawn in yellow.
    """
    # Work on a copy, so the original photo stays unchanged.
    view = image.copy()
    # Coated pixels become half their own colour plus some green, so the coating looks tinted green.
    view[mask > 0] = (0.5 * view[mask > 0] + (0, 128, 0)).astype(np.uint8)
    # Draw the coating border in yellow, thick enough to stay visible after shrinking.
    cv2.drawContours(view, find_borders(mask), -1, (0, 255, 255), max(1, round(1.5 / scale)))
    # Shrink the picture to fit the screen; INTER_AREA gives the cleanest result when shrinking.
    return cv2.resize(view, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def help_picture():
    """Make the small instructions picture shown in the sliders window.

    Returns:
        A dark-grey image with two lines of white text.
    """
    # A 64 x 520 pixel dark-grey picture.
    picture = np.full((64, 520, 3), 45, np.uint8)
    # Write each instruction line, 28 px below the previous one.
    for row, text in enumerate(["Move the sliders until only the coating is green.",
                                "Click photo = print HSV    s = save to config    q = quit"]):
        # White text, size 0.55, 1 px thick, with smoothed edges.
        cv2.putText(picture, text, (10, 24 + 28 * row), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1,
                    cv2.LINE_AA)
    # Hand the finished picture back.
    return picture


def main(argv=None) -> int:
    """Open the tuner windows and run until the user quits.

    Args:
        argv: the command-line words; None means "use the ones typed in the terminal".

    Returns:
        0, the exit code for success.
    """
    # Describe the options this command accepts.
    ap = argparse.ArgumentParser(description="Tune the coating colour range with sliders.")
    # --image: the photo to tune on (required).
    ap.add_argument("--image", required=True, help="a photo of a coated board")
    ap.add_argument("--config", default="config.yaml")  # --config: the settings file to read and save
    # Read the options the user typed (argparse stops with a help message if --image is missing).
    args = ap.parse_args(argv)
    # Load the current segmentation settings; the sliders start at these values.
    seg = load_config(args.config)["segmentation"]
    # Load the photo.
    image = read_image(args.image)
    # Convert it to HSV once, for the click read-out.
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    # Shrink factor, so the photo fits in about 1000 x 700 pixels on screen (never enlarged).
    scale = min(1.0, 1000 / image.shape[1], 700 / image.shape[0])

    # Sliders and photo get separate windows, so the sliders never squeeze the photo.
    cv2.namedWindow(SLIDERS_WINDOW, cv2.WINDOW_AUTOSIZE)  # AUTOSIZE: the window fits its picture
    cv2.namedWindow(PHOTO_WINDOW, cv2.WINDOW_AUTOSIZE)  # AUTOSIZE: the window fits its picture
    # Put the sliders at the top left of the screen and the photo to their right.
    cv2.moveWindow(SLIDERS_WINDOW, 0, 0)  # top-left corner of the screen
    cv2.moveWindow(PHOTO_WINDOW, 540, 0)  # 540 px from the left, at the top
    # Create one slider per entry in SLIDERS.
    for label, key, i, top in SLIDERS:
        # Its start value: one number of a list (hsv_lower[0] ...) or a single setting (blur_px ...).
        value = seg[key][i] if i is not None else seg[key]
        # The slider runs from 0 to "top"; the empty function means "do nothing when it moves",
        # because the loop below reads all sliders anyway.
        cv2.createTrackbar(label, SLIDERS_WINDOW, int(value), top, lambda _: None)
    # Show the instructions in the sliders window.
    cv2.imshow(SLIDERS_WINDOW, help_picture())

    # Remembers the previous click for the distance read-out (a list, so on_click can change it).
    last_click = []

    def on_click(event, x, y, flags, param):
        """Called by OpenCV for every mouse event in the photo window; reacts to left clicks only."""
        # Ignore mouse moves, right clicks and so on.
        if event != cv2.EVENT_LBUTTONDOWN:
            return  # nothing to do
        # Convert the click position from the shrunken picture back to full-size photo pixels.
        px = min(int(x / scale), image.shape[1] - 1)  # the column (x); min() keeps it inside the photo
        py = min(int(y / scale), image.shape[0] - 1)  # the row (y), the same way
        # Read that pixel's hue, saturation and value (NumPy indexes images as [row, column]).
        h, s, v = (int(c) for c in hsv[py, px])
        # Build the message to print.
        message = f"pixel ({px}, {py})  HSV = ({h}, {s}, {v})"
        # After the first click, also give the distance from the previous click (for pixels_per_mm).
        if last_click:
            # Add the straight-line distance between the two clicks.
            message += f"   distance from previous click: {math.dist(last_click, (px, py)):.1f} px"
        # Remember this click for next time.
        last_click[:] = [px, py]
        # Print straight away (flush), so it appears in the terminal immediately.
        print(message, flush=True)

    # Tell OpenCV to call on_click for mouse events in the photo window.
    cv2.setMouseCallback(PHOTO_WINDOW, on_click)
    # The slider values drawn last time; None forces the first drawing.
    shown = None
    # Keep going until the user quits.
    while True:
        # Read every slider's current position into the settings.
        for label, key, i, _ in SLIDERS:
            value = cv2.getTrackbarPos(label, SLIDERS_WINDOW)  # the slider's current position
            # A single setting such as blur_px ...
            if i is None:
                seg[key] = value  # store it directly
            # ... or one number inside hsv_lower or hsv_upper.
            else:
                seg[key][i] = value  # store it at position i of the list
        # All slider values together, to see whether anything changed.
        state = (tuple(seg["hsv_lower"]), tuple(seg["hsv_upper"]), seg["blur_px"], seg["open_px"], seg["close_px"])
        # Only redo the (slow) coating detection when a slider has moved.
        if state != shown:
            # Find the coating with the current values and show the preview.
            cv2.imshow(PHOTO_WINDOW, preview(image, segment_coating(image, seg), scale))
            shown = state  # remember what is on screen now
        # Let the windows update and wait up to 30 ms for a key press (& 0xFF keeps just the key code).
        key = cv2.waitKey(30) & 0xFF
        # s: save the current values into config.yaml and confirm in the terminal.
        if key == ord("s"):
            save_to_config(args.config, seg)  # write the values into the settings file
            # Confirm what was saved.
            print(f"saved to {args.config}: hsv_lower={seg['hsv_lower']} hsv_upper={seg['hsv_upper']} "
                  f"blur_px={seg['blur_px']} open_px={seg['open_px']} close_px={seg['close_px']}", flush=True)
        # Has either window been closed with its X button?
        closed = any(cv2.getWindowProperty(w, cv2.WND_PROP_VISIBLE) < 1 for w in (SLIDERS_WINDOW, PHOTO_WINDOW))
        # q, Esc (key code 27) or a closed window ends the loop.
        if key in (ord("q"), 27) or closed:
            break  # leave the while loop
    # Close all OpenCV windows.
    cv2.destroyAllWindows()
    # Exit code 0 = success.
    return 0


# This block runs only when the file is started with  python -m coating_inspector.tune ...
if __name__ == "__main__":
    # Run main() and hand its return value to the operating system as the exit code.
    raise SystemExit(main())
