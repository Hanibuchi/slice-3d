# slice3d

A Python library/CLI that slices a 3D model (STL / OBJ / PLY / GLB / GLTF, etc.) at regular intervals and exports the cross-sections (outlines) as SVG / DXF / PNG / CSV. Built on [trimesh](https://github.com/mikedh/trimesh).

An example slicing an ammonite fossil model along the X axis:

![Slice grid](docs/assets/ammonite_slices_grid.png)

A cross-section near the center (showing the spiral chambers clearly):

![Center slice](docs/assets/ammonite_center_slice.png)

## Installation

```bash
pip install slice3d

# For PNG output (requires matplotlib)
pip install "slice3d[viz]"
```

For development, install this repository as an editable install.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Using the CLI

```bash
slice3d model.stl --axis z --thickness 2.0 --outdir slices --format svg
```

| Option | Description | Default |
| --- | --- | --- |
| `--axis {x,y,z}` | Axis to slice along | `z` |
| `--thickness` | Slice spacing (model units) | `1.0` |
| `--start` / `--end` | Slice range (defaults to the model's whole bounding box) | none |
| `--outdir` | Output directory | `./slices` |
| `--format {svg,dxf,png,csv}` | Cross-section output format | `svg` |

PNG output (shared by the CLI, `slice_file`, and the GUI) is saved with a fixed view range based on the original model's whole bounding box, rather than auto-fitting to each cross-section's content. As a result, every image from the same slicing run has the same pixel size and scale — smaller cross-sections appear smaller and larger ones appear larger, preserving their actual size ratio relative to the original model.

Slices with no intersection are skipped automatically.

## GUI viewer

Opens a dedicated window where you can check the volume and slice position, and change the axis or slice spacing (thickness) on the fly.

```bash
pip install "slice3d[gui]"
slice3d-gui model.stl
slice3d-gui model.stl --axis x --thickness 0.01
slice3d-gui model.glb              # glTF/GLB are meters by spec, so "m" is shown automatically
slice3d-gui model.stl --units mm   # for formats like STL with no known unit, specify it explicitly
slice3d-gui model.stl --format png # initial format for the Save buttons (default: svg)
```

![GUI viewer](docs/assets/gui_screenshot.png)

Everything in the window (volume, axis, numbers, etc.) is displayed in English.

- The model name and volume (`mesh.volume`; noted as approximate if non-watertight) are shown at the top of the window
- A semi-transparent 3D view of the whole model on the left, with the current cutting position overlaid as a red plane and the cross-section's outline, so you can see at a glance where and in which orientation it's being cut
- The cross-section itself (the cut viewed straight-on, in 2D) shown live on the right
- A slider to switch the slice position (index / position)
- `Axis` radio buttons to switch the slicing axis (switching auto-resets thickness to a round value based on the axis's full extent — 1/2/5 × 10ⁿ, roughly 30 divisions)
- A `Thickness` text box to set the spacing and press Enter → the number of cross-sections is recalculated
- Volume, thickness, and position values are shown with a unit. glTF/GLB (`.glb` / `.gltf`) are meters by spec, so `m` is added automatically; formats like STL/OBJ/PLY carry no unit information, so no unit is shown by default
  - `--units` (e.g. `mm`, `cm`) lets you specify the displayed unit explicitly. Pass `--units ""` to show no unit
- `Format` buttons (SVG/PNG/DXF/CSV) to choose the save format. The selected format is highlighted and reflected in the Save buttons' labels
- `Save Current Slice` button to save the currently displayed cross-section
- `Save All Slices Along <axis>-Axis` button to save every cross-section in one go using the current axis/thickness settings (positions with no intersection are skipped automatically)
- Both save to `<same directory as the model>/slices_gui/`

## Using it as a library

```python
import slice3d

# Batch mode: load a model, slice it, and write it out to a directory
written = slice3d.slice_file("model.stl", "out", axis="z", thickness=1.0, fmt="svg")

# For finer control
mesh = slice3d.load_mesh("model.stl")
for s in slice3d.iter_slices(mesh, axis="z", thickness=1.0):
    if s.is_empty:
        continue
    print(s.index, s.position, len(s.path_2d.discrete))
    slice3d.save_section(s.path_2d, f"out/{s.index:04d}.svg")
```

### API

- `slice3d.load_mesh(path)` — load a 3D model and return a `trimesh.Trimesh`
- `slice3d.compute_heights(mesh, axis, thickness, start=None, end=None)` — compute the array of slice positions
- `slice3d.iter_slices(mesh, axis="z", thickness=1.0, start=None, end=None)` — an iterator that yields `Slice` objects one at a time
- `slice3d.slice_mesh(...)` — get the result of `iter_slices` as a list
- `slice3d.save_section(path_2d, outpath, fmt=None)` — save a single cross-section (`fmt` is inferred from the extension if omitted)
- `slice3d.print_volume(mesh)` — print the mesh's volume to stdout and return the value
- `slice3d.slice_file(model_path, outdir, axis="z", thickness=1.0, start=None, end=None, fmt="svg")` — load, slice, and save in one call

`Slice` is a dataclass with `index`, `axis`, `position`, `path_2d` (`trimesh.path.Path2D | None`), and `is_empty`.

## Example

```bash
python examples/slice_ammonite.py
```

Slices `examples/ammonite.glb` along the X axis and writes PNGs to `examples/output/`.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT License. See [LICENSE](LICENSE).
