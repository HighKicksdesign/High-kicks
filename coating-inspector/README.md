# Coating Border Inspector

Reference copy of the project from the *Coating Border Inspector* build guide: a Python + OpenCV
tool that finds the borders of conformal coating on a PCBA photographed under blue/UV light, lines
each photo up with an approved board, and reports PASS or FAIL with a marked-up picture, a JSON
report and a CSV summary.

Guide: https://claude.ai/artifact/DqWtpdHKvAi2eDArq8apaL (private until you share it)

## Quick start

Open this `coating-inspector` folder in VS Code and create a virtual environment in its terminal.

Windows (PowerShell):

```
py -m venv .venv
.venv\Scripts\Activate.ps1
```

macOS / Linux:

```
python3 -m venv .venv
source .venv/bin/activate
```

Then, on any system:

```
pip install -r requirements.txt
python -m coating_inspector.synthetic
python -m coating_inspector.golden --images samples/approved --keepout samples/keepout_mask.png --out golden
python -m coating_inspector.check --golden golden --images samples/approved samples/test --out results
python -m pytest
```

Expected: 5 boards pass and 4 fail, each for its built-in defect, and 13 tests pass. Result
pictures and reports are written to `results/`.

Before using it on real boards, follow step 12 of the guide: tune the colour range, measure
`pixels_per_mm` and set the tolerances in `config.yaml`.

Tested on Linux with Python 3.11 + OpenCV 4.10, Python 3.12, and Python 3.13 + OpenCV 5.1.
