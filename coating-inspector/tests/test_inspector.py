"""Automated checks.  Run:  python -m pytest   (or use the Testing panel in VS Code)"""
from pathlib import Path

import numpy as np
import pytest

from coating_inspector.align import align_to_reference
from coating_inspector.common import load_config, read_image, write_image
from coating_inspector.compare import inspect_image
from coating_inspector.golden import build_golden, read_keepout
from coating_inspector.synthetic import SAMPLES, make_samples
from coating_inspector.tune import save_to_config

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT / "config.yaml")


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    return make_samples(tmp_path_factory.mktemp("samples"))


@pytest.fixture(scope="module")
def golden(samples, tmp_path_factory):
    approved = sorted((samples / "approved").glob("*.png"))
    return build_golden(approved, CFG, tmp_path_factory.mktemp("golden"), samples / "keepout_mask.png")


def photo(samples, name):
    return read_image(samples / SAMPLES[name].folder / f"{name}.png")


@pytest.mark.parametrize("name", ["approved_2", "good_1", "good_2", "shifted_pattern"])
def test_alignment_finds_the_known_placement(samples, name):
    a = align_to_reference(photo(samples, "approved_1"), photo(samples, name), CFG["alignment"])
    assert a.shift_px == pytest.approx(SAMPLES[name].shift, abs=1.0)
    assert a.rotation_deg == pytest.approx(SAMPLES[name].angle, abs=0.1)


@pytest.mark.parametrize("name, expected", [
    ("good_1", set()),
    ("good_2", set()),
    ("missing_coating", {"missing"}),
    ("excess_spill", {"excess"}),
    ("keepout_violation", {"keepout"}),
    ("shifted_pattern", {"missing", "excess"}),
])
def test_boards_get_the_right_verdict(samples, golden, name, expected):
    result = inspect_image(photo(samples, name), golden, CFG).comparison
    assert {d.kind for d in result.defects} == expected, result.reasons
    assert result.passed == (not expected), result.reasons


def test_shifted_pattern_fails_the_outline_check(samples, golden):
    result = inspect_image(photo(samples, "shifted_pattern"), golden, CFG).comparison
    assert result.metrics["outline_match_pct"] < CFG["tolerance"]["min_outline_match_pct"]


def test_keepout_can_be_painted_in_magenta(tmp_path):
    picture = np.zeros((50, 80, 3), np.uint8)
    picture[10:20, 30:60] = (255, 0, 255)
    write_image(tmp_path / "painted.png", picture)
    keepout = read_keepout(tmp_path / "painted.png")
    assert keepout[15, 40] == 255 and keepout[30, 10] == 0 and (keepout > 0).sum() == 300


def test_tuner_saves_values_and_keeps_comments(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text((ROOT / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    seg = dict(CFG["segmentation"], hsv_lower=[90, 70, 100], close_px=6)
    save_to_config(config_file, seg)
    saved = load_config(config_file)["segmentation"]
    assert saved["hsv_lower"] == [90, 70, 100] and saved["close_px"] == 6
    assert "Tune it for YOUR camera" in config_file.read_text(encoding="utf-8")
