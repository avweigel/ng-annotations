# ng-annotations

Turn the annotations in a [Neuroglancer](https://github.com/google/neuroglancer) link into
spreadsheets, and turn those spreadsheets back into a link.

**Use it in the browser:** https://avweigel.github.io/ng-annotations/
Paste a link, download CSVs. Drop CSVs in, get a link. Nothing is uploaded; it all runs in the page.

## What you get

One CSV per annotation type, coordinates in nanometres (from the layer's coordinate space):

| Type | Columns |
| --- | --- |
| Lines | start z, y, x · end z, y, x · length |
| Points | z, y, x |
| Boxes | min z, y, x · max z, y, x · size z, y, x |
| Ellipsoids | center z, y, x · radius z, y, x |
| Polylines | one row per vertex: vertex, z, y, x, distance along |

Every file starts with `layer` and `id`, and ends with `segments` (linked segment IDs, joined
with `;`), `neuroglancer url`, `description`, and one column per annotation property the layer
defines.

Edit the CSVs if you like (move points, delete rows, add rows), then load them back: they
replace the annotations of the same type in a layer of the same name and leave everything else
in the view alone.

## Command line

Python 3.9 or newer, no other dependencies.

```bash
pip install git+https://github.com/avweigel/ng-annotations

pbpaste | ng-annotations export - out.csv       # link on the clipboard (macOS) -> CSVs
ng-annotations export 'LINK' out.csv            # or a link in single quotes, a file, or JSON state
ng-annotations load out.csv out_points.csv      # CSVs -> a link (printed)
ng-annotations load out.csv --base 'LINK'       # ... added to another view
ng-annotations load out.csv --bare              # ... on their own
```

`export` writes lines to `out.csv` and the other types beside it (`out_points.csv`,
`out_boxes.csv`, ...). Put pasted links in single quotes: they contain `#!`, which zsh and bash
treat as history expansion inside double quotes.

From Python:

```python
from ng_annotations import load_state, extract
state, link = load_state("https://neuroglancer-demo.appspot.com/#!...")
tables, skipped = extract(state, link)
tables["line"]["rows"][0]["length (nm)"]
```

## Notes

- Annotations live in the link itself, in everything after `#!`. Copying the address is how
  you save them in Neuroglancer; copy it again after any change.
- Only local annotation layers (annotations stored in the link) are read. A link that points
  at a saved state file (`#!gs://...`, `#!https://...`) doesn't carry the annotations: open it
  in Neuroglancer and copy the JSON with the `{ }` button instead.
- The browser page (`docs/index.html`) and the Python package write identical files. If you
  change one, change the other.

## Credits

- The lines file uses the CSV columns of David Ackerman's
  [annotation-processing-utils](https://github.com/davidackerman/annotation-processing-utils)
  (`start z (nm)` ... `end x (nm)`, `neuroglancer url`), so exported lines go straight into
  that pipeline.
- The annotation workflow this supports builds on Jacquelyn Price's nuclear pore annotation
  protocol (CellMap, HHMI Janelia).
- [Neuroglancer](https://github.com/google/neuroglancer) is by Google.

## Licence

MIT. See [LICENSE](LICENSE).
