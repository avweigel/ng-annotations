"""Export -> CSV -> load -> export gives the same tables, for every annotation type."""
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ng_annotations import NGAnnotationError, extract, load_state, read_files, to_link, write_csv  # noqa: E402

DIMS = {"z": [8e-9, "m"], "y": [8e-9, "m"], "x": [8e-9, "m"]}
STATE = {
    "dimensions": DIMS,
    "layers": [
        {"type": "image", "name": "em", "source": "zarr://https://example.org/data/sample.zarr/em"},
        {"type": "annotation", "name": "marks",
         "source": {"url": "local://annotations", "transform": {"outputDimensions": DIMS}},
         "annotationProperties": [{"id": "score", "type": "float32", "default": 0}],
         "annotations": [
             {"type": "line", "id": "l1", "pointA": [10, 20, 30], "pointB": [13, 24, 30],
              "segments": [["5", "7"]], "description": "first", "props": [0.5]},
             {"type": "point", "id": "p1", "point": [1, 2, 3], "props": [1]},
             {"type": "axis_aligned_bounding_box", "id": "b1", "pointA": [5, 5, 5], "pointB": [1, 2, 3]},
             {"type": "ellipsoid", "id": "e1", "center": [9, 9, 9], "radii": [1, 2, 3]},
             {"type": "polyline", "id": "pl1", "points": [[0, 0, 0], [0, 3, 4], [0, 3, 8]]},
         ]},
    ],
    "layout": "4panel",
}
LINK = "https://neuroglancer-demo.appspot.com/#!" + quote(json.dumps(STATE), safe="")


def export_all(link, folder):
    state, text = load_state(link)
    tables, skipped = extract(state, text)
    paths = []
    for kind, t in tables.items():
        p = Path(folder) / f"{kind}.csv"
        write_csv(p, t["columns"], t["rows"])
        paths.append(str(p))
    return tables, skipped, paths


class RoundTrip(unittest.TestCase):
    def test_values(self):
        tables, skipped, _ = export_all(LINK, tempfile.mkdtemp())
        self.assertEqual(skipped, 0)
        self.assertEqual(set(tables), {"line", "point", "axis_aligned_bounding_box", "ellipsoid", "polyline"})
        line = tables["line"]["rows"][0]
        self.assertEqual(line["start z (nm)"], "80.0")
        self.assertEqual(line["length (nm)"], "40.0")          # 8 nm voxels: 3-4-5 triangle x 8
        self.assertEqual(line["segments"], "5;7")
        self.assertEqual(line["score"], "0.5")
        box = tables["axis_aligned_bounding_box"]["rows"][0]
        self.assertEqual((box["min z (nm)"], box["max z (nm)"], box["size x (nm)"]), ("8.0", "40.0", "16.0"))
        poly = tables["polyline"]["rows"]
        self.assertEqual([r["distance along (nm)"] for r in poly], ["0.0", "40.0", "72.0"])

    def test_round_trip(self):
        d = tempfile.mkdtemp()
        first, _, paths = export_all(LINK, d)
        records, links, _ = read_files(paths)
        url, *_ = to_link(records, links)
        second, _, _ = export_all(url, tempfile.mkdtemp())
        for kind in first:
            strip = lambda rows: [{k: v for k, v in r.items() if k != "neuroglancer url"} for r in rows]
            self.assertEqual(strip(first[kind]["rows"]), strip(second[kind]["rows"]), kind)

    def test_bare(self):
        _, _, paths = export_all(LINK, tempfile.mkdtemp())
        records, links, _ = read_files(paths)
        url, state, on, *_ = to_link(records, links, bare=True)
        self.assertEqual(on, "nothing else")
        self.assertEqual([l["type"] for l in state["layers"]], ["annotation"])

    def test_errors(self):
        with self.assertRaises(NGAnnotationError):
            load_state("https://example.org/#!{not json")
        with self.assertRaises(NGAnnotationError):
            load_state("https://example.org/no-state")
        with self.assertRaises(NGAnnotationError):
            load_state("https://example.org/#!gs://bucket/state.json")

    def test_cli(self):
        d = Path(tempfile.mkdtemp())
        (d / "link.txt").write_text(LINK)
        env_py = [sys.executable, "-m", "ng_annotations"]
        run = lambda *a: subprocess.run(env_py + list(a), cwd=d, capture_output=True, text=True,
                                        env={"PYTHONPATH": str(ROOT / "src")})
        r = run("export", "link.txt", "out.csv")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((d / "out_points.csv").exists())
        r = run("load", "out.csv", "out_points.csv", "--bare")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("https://neuroglancer-demo.appspot.com/#!"))
        self.assertEqual(run("export", "https://x/#!nope", "a.csv").returncode, 1)


if __name__ == "__main__":
    unittest.main()
