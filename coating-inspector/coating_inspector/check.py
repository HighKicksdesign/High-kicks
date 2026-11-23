"""Step 9: check board photos against the golden pattern.
Run:  python -m coating_inspector.check --golden golden --images samples/test --out results"""
from __future__ import annotations  # lets newer type hints work on older Python versions

import argparse  # reads the options typed after the command
import csv  # writes summary.csv (which opens in Excel)
from pathlib import Path  # handles file and folder paths

from .align import AlignmentError  # raised when a photo cannot be lined up
from .common import find_images, load_config, read_image, write_image  # settings and file helpers
from .compare import inspect_image  # inspects one photo
from .golden import load_golden  # loads the approved pattern
from .report import draw_overlay, write_report  # result picture and JSON report


def main(argv=None) -> int:
    """Command line: check every given photo and write pictures, reports and a summary.

    Args:
        argv: the command-line words; None means "use the ones typed in the terminal".

    Returns:
        The exit code: 0 if every board passed, 1 if any failed or could not be checked.
    """
    # Describe the options this command accepts.
    ap = argparse.ArgumentParser(description="Check boards against the golden coating pattern.")
    # --golden: the folder with the golden pattern (default: golden).
    ap.add_argument("--golden", default="golden", help="folder made by coating_inspector.golden")
    # --images: one or more photos, folders or wildcards (required).
    ap.add_argument("--images", nargs="+", required=True, help="board photos (files, folders or wildcards)")
    # --out: where the results are written (default: results).
    ap.add_argument("--out", default="results", help="folder for result pictures and reports")
    ap.add_argument("--config", default="config.yaml")  # --config: the settings file
    # Read what the user typed.
    args = ap.parse_args(argv)
    # Load the settings ...
    cfg = load_config(args.config)
    # ... and the approved pattern.
    golden = load_golden(args.golden)
    # Turn files, folders and wildcards into a list of photos.
    paths = find_images(args.images)
    # Nothing found: stop with an error message.
    if not paths:
        ap.error("no images found")  # argparse prints the message and stops the program
    # Create the output folder (no error if it already exists).
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)  # parents=True also creates any missing parent folders

    # One summary row per board, for summary.csv.
    rows = []
    # The table heading; each column is padded to a fixed width (<24 = left-aligned in 24 characters).
    print(f"{'board':<24}{'result':<8}{'coverage':>9}{'outline':>9}  details")
    # Inspect the photos one by one.
    for path in paths:
        # Try the inspection ...
        try:
            # Read the photo, then align, segment and compare.
            inspection = inspect_image(read_image(path), golden, cfg)
        # ... and if the photo can't be lined up, report an ERROR row instead of stopping everything.
        except AlignmentError as err:
            print(f"{path.name:<24}{'ERROR':<8}{'':>18}  {err}")  # an ERROR row in the table, with the reason
            rows.append({"board": path.name, "result": "ERROR", "details": str(err)})  # recorded for summary.csv too
            # Go on with the next photo.
            continue
        # The comparison result.
        comp = inspection.comparison
        # Save the result picture, the coating mask and the JSON report, named after the photo.
        write_image(out / f"{path.stem}_result.png", draw_overlay(inspection, golden))  # the marked-up result picture
        write_image(out / f"{path.stem}_mask.png", inspection.mask)  # the coating found, as a black/white picture
        write_report(out / f"{path.stem}.json", path, inspection)  # the JSON report
        # The verdict as text.
        result = "PASS" if comp.passed else "FAIL"
        # A short name for the measurements.
        m = comp.metrics
        # Print one table row: name, verdict, coverage and outline match (1 decimal place) and the reasons.
        print(f"{path.name:<24}{result:<8}{m['coverage_pct']:>8.1f}%{m['outline_match_pct']:>8.1f}%  "
              f"{'; '.join(comp.reasons)}")
        # The same, plus every measurement, for summary.csv (** unpacks the metrics dictionary).
        rows.append({"board": path.name, "result": result, "details": "; ".join(comp.reasons), **m})

    # Write summary.csv (newline="" prevents blank lines between the rows on Windows).
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        # The column names: every key used in any row, in first-seen order, without repeats.
        fields = list(dict.fromkeys(key for row in rows for key in row))
        # A CSV writer turns each dictionary into one line of the file.
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()  # first line: the column names
        writer.writerows(rows)  # then one line per board
    # Count the boards that did not pass (FAIL or ERROR).
    failed = sum(row["result"] != "PASS" for row in rows)
    # The final summary line.
    print(f"\n{len(rows) - failed} passed, {failed} failed. Pictures and reports are in {out}/")
    # Exit code for scripts: 1 if anything failed, 0 if everything passed.
    return 1 if failed else 0


# This block runs only when the file is started with  python -m coating_inspector.check ...
if __name__ == "__main__":
    # Run main() and hand its return value to the operating system as the exit code.
    raise SystemExit(main())
