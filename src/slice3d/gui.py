"""GUI viewer for checking a 3D model's cross-sections and volume.

Opens a dedicated window where you can see the whole model and the current
cutting position in a 3D view, and switch between cross-sections with a slider.
The axis (x/y/z) and slice spacing (thickness) can be changed in the window.

Usage::

    slice3d-gui model.stl
    slice3d-gui model.stl --axis x --thickness 0.01
    slice3d-gui model.glb              # glTF/GLB are meters by spec, so "m" is shown automatically
    slice3d-gui model.stl --units mm   # for formats like STL with no known unit, specify it explicitly

Requires matplotlib (``pip install "slice3d[gui]"``).
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import trimesh
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, RadioButtons, Slider, TextBox
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from . import core


def _pick_cjk_font() -> str | None:
    """Pick one CJK-capable font installed on the system (to avoid mojibake)."""
    import matplotlib.font_manager as fm

    available = {f.name for f in fm.fontManager.ttflist}
    for candidate in ("Hiragino Sans", "Yu Gothic", "Meiryo", "Noto Sans CJK JP", "IPAexGothic"):
        if candidate in available:
            return candidate
    return None


_cjk_font = _pick_cjk_font()
if _cjk_font:
    plt.rcParams["font.family"] = [_cjk_font, "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# To keep the 3D preview from getting heavy, simplify the mesh once its face count
# exceeds this. mplot3d gets slower to rotate/redraw roughly in proportion to face
# count, so capping it at a few thousand faces keeps things smooth.
# (Slice computation itself always uses the original mesh's full precision; this
# simplification only affects the 3D preview.)
_MAX_PREVIEW_FACES = 4_000

# glTF/GLB are meters by spec, so that's used as the default display unit.
# Formats like STL/OBJ/PLY carry no unit information, so their default is no unit (empty string).
_UNITS_BY_EXTENSION = {".glb": "m", ".gltf": "m"}

_AXIS_NAMES = ("x", "y", "z")
_FORMATS = ("svg", "png", "dxf", "csv")


def _default_units(model_path: Path) -> str:
    return _UNITS_BY_EXTENSION.get(model_path.suffix.lower(), "")


def _nice_thickness(extent: float, target_slices: int = 30) -> float:
    """Pick a round thickness value (1/2/5 x 10^n) that divides extent into about target_slices slices."""
    raw = extent / target_slices
    if raw <= 0:
        return max(raw, 1e-9)
    magnitude = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        candidate = m * magnitude
        if candidate >= raw:
            return candidate
    return 10 * magnitude


class SliceViewer:
    """A matplotlib window combining a 3D view with a slider to browse cross-sections."""

    def __init__(
        self,
        model_path: str | Path,
        axis: str = "z",
        thickness: float | None = None,
        max_preview_faces: int = _MAX_PREVIEW_FACES,
        units: str | None = None,
        fmt: str = "svg",
    ):
        self.model_path = Path(model_path)
        self.mesh = core.load_mesh(self.model_path)
        self.axis = axis
        self.volume = float(self.mesh.volume)
        self.max_preview_faces = max_preview_faces
        self.units = _default_units(self.model_path) if units is None else units
        if fmt not in _FORMATS:
            raise ValueError(f"fmt must be one of {list(_FORMATS)}: {fmt!r}")
        self.format = fmt
        self._format_buttons: dict[str, Button] = {}

        if thickness is None:
            extent = self.mesh.extents[core.AXES[axis]]
            thickness = _nice_thickness(extent)
        self.thickness = thickness

        self.heights = None
        self.slider = None
        self._plane_artist = None
        self._curve_lines: list = []

        self._build_ui()
        self._recompute_slices()

    # ---- display formatting ----
    # Round to 3 significant figures (a raw float has too many digits to read comfortably).
    def _fmt_length(self, value: float) -> str:
        suffix = f" {self.units}" if self.units else ""
        return f"{value:.3g}{suffix}"

    def _fmt_volume(self, value: float) -> str:
        suffix = f" {self.units}³" if self.units else ""
        return f"{value:.3g}{suffix}"

    # ---- data ----
    def _recompute_slices(self) -> None:
        self.heights = core.compute_heights(self.mesh, self.axis, self.thickness)
        self._rebuild_slider()

    def _section_at(self, index: int):
        """Compute the cross-section at the given index. Returns (path_2d, discrete_3d).

        path_2d is the Path2D on the 2D plane (None if there's no intersection);
        discrete_3d is a list of polylines (Nx3 arrays) for the 3D preview.

        Using polylines() (the entity-based extraction from core.py) picks up every
        line without loss, including open (non-closed) lines such as those found in
        cross-sections of a non-watertight mesh. ``section.discrete`` is avoided
        because it only returns closed loops.
        """
        axis_idx = core.AXES[self.axis]
        normal = [0.0, 0.0, 0.0]
        normal[axis_idx] = 1.0
        origin = self.mesh.bounds[0].copy()
        origin[axis_idx] = self.heights[index]
        section = self.mesh.section(plane_origin=origin, plane_normal=normal)
        if section is None:
            return None, []
        path_2d, _transform = section.to_2D()
        return path_2d, core.polylines(section)

    def _plane_corners(self, index: int) -> np.ndarray:
        axis_idx = core.AXES[self.axis]
        h = self.heights[index]
        other = [i for i in range(3) if i != axis_idx]
        b = self.mesh.bounds
        lo0, hi0 = b[0, other[0]], b[1, other[0]]
        lo1, hi1 = b[0, other[1]], b[1, other[1]]
        corners = np.zeros((4, 3))
        for k, (a, c) in enumerate(((lo0, lo1), (hi0, lo1), (hi0, hi1), (lo0, hi1))):
            corners[k, axis_idx] = h
            corners[k, other[0]] = a
            corners[k, other[1]] = c
        return corners

    # ---- build UI ----
    def _build_ui(self) -> None:
        self.fig = plt.figure(figsize=(11, 9))
        try:
            self.fig.canvas.manager.set_window_title(f"slice3d viewer - {self.model_path.name}")
        except AttributeError:
            pass

        self.ax_3d = self.fig.add_axes((0.03, 0.34, 0.45, 0.55), projection="3d")
        self._draw_static_mesh()

        self.ax_section = self.fig.add_axes((0.55, 0.34, 0.43, 0.55))
        self.ax_section.set_aspect("equal")
        self.ax_section.set_title("Cross-section (view along slicing axis)", fontsize=10)

        watertight_note = "" if self.mesh.is_watertight else "  (non-watertight: volume is approximate)"
        self.fig.text(
            0.02, 0.975,
            f"{self.model_path.name}   volume = {self._fmt_volume(self.volume)}{watertight_note}",
            fontsize=10, va="top",
        )
        self.pos_text = self.fig.text(0.02, 0.95, "", fontsize=10, va="top")
        self.fig.text(
            0.03, 0.92, "Full model (red = current slice plane)", fontsize=10, va="top"
        )

        # The radio buttons' default marker size and click target are too small to
        # hit comfortably, so we give them a wider dedicated area and enlarge the
        # marker and font via radio_props/label_props.
        ax_radio = self.fig.add_axes((0.01, 0.02, 0.13, 0.27))
        ax_radio.set_title("Axis", fontsize=11)
        self.radio = RadioButtons(
            ax_radio,
            ("x", "y", "z"),
            active="xyz".index(self.axis),
            radio_props={"s": 160},
            label_props={"fontsize": [14, 14, 14]},
        )
        self.radio.on_clicked(self._on_axis_change)

        self.ax_slider = self.fig.add_axes((0.19, 0.25, 0.71, 0.05))
        # The slider handle is also hard to grab at its default size, so enlarge it
        # (the track itself can already be clicked anywhere to jump to that position).
        self._slider_handle_style = {"size": 18}

        thickness_label = f"Thickness ({self.units})  " if self.units else "Thickness  "
        ax_thickness = self.fig.add_axes((0.19, 0.16, 0.18, 0.06))
        self.thickness_box = TextBox(ax_thickness, thickness_label, initial=f"{self.thickness:g}")
        self.thickness_box.text_disp.set_fontsize(12)
        self.thickness_box.label.set_fontsize(11)
        self.thickness_box.on_submit(self._on_thickness_submit)

        ax_save_current = self.fig.add_axes((0.62, 0.16, 0.28, 0.06))
        self.save_current_button = Button(ax_save_current, "")
        self.save_current_button.label.set_fontsize(11)
        self.save_current_button.on_clicked(self._on_save)

        self.fig.text(0.19, 0.10, "Format:", fontsize=10, va="center")
        format_x = (0.30, 0.44, 0.58, 0.72)
        format_width = 0.13
        for x, fmt in zip(format_x, _FORMATS):
            ax_fmt = self.fig.add_axes((x, 0.075, format_width, 0.05))
            button = Button(ax_fmt, fmt.upper())
            button.label.set_fontsize(10)
            button.on_clicked(lambda event, f=fmt: self._on_format_change(f))
            self._format_buttons[fmt] = button

        ax_save_all = self.fig.add_axes((0.19, 0.005, 0.81, 0.06))
        self.save_all_button = Button(ax_save_all, "")
        self.save_all_button.label.set_fontsize(11)
        self.save_all_button.on_clicked(self._on_save_all)

        self._refresh_format_buttons()

    def _preview_mesh(self):
        """Return a lightweight mesh for the 3D preview only (not used for slice computation)."""
        mesh = self.mesh
        if len(mesh.faces) <= self.max_preview_faces:
            return mesh
        try:
            return mesh.simplify_quadric_decimation(face_count=self.max_preview_faces)
        except Exception:
            # Fallback for environments without fast_simplification, etc.: simple
            # decimation. The shape looks coarser, but that beats a frozen display.
            step = math.ceil(len(mesh.faces) / self.max_preview_faces)
            faces = mesh.faces[::step]
            return trimesh.Trimesh(vertices=mesh.vertices, faces=faces, process=False)

    def _draw_static_mesh(self) -> None:
        """Draw the whole model once as a semi-transparent 3D surface (not redrawn on slice operations)."""
        preview = self._preview_mesh()
        tri = preview.vertices[preview.faces]

        surface = Poly3DCollection(tri, alpha=0.25, facecolor="lightsteelblue", edgecolor="none")
        self.ax_3d.add_collection3d(surface)

        b = self.mesh.bounds
        self.ax_3d.set_xlim(b[0, 0], b[1, 0])
        self.ax_3d.set_ylim(b[0, 1], b[1, 1])
        self.ax_3d.set_zlim(b[0, 2], b[1, 2])
        extents = np.maximum(self.mesh.extents, 1e-9)
        self.ax_3d.set_box_aspect(tuple(extents))
        self.ax_3d.set_xlabel("x", fontsize=8)
        self.ax_3d.set_ylabel("y", fontsize=8)
        self.ax_3d.set_zlabel("z", fontsize=8)

    def _update_3d_highlight(self, index: int, discrete_3d) -> None:
        if self._plane_artist is not None:
            self._plane_artist.remove()
            self._plane_artist = None
        for line in self._curve_lines:
            line.remove()
        self._curve_lines = []

        corners = self._plane_corners(index)
        plane = Poly3DCollection([corners], alpha=0.15, facecolor="tomato", edgecolor="none")
        self.ax_3d.add_collection3d(plane)
        self._plane_artist = plane

        for polyline in discrete_3d:
            (line,) = self.ax_3d.plot(
                polyline[:, 0], polyline[:, 1], polyline[:, 2], color="red", linewidth=2
            )
            self._curve_lines.append(line)

    def _rebuild_slider(self) -> None:
        n = len(self.heights)
        current = 0 if self.slider is None else min(int(self.slider.val), n - 1)
        self.ax_slider.clear()
        self.slider = Slider(
            self.ax_slider,
            "slice",
            0,
            max(n - 1, 0),
            valinit=current,
            valstep=1,
            handle_style=self._slider_handle_style,
        )
        self.slider.label.set_fontsize(11)
        self.slider.on_changed(lambda val: self._show_index(int(val)))
        self._show_index(current)

    # ---- callbacks ----
    def _on_axis_change(self, label: str) -> None:
        self.axis = label
        self.thickness = _nice_thickness(self.mesh.extents[core.AXES[label]])
        self.thickness_box.set_val(f"{self.thickness:g}")
        self._recompute_slices()
        self._refresh_format_buttons()  # refresh since the Save All button label includes the axis name
        self.fig.canvas.draw_idle()

    def _on_thickness_submit(self, text: str) -> None:
        try:
            thickness = float(text)
        except ValueError:
            return
        if thickness <= 0:
            return
        self.thickness = thickness
        self._recompute_slices()
        self.fig.canvas.draw_idle()

    def _on_format_change(self, fmt: str) -> None:
        self.format = fmt
        self._refresh_format_buttons()
        self.fig.canvas.draw_idle()

    def _refresh_format_buttons(self) -> None:
        """Highlight the currently selected format's button and update the save buttons' labels."""
        for fmt, button in self._format_buttons.items():
            selected = fmt == self.format
            button.color = "lightblue" if selected else "0.85"
            button.hovercolor = "skyblue" if selected else "0.95"
            button.ax.set_facecolor(button.color)
        self.save_current_button.label.set_text(f"Save Current Slice ({self.format.upper()})")
        self.save_all_button.label.set_text(f"Save All Slices Along {self.axis.upper()}-Axis ({self.format.upper()})")

    def _outdir(self) -> Path:
        outdir = self.model_path.parent / "slices_gui"
        outdir.mkdir(exist_ok=True)
        return outdir

    def _on_save(self, event) -> None:
        index = int(self.slider.val)
        path_2d, discrete_3d = self._section_at(index)
        if path_2d is None:
            print("Cannot save: no intersection at this slice position")
            return
        outdir = self._outdir()
        outpath = outdir / f"{self.model_path.stem}_{self.axis}{index:04d}_{self.heights[index]:.4f}.{self.format}"
        # Passing polylines_3d/axis/bounds fixes the saved image's (PNG) view range
        # to the whole model's bounding box, so the scale doesn't vary between sections.
        core.save_section(
            path_2d, outpath, self.format,
            polylines_3d=discrete_3d, axis=self.axis, bounds=self.mesh.bounds,
        )
        print(f"Saved: {outpath}")

    def _on_save_all(self, event) -> None:
        """Save all slices in one go using the current axis/thickness settings (positions with no intersection are skipped)."""
        outdir = self._outdir()
        written = core.slice_file(
            self.model_path,
            outdir,
            axis=self.axis,
            thickness=self.thickness,
            fmt=self.format,
        )
        print(
            f"Saved {len(written)}/{len(self.heights)} slices "
            f"(axis={self.axis}, thickness={self._fmt_length(self.thickness)}, format={self.format}) to {outdir}"
        )

    # ---- rendering ----
    def _show_index(self, index: int) -> None:
        index = max(0, min(index, len(self.heights) - 1))
        position = self.heights[index]
        path_2d, discrete_3d = self._section_at(index)

        self._update_3d_highlight(index, discrete_3d)

        # The cross-section panel is drawn by projecting the same world coordinates
        # (discrete_3d) used for the 3D highlight onto the two remaining axes.
        # Using path_2d (the local 2D coordinate system trimesh picks per section)
        # instead would auto-scale to the section's shape alone, blowing small
        # fragments up to fill the panel and losing correspondence with the 3D view
        # (most noticeable when slicing along a thin axis).
        # Here the view range is fixed to the whole model's bounding box instead,
        # so the scale is always consistent.
        axis_idx = core.AXES[self.axis]
        other = [i for i in range(3) if i != axis_idx]
        xlabel, ylabel = _AXIS_NAMES[other[0]], _AXIS_NAMES[other[1]]

        self.ax_section.clear()
        self.ax_section.set_aspect("equal")
        self.ax_section.set_title("Cross-section (view along slicing axis)", fontsize=10)
        self.ax_section.set_xlabel(xlabel, fontsize=9)
        self.ax_section.set_ylabel(ylabel, fontsize=9)
        b = self.mesh.bounds
        self.ax_section.set_xlim(b[0, other[0]], b[1, other[0]])
        self.ax_section.set_ylim(b[0, other[1]], b[1, other[1]])
        if not discrete_3d:
            self.ax_section.text(
                0.5, 0.5, "No intersection", ha="center", va="center", transform=self.ax_section.transAxes
            )
        else:
            for polyline in discrete_3d:
                self.ax_section.plot(polyline[:, other[0]], polyline[:, other[1]], "-k")

        self.pos_text.set_text(
            f"axis={self.axis}  thickness={self._fmt_length(self.thickness)}  "
            f"slice={index + 1}/{len(self.heights)}  position={self._fmt_length(position)}"
        )
        self.fig.canvas.draw_idle()

    def show(self) -> None:
        plt.show()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="slice3d-gui", description="Interactive GUI viewer for a 3D model's volume and slices"
    )
    parser.add_argument("model", type=Path, help="input 3D model file (STL/OBJ/PLY/GLB, etc.)")
    parser.add_argument("--axis", choices=tuple(core.AXES), default="z", help="initial slicing axis")
    parser.add_argument(
        "--thickness",
        type=float,
        default=None,
        help='initial slice spacing (a.k.a. "slice thickness"); '
        "default: a round number giving roughly 30 slices across the model",
    )
    parser.add_argument(
        "--units",
        type=str,
        default=None,
        help='length unit label to display next to values, e.g. "m" or "mm". '
        'Defaults to "m" for glTF/GLB files (meters by spec) and no unit otherwise; '
        'pass --units "" to force no unit label.',
    )
    parser.add_argument(
        "--max-preview-faces",
        type=int,
        default=_MAX_PREVIEW_FACES,
        help=f"max face count for the 3D preview mesh (default: {_MAX_PREVIEW_FACES}); "
        "lower this if the 3D view feels slow",
    )
    parser.add_argument(
        "--format",
        choices=_FORMATS,
        default="svg",
        help="initial export format for the Save buttons (default: svg); "
        "can also be changed in the window",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    viewer = SliceViewer(
        args.model,
        axis=args.axis,
        thickness=args.thickness,
        max_preview_faces=args.max_preview_faces,
        units=args.units,
        fmt=args.format,
    )
    viewer.show()


if __name__ == "__main__":
    main()
