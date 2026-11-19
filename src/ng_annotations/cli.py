"""Command line: ng-annotations export | load.

  ng-annotations export LINK out.csv
      Write the annotations in a Neuroglancer link to CSV, one file per type,
      coordinates in nm:
          lines        out.csv             start z/y/x, end z/y/x, length
          points       out_points.csv      z/y/x
          boxes        out_boxes.csv       min z/y/x, max z/y/x, size z/y/x
          ellipsoids   out_ellipsoids.csv  center z/y/x, radius z/y/x
          polylines    out_polylines.csv   one row per vertex, with the distance along
      LINK is the link itself (in single quotes), a file holding it, the JSON
      state from Neuroglancer's { } button, or "-" to read it from standard input:
          pbpaste | ng-annotations export - out.csv          (macOS clipboard)

  ng-annotations load out.csv [out_points.csv ...] [--base LINK | --bare]
      Print a Neuroglancer link holding the annotations in those CSV files
      (edited or not). Shown on the view saved in the files' "neuroglancer url"
      column, on --base LINK, or on nothing else with --bare.
          ng-annotations load out.csv | pbcopy               (link onto the clipboard)

Put a pasted link in single quotes: it contains "#!", which zsh and bash treat
as history expansion inside double quotes.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core import TYPES, NGAnnotationError, count, extract, load_state, read_files, to_link, write_csv


def export(link: str, out: str) -> None:
    state, link_text = load_state(link)
    tables, skipped = extract(state, link_text)
    if not tables:
        raise NGAnnotationError("No annotations found in local annotation layers.")
    out_path = Path(out)
    for kind, (suffix, one, many) in TYPES.items():
        if kind not in tables:
            continue
        path = out_path if not suffix else out_path.with_name(
            f"{out_path.stem}_{suffix}{out_path.suffix or '.csv'}")
        write_csv(path, tables[kind]["columns"], tables[kind]["rows"])
        n = count(kind, tables[kind]["rows"])
        print(f"{n} {one if n == 1 else many} -> {path}")
    if "line" not in tables:
        print(f"(no lines, so {out_path} was not written)")
    if skipped:
        print(f"({skipped} annotation{'' if skipped == 1 else 's'} of an unknown type skipped)")


def load(files: list[str], base: str | None, bare: bool) -> None:
    records, links, unread = read_files(files)
    url, _, on, notes, used = to_link(records, links, base=base, bare=bare)
    counts = {k: sum(r["kind"] == k for r in records) for k in TYPES}
    loaded = ", ".join(f"{n} {TYPES[k][1] if n == 1 else TYPES[k][2]}" for k, n in counts.items() if n)
    print(f"{loaded}, shown on {on}", file=sys.stderr)
    for note in notes:
        print(f"  {note}", file=sys.stderr)
    left = [c for c in unread if c not in used]
    if left:
        print(f"  not loaded (no matching property in the layer): {', '.join(left)}", file=sys.stderr)
    print(url)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ng-annotations", description=__doc__.split("\n\n")[0],
                                 epilog="\n\n".join(__doc__.split("\n\n")[1:]),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="Neuroglancer link -> CSV files")
    e.add_argument("link", help="link, file holding it, JSON state, or - for stdin")
    e.add_argument("out", help="output CSV path (other types get _points, _boxes, ... added)")
    l = sub.add_parser("load", help="CSV files -> Neuroglancer link")
    l.add_argument("files", nargs="+", help="CSV files written by export or the web page")
    g = l.add_mutually_exclusive_group()
    g.add_argument("--base", help="show the annotations on this link (or file, or JSON state)")
    g.add_argument("--bare", action="store_true", help="show the annotations on their own")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "export":
            export(args.link, args.out)
        else:
            load(args.files, args.base, args.bare)
    except NGAnnotationError as err:
        print(f"ng-annotations: {err}", file=sys.stderr)
        return 1
    return 0
