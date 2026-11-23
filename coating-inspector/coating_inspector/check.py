"""Step 9: check board photos against the golden pattern.
Run:  python -m coating_inspector.check --golden golden --images samples/test --out results"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from .align import AlignmentError
from .common import find_images, load_config, read_image, write_image
from .compare import inspect_image
from .golden import load_golden
from .report import draw_overlay, write_report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check boards against the golden coating pattern.")
    ap.add_argument("--golden", default="golden", help="folder made by coating_inspector.golden")
    ap.add_argument("--images", nargs="+", required=True, help="board photos (files, folders or wildcards)")
    ap.add_argument("--out", default="results", help="folder for result pictures and reports")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    golden = load_golden(args.golden)
    paths = find_images(args.images)
    if not paths:
        ap.error("no images found")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    print(f"{'board':<24}{'result':<8}{'coverage':>9}{'outline':>9}  details")
    for path in paths:
        try:
            inspection = inspect_image(read_image(path), golden, cfg)
        except AlignmentError as err:
            print(f"{path.name:<24}{'ERROR':<8}{'':>18}  {err}")
            rows.append({"board": path.name, "result": "ERROR", "details": str(err)})
            continue
        comp = inspection.comparison
        write_image(out / f"{path.stem}_result.png", draw_overlay(inspection, golden))
        write_image(out / f"{path.stem}_mask.png", inspection.mask)
        write_report(out / f"{path.stem}.json", path, inspection)
        result = "PASS" if comp.passed else "FAIL"
        m = comp.metrics
        print(f"{path.name:<24}{result:<8}{m['coverage_pct']:>8.1f}%{m['outline_match_pct']:>8.1f}%  "
              f"{'; '.join(comp.reasons)}")
        rows.append({"board": path.name, "result": result, "details": "; ".join(comp.reasons), **m})

    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        fields = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    failed = sum(row["result"] != "PASS" for row in rows)
    print(f"\n{len(rows) - failed} passed, {failed} failed. Pictures and reports are in {out}/")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
