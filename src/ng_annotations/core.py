"""Neuroglancer annotations to spreadsheets and back.

``extract`` reads the annotations stored in a Neuroglancer link (local
annotation layers) and returns one table per annotation type, coordinates in
nanometres. ``read_files`` and ``build`` do the reverse: CSV files written by
``extract`` (edited or not) go back into a Neuroglancer state.

Standard library only. The browser page (docs/index.html) runs the same code in
JavaScript and writes identical files; keep the two in step.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from urllib.parse import quote, unquote


class NGAnnotationError(ValueError):
    """A link, state or spreadsheet that can't be read. The message says why."""


def _fail(msg: str):
    raise NGAnnotationError(msg)


AXES = ("z", "y", "x")
UNIT_TO_NM = {"m": 1e9, "mm": 1e6, "um": 1e3, "µm": 1e3, "nm": 1.0}

# Neuroglancer's type name -> (suffix of its file, singular, plural), in the
# order files are written. Lines write to the output path itself.
TYPES = {
    "line": ("", "line", "lines"),
    "point": ("points", "point", "points"),
    "axis_aligned_bounding_box": ("boxes", "box", "boxes"),
    "ellipsoid": ("ellipsoids", "ellipsoid", "ellipsoids"),
    "polyline": ("polylines", "polyline", "polylines"),
}
# the columns each type adds between "id" and "segments"
SHAPE_COLUMNS = {
    "line": [f"start {a} (nm)" for a in AXES] + [f"end {a} (nm)" for a in AXES] + ["length (nm)"],
    "point": [f"{a} (nm)" for a in AXES],
    "axis_aligned_bounding_box": ([f"min {a} (nm)" for a in AXES] + [f"max {a} (nm)" for a in AXES]
                                  + [f"size {a} (nm)" for a in AXES]),
    "ellipsoid": [f"center {a} (nm)" for a in AXES] + [f"radius {a} (nm)" for a in AXES],
    "polyline": ["vertex"] + [f"{a} (nm)" for a in AXES] + ["distance along (nm)"],
}
HEAD = ["layer", "id"]
TAIL = ["segments", "neuroglancer url", "description"]


def load_state(src: str) -> tuple[dict, str]:
    """Return (state dict, link) from a Neuroglancer link, a file holding one,
    the JSON state itself (Neuroglancer's { } button), or "-" for standard input."""
    text = src.strip()
    if text == "-":
        text = sys.stdin.read().strip()
    elif not text.startswith(("http", "{")) and Path(text).exists():
        text = Path(text).read_text().strip()
    if text.startswith("{"):
        return _parse(text), ""
    if "#!" not in text:
        _fail("No '#!' state in that link. Copy the full address from Neuroglancer.")
    frag = unquote(text.split("#!", 1)[1])
    if frag.startswith(("http://", "https://", "gs://", "s3://")):
        _fail(f"This link points at a saved state ({frag[:80]}) instead of carrying it. "
                 "Open it in Neuroglancer and copy the JSON with the { } button.")
    return _parse(frag), text


def _parse(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        _fail("The link's state is not valid JSON. Was the whole address copied?")


def nm_per_unit(dims: dict) -> list[tuple[str, float]]:
    """Neuroglancer dimensions {"z": [8e-9, "m"], ...} -> [(axis, nm per unit), ...] in order."""
    out = []
    for name, (scale, unit) in dims.items():
        if unit not in UNIT_TO_NM:
            _fail(f"Unsupported unit {unit!r} on axis {name!r}")
        out.append((name, float(scale) * UNIT_TO_NM[unit]))
    return out


# Every value is turned into its CSV text here, so the browser page can match
# it exactly: nanometres rounded to 0.001 and written as Python writes a float.
def nm(v: float) -> str:
    return repr(round(v, 3))


def prop_text(v) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return repr(float(v))
    return "" if v is None else str(v)


def dist(a: dict, b: dict) -> float:
    # written out, not math.dist, so the page can repeat the same arithmetic
    dz, dy, dx = (b[k] - a[k] for k in AXES)
    return math.sqrt(dz * dz + dy * dy + dx * dx)


def extract(state: dict, link: str = "") -> tuple[dict, int]:
    """Return ({type: {"columns": [...], "rows": [row dict, ...]}}, skipped).
    Only types the link contains are present; `skipped` counts annotations of
    a type this script does not know."""
    tables = {t: {"columns": None, "rows": [], "props": []} for t in TYPES}
    skipped = 0
    global_dims = state.get("dimensions")
    for layer in state.get("layers", []):
        if layer.get("type") != "annotation" or "annotations" not in layer:
            continue
        name = layer.get("name", "")
        src = layer.get("source")
        dims = global_dims
        if isinstance(src, dict):
            dims = (src.get("transform") or {}).get("outputDimensions") or dims
        if not dims:
            _fail(f"Layer {name!r}: no coordinate space found")
        axes = nm_per_unit(dims)
        missing = set(AXES) - {a for a, _ in axes}
        if missing:
            _fail(f"Layer {name!r}: missing axes {sorted(missing)}")
        props = layer.get("annotationProperties") or []

        def field(ann, key):
            if key not in ann:
                _fail(f"Layer {name!r}: annotation {ann.get('id', '?')!r} has no {key!r}")
            return ann[key]

        def point(p):
            return {ax: float(v) * s for (ax, s), v in zip(axes, p)}

        for ann in layer["annotations"]:
            kind = ann.get("type")
            if kind not in TYPES:
                skipped += 1
                continue
            segs = []
            for group in ann.get("segments", []):
                # current Neuroglancer writes one list per linked layer; older links a flat list
                segs.extend([group] if isinstance(group, str) else group)
            tail = {"segments": ";".join(map(str, segs)), "neuroglancer url": link,
                    "description": str(ann.get("description") or "")}
            # one column per property; an id that repeats a column name gets
            # " (property)" added so it cannot overwrite that column
            base = HEAD + SHAPE_COLUMNS[kind] + TAIL
            values = ann.get("props") or []
            extra = {}
            for i, p in enumerate(props):
                pid = str(p.get("id", f"property {i + 1}"))
                extra[pid if pid not in base else f"{pid} (property)"] = prop_text(
                    values[i] if i < len(values) else p.get("default"))
            head = {"layer": name, "id": str(ann.get("id", ""))}

            shapes = []
            if kind == "line":
                a, b = point(field(ann, "pointA")), point(field(ann, "pointB"))
                s = {f"start {k} (nm)": nm(a[k]) for k in AXES}
                s.update({f"end {k} (nm)": nm(b[k]) for k in AXES})
                s["length (nm)"] = nm(dist(a, b))
                shapes.append(s)
            elif kind == "point":
                p = point(field(ann, "point"))
                shapes.append({f"{k} (nm)": nm(p[k]) for k in AXES})
            elif kind == "axis_aligned_bounding_box":
                a, b = point(field(ann, "pointA")), point(field(ann, "pointB"))
                s = {f"min {k} (nm)": nm(min(a[k], b[k])) for k in AXES}
                s.update({f"max {k} (nm)": nm(max(a[k], b[k])) for k in AXES})
                s.update({f"size {k} (nm)": nm(abs(b[k] - a[k])) for k in AXES})
                shapes.append(s)
            elif kind == "ellipsoid":
                c, r = point(field(ann, "center")), point(field(ann, "radii"))
                s = {f"center {k} (nm)": nm(c[k]) for k in AXES}
                s.update({f"radius {k} (nm)": nm(abs(r[k])) for k in AXES})
                shapes.append(s)
            elif kind == "polyline":
                along, prev = 0.0, None
                for i, raw in enumerate(field(ann, "points"), 1):
                    p = point(raw)
                    if prev is not None:
                        along += dist(prev, p)
                    prev = p
                    shapes.append({"vertex": str(i), **{f"{k} (nm)": nm(p[k]) for k in AXES},
                                   "distance along (nm)": nm(along)})

            t = tables[kind]
            t["props"] += [k for k in extra if k not in t["props"]]
            t["rows"].extend({**head, **s, **tail, **extra} for s in shapes)

    # property columns are the union over the layers that hold this type
    return ({kind: {"columns": HEAD + SHAPE_COLUMNS[kind] + TAIL + t["props"], "rows": t["rows"]}
             for kind, t in tables.items() if t["rows"]}, skipped)


NG_HOST = "https://neuroglancer-demo.appspot.com/"
NM_SPACE = {a: [1e-9, "m"] for a in AXES}

# The columns a file must have to be read as each type, checked in this order
# (a polyline file also has the point columns, so it is tried first).
REQUIRED = {
    "line": [f"start {a} (nm)" for a in AXES] + [f"end {a} (nm)" for a in AXES],
    "axis_aligned_bounding_box": [f"min {a} (nm)" for a in AXES] + [f"max {a} (nm)" for a in AXES],
    "ellipsoid": [f"center {a} (nm)" for a in AXES] + [f"radius {a} (nm)" for a in AXES],
    "polyline": ["vertex"] + [f"{a} (nm)" for a in AXES],
    "point": [f"{a} (nm)" for a in AXES],
}
# Neuroglancer's field for each coordinate group, per type
FIELDS = {
    "line": (("pointA", "start "), ("pointB", "end ")),
    "point": (("point", ""),),
    "axis_aligned_bounding_box": (("pointA", "min "), ("pointB", "max ")),
    "ellipsoid": (("center", "center "), ("radii", "radius ")),
}
NUMERIC_PROPS = {"uint8", "int8", "uint16", "int16", "uint32", "int32", "float32"}


def kind_of(columns: list[str]) -> str | None:
    cols = set(columns)
    return next((k for k, req in REQUIRED.items() if set(req) <= cols), None)


def number(row: dict, col: str, where: str) -> float:
    v = (row.get(col) or "").strip()
    try:
        return float(v)
    except ValueError:
        _fail(f"{where}: {col!r} is {v!r}, which is not a number")


def read_files(paths: list[str]) -> tuple[list[dict], list[str], list[str]]:
    """Return (records, links, unread columns). A record is one annotation:
    kind, layer, id, coords {field: [z, y, x] nm}, description, segments, extra."""
    records, links, unread = [], [], []
    for path in paths:
        with open(path, newline="", encoding="utf-8-sig") as f:   # -sig: Excel's byte-order mark
            reader = csv.DictReader(f)
            cols = reader.fieldnames or []
            kind = kind_of(cols)
            if not kind:
                _fail(f"{path}: these columns are not an exported annotation file: {cols}")
            known = set(HEAD + SHAPE_COLUMNS[kind] + TAIL)
            extra_cols = [c for c in cols if c not in known]
            polylines: dict = {}
            open_key, unnamed = None, 0
            for n, row in enumerate(reader, 2):        # line 1 is the header
                row.pop(None, None)                    # fields beyond the header, e.g. trailing commas
                if not any((v or "").strip() for v in row.values()):
                    continue                           # a blank row left by a spreadsheet
                where = f"{path}, row {n}"
                if (row.get("neuroglancer url") or "").strip():
                    links.append(row["neuroglancer url"].strip())
                segs = [s.strip() for s in (row.get("segments") or "").split(";") if s.strip()]
                rec = {"kind": kind, "layer": (row.get("layer") or "").strip() or "annotations",
                       "id": (row.get("id") or "").strip(),
                       "description": row.get("description") or "", "segments": segs,
                       "extra": {c: row.get(c) or "" for c in extra_cols}}
                if kind == "polyline":
                    p = [number(row, f"{a} (nm)", where) for a in AXES]
                    v = number(row, "vertex", where)
                    # rows of one polyline share an id; without ids, vertex 1 starts a new one
                    if rec["id"]:
                        key = (rec["layer"], rec["id"])
                    else:
                        if v == 1 or open_key is None:
                            unnamed += 1
                            open_key = (rec["layer"], None, unnamed)
                        key = open_key
                    if key not in polylines:
                        rec["coords"] = {"points": []}
                        polylines[key] = rec
                        records.append(rec)
                    polylines[key]["coords"]["points"].append((v, p))
                else:
                    rec["coords"] = {fld: [number(row, f"{pre}{a} (nm)", where) for a in AXES]
                                     for fld, pre in FIELDS[kind]}
                    records.append(rec)
            unread += [c for c in extra_cols if c not in unread]
    for rec in records:      # vertices in order of their number, then drop the number
        if rec["kind"] == "polyline":
            rec["coords"]["points"] = [p for _, p in sorted(rec["coords"]["points"], key=lambda t: t[0])]
    return records, links, unread


def prop_value(text: str, prop: dict):
    if not text.strip():
        return prop.get("default", 0 if prop.get("type") in NUMERIC_PROPS else "")
    if prop.get("type") in NUMERIC_PROPS:
        x = float(text)
        return x if prop["type"] == "float32" else int(math.floor(x + 0.5))
    return text


def to_layer_units(p: list[float], axes: list[tuple[str, float]], radius: bool = False) -> list[float]:
    """[z, y, x] in nm -> the layer's own axes and units. An axis other than
    z, y, x (time, channel) gets 0; radii are kept positive."""
    nm = dict(zip(AXES, p))
    out = []
    for a, s in axes:
        v = nm[a] / s if a in nm else 0.0
        out.append(abs(v) if radius else v)
    return out


def build(records: list[dict], state: dict) -> tuple[dict, list[str], set]:
    """Put the records into `state` (changed in place).
    Returns (state, notes, the extra columns that were restored as properties)."""
    notes, used_cols = [], set()
    layers = state.setdefault("layers", [])
    order = list(dict.fromkeys(r["layer"] for r in records))
    for name in order:
        recs = [r for r in records if r["layer"] == name]
        kinds = {r["kind"] for r in recs}
        layer = next((l for l in layers if l.get("type") == "annotation" and l.get("name") == name
                      and isinstance(l.get("annotations"), list)), None)
        if layer is not None:
            src = layer.get("source")
            dims = (src.get("transform") or {}).get("outputDimensions") if isinstance(src, dict) else None
            dims = dims or state.get("dimensions") or NM_SPACE
            kept = [a for a in layer["annotations"] if a.get("type") not in kinds]
            words = ", ".join(TYPES[k][2] for k in TYPES if k in kinds)
            notes.append(f"layer {name!r}: replaced its {words}"
                         + (f", kept {len(kept)} other annotation{'' if len(kept) == 1 else 's'}"
                            if kept else ""))
        else:
            layer = {"type": "annotation", "name": name,
                     "source": {"url": "local://annotations", "transform": {"outputDimensions": NM_SPACE}},
                     "tab": "annotations", "annotations": []}
            layers.append(layer)
            dims, kept = NM_SPACE, []
            notes.append(f"layer {name!r}: new")
        axes = nm_per_unit(dims)
        props = layer.get("annotationProperties") or []
        used = {str(a.get("id")) for a in kept}
        anns = []
        for i, r in enumerate(recs, 1):
            ann = {"type": r["kind"]}
            if r["kind"] == "polyline":
                ann["points"] = [to_layer_units(p, axes) for p in r["coords"]["points"]]
            else:
                for fld, val in r["coords"].items():
                    ann[fld] = to_layer_units(val, axes, radius=(fld == "radii"))
                if r["kind"] == "axis_aligned_bounding_box":   # min and max, in layer order
                    a, b = ann["pointA"], ann["pointB"]
                    ann["pointA"], ann["pointB"] = [min(x, y) for x, y in zip(a, b)], [max(x, y) for x, y in zip(a, b)]
            # ids must be unique in a layer; a missing or repeated one gets a numbered id
            aid = r["id"] or f"{r['kind']}-{i}"
            while aid in used:
                aid += "+"
            used.add(aid)
            ann["id"] = aid
            if r["description"]:
                ann["description"] = r["description"]
            if r["segments"]:
                ann["segments"] = [r["segments"]]
            if props:
                base = HEAD + SHAPE_COLUMNS[r["kind"]] + TAIL
                ann["props"] = []
                for j, p in enumerate(props):
                    pid = str(p.get("id", f"property {j + 1}"))
                    col = pid if pid not in base else f"{pid} (property)"
                    if col in r["extra"]:
                        used_cols.add(col)
                    ann["props"].append(prop_value(r["extra"].get(col, ""), p))
            anns.append(ann)
        layer["annotations"] = kept + anns
    return state, notes, used_cols


def centre(records: list[dict]) -> dict:
    """The middle of everything loaded, in nm per axis."""
    pts = []
    for r in records:
        for fld, val in r["coords"].items():
            if fld == "points":
                pts += val
            elif fld != "radii":
                pts.append(val)
    return {a: (min(p[i] for p in pts) + max(p[i] for p in pts)) / 2 for i, a in enumerate(AXES)}


def write_csv(path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, restval="")
        w.writeheader()
        w.writerows(rows)


def count(kind: str, rows: list[dict]) -> int:
    """Annotations in a table (a polyline is one row per vertex)."""
    return len({(r["layer"], r["id"]) for r in rows}) if kind == "polyline" else len(rows)


def to_link(records: list[dict], links: list[str], base: str | None = None,
            bare: bool = False) -> tuple[str, dict, str, list[str], set]:
    """Build a Neuroglancer link holding `records`.

    Shown on `base` (a link, file or JSON state) if given; otherwise on the view
    saved in the spreadsheets' "neuroglancer url" column, unless `bare`, in which
    case the annotations are shown on their own. Returns (link, state, what they
    were shown on, notes, extra columns restored as properties)."""
    if not records:
        _fail("Those files have no annotations in them.")
    host, keep_view = NG_HOST, True
    if base:
        state, link = load_state(base)
        on = "the link given"
    elif links and not bare:
        state, link = load_state(links[0])
        on = "the view saved in the spreadsheet"
        if len(set(links)) > 1:
            on += " (the first of several links in the files)"
    else:
        state, link, keep_view = {"dimensions": dict(NM_SPACE), "layers": [], "layout": "4panel"}, "", False
        on = "nothing else" if bare else "nothing else (no link in the spreadsheet)"
    if link and "#!" in link:
        host = link.split("#!", 1)[0]
    state, notes, used_cols = build(records, state)
    if not keep_view:   # a fresh view: centre it on the annotations
        c = centre(records)
        state["position"] = [c[a] / s if a in c else 0.0 for a, s in nm_per_unit(state["dimensions"])]
        state["selectedLayer"] = {"layer": records[0]["layer"], "visible": True}
    url = host + "#!" + quote(json.dumps(state, separators=(",", ":")), safe="")
    return url, state, on, notes, used_cols
