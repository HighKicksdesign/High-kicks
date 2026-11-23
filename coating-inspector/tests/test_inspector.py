"""Automated checks.  Run:  python -m pytest   (or use the Testing panel in VS Code)

pytest runs every function whose name starts with test_. A test passes when all of
its assert statements are true."""
from pathlib import Path  # handles file and folder paths

import numpy as np  # NumPy: builds a small test picture
import pytest  # the test runner: fixtures, parametrize, approx

from coating_inspector.align import align_to_reference  # the functions being tested ...
from coating_inspector.common import load_config, read_image, write_image  # settings and image files
from coating_inspector.compare import inspect_image  # inspects one photo
from coating_inspector.golden import build_golden, read_keepout  # builds the pattern, reads keep-out zones
from coating_inspector.synthetic import SAMPLES, make_samples  # sample photos and their known placement
from coating_inspector.tune import save_to_config  # the tuner's save function

ROOT = Path(__file__).resolve().parents[1]  # the project folder (one level above tests/)
CFG = load_config(ROOT / "config.yaml")  # the real settings, so the tests check what you will use


# A fixture: made once for this file and handed to every test that names it as an argument.
@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    """Make fresh sample photos once, in a temporary folder, for all the tests in this file."""
    # tmp_path_factory gives a new empty temporary folder; make_samples fills it and returns it.
    return make_samples(tmp_path_factory.mktemp("samples"))


# A fixture: made once for this file and handed to every test that names it as an argument.
@pytest.fixture(scope="module")
def golden(samples, tmp_path_factory):
    """Build a golden pattern once, from the approved sample photos (uses the samples fixture)."""
    # The approved photos, sorted so approved_1 (placed exactly) becomes the reference.
    approved = sorted((samples / "approved").glob("*.png"))
    # Build the pattern with the real settings and the keep-out mask, in another temporary folder.
    return build_golden(approved, CFG, tmp_path_factory.mktemp("golden"), samples / "keepout_mask.png")


def photo(samples, name):
    """Read one sample photo by name, for example photo(samples, "good_1")."""
    # Each sample's folder (approved or test) is stored in SAMPLES.
    return read_image(samples / SAMPLES[name].folder / f"{name}.png")


# Run the next test four times, once for each photo name.
@pytest.mark.parametrize("name", ["approved_2", "good_1", "good_2", "shifted_pattern"])
def test_alignment_finds_the_known_placement(samples, name):
    """Alignment must find each board's true shift (within 1 px) and rotation (within 0.1 degrees)."""
    # Line the photo up with approved_1, which was placed exactly.
    a = align_to_reference(photo(samples, "approved_1"), photo(samples, name), CFG["alignment"])
    # pytest.approx allows a small difference: abs=1.0 means within 1 px.
    assert a.shift_px == pytest.approx(SAMPLES[name].shift, abs=1.0)
    # And the rotation must be within 0.1 degrees.
    assert a.rotation_deg == pytest.approx(SAMPLES[name].angle, abs=0.1)


# Run the next test once for each (photo, expected defect kinds) pair.
@pytest.mark.parametrize("name, expected", [
    ("good_1", set()),                          # no defects: should PASS
    ("good_2", set()),                          # no defects: should PASS
    ("missing_coating", {"missing"}),           # exactly one kind: missing
    ("excess_spill", {"excess"}),               # exactly one kind: excess
    ("keepout_violation", {"keepout"}),         # exactly one kind: keep-out
    ("shifted_pattern", {"missing", "excess"}), # both missing and excess strips
])
def test_boards_get_the_right_verdict(samples, golden, name, expected):
    """Each sample board must get exactly the defect kinds it was made with, and PASS only if it has none."""
    # Inspect the photo and keep the comparison result.
    result = inspect_image(photo(samples, name), golden, CFG).comparison
    # The kinds of defect found must equal the expected set (if not, the reasons are shown).
    assert {d.kind for d in result.defects} == expected, result.reasons
    # PASS exactly when nothing was expected.
    assert result.passed == (not expected), result.reasons


def test_shifted_pattern_fails_the_outline_check(samples, golden):
    """A pattern shifted by 2.5 mm must also fail the outline-match rule."""
    # Inspect the shifted board.
    result = inspect_image(photo(samples, "shifted_pattern"), golden, CFG).comparison
    # Its outline match must be below the minimum in config.yaml.
    assert result.metrics["outline_match_pct"] < CFG["tolerance"]["min_outline_match_pct"]


def test_keepout_can_be_painted_in_magenta(tmp_path):
    """A keep-out zone painted pure magenta on a picture must be read as a mask."""
    # A small black picture (50 x 80 px) ...
    picture = np.zeros((50, 80, 3), np.uint8)
    # ... with a 10 x 30 px magenta rectangle (BGR 255, 0, 255).
    picture[10:20, 30:60] = (255, 0, 255)
    # Save it in pytest's temporary folder.
    write_image(tmp_path / "painted.png", picture)
    # Read it back as keep-out zones.
    keepout = read_keepout(tmp_path / "painted.png")
    # Inside the rectangle = 255, outside = 0, and exactly 10 x 30 = 300 pixels marked.
    assert keepout[15, 40] == 255 and keepout[30, 10] == 0 and (keepout > 0).sum() == 300


def test_tuner_saves_values_and_keeps_comments(tmp_path):
    """Saving from the tuner must change the values in config.yaml and keep its comments."""
    # Copy the real config.yaml to a temporary file, so the real one is not changed.
    config_file = tmp_path / "config.yaml"
    # Fill it with the real file's text.
    config_file.write_text((ROOT / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    # The current settings with two values changed.
    seg = dict(CFG["segmentation"], hsv_lower=[90, 70, 100], close_px=6)
    # Save them the way the tuner does.
    save_to_config(config_file, seg)
    # Read the file back: the new values must be there ...
    saved = load_config(config_file)["segmentation"]
    assert saved["hsv_lower"] == [90, 70, 100] and saved["close_px"] == 6  # both changed values must be saved
    # ... and a comment from the original file must still be there.
    assert "Tune it for YOUR camera" in config_file.read_text(encoding="utf-8")
