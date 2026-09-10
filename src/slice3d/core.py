"""Core functionality for slicing a 3D mesh at regular intervals and obtaining cross-sections (2D paths)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import numpy as np
import trimesh

__all__ = [
    "AXES",
    "Slice",
    "load_mesh",
    "compute_heights",
    "iter_slices",
    "slice_mesh",
    "save_section",
    "slice_file",
    "print_volume",
    "polylines",
]

AXES = {"x": 0, "y": 1, "z": 2}


@dataclass(frozen=True)
class Slice:
    """Represents a single cross-section."""

    index: int
    axis: str
    position: float
    path_2d: "trimesh.path.Path2D | None"
    # The cross-section's polylines in world coordinates (a list of Nx3 arrays). Used to
    # keep a consistent real-world scale when saving PNGs (path_2d uses a local 2D
    # coordinate system that trimesh picks per section, so scale isn't consistent
    # across multiple sections).
    polylines_3d: list = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return self.path_2d is None


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    """Load a 3D model file and return it as a single Trimesh.

    Supports any format trimesh can handle, e.g. STL / OBJ / PLY / GLB / GLTF.
    """
    mesh = trimesh.load(path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError(f"Could not load as a single mesh: {path}")
    return mesh


def compute_heights(
    mesh: trimesh.Trimesh,
    axis: str,
    thickness: float,
    start: float | None = None,
    end: float | None = None,
) -> np.ndarray:
    """Compute the array of slice positions at a regular interval (thickness) along the given axis."""
    if axis not in AXES:
        raise ValueError(f"axis must be one of {list(AXES)}: {axis!r}")
    if thickness <= 0:
        raise ValueError("thickness must be a positive value")

    axis_idx = AXES[axis]
    bounds_min, bounds_max = mesh.bounds[:, axis_idx]
    lo = bounds_min if start is None else start
    hi = bounds_max if end is None else end
    if hi <= lo:
        raise ValueError(f"end must be greater than start (start={lo}, end={hi})")

    n = int(np.floor((hi - lo) / thickness)) + 1
    return lo + np.arange(n) * thickness


def iter_slices(
    mesh: trimesh.Trimesh,
    axis: str = "z",
    thickness: float = 1.0,
    start: float | None = None,
    end: float | None = None,
) -> Iterator[Slice]:
    """Slice the mesh at regular intervals, yielding one Slice object at a time.

    At positions with no intersection, a Slice with ``path_2d=None`` is yielded
    (the caller can check this to skip it).
    """
    axis_idx = AXES[axis]
    heights = compute_heights(mesh, axis, thickness, start, end)

    normal = np.zeros(3)
    normal[axis_idx] = 1.0
    origin = mesh.bounds[0].copy()

    for i, h in enumerate(heights):
        plane_origin = origin.copy()
        plane_origin[axis_idx] = h
        section = mesh.section(plane_origin=plane_origin, plane_normal=normal)
        if section is None:
            yield Slice(index=i, axis=axis, position=float(h), path_2d=None)
            continue
        path_2d, _transform = section.to_2D()
        yield Slice(
            index=i,
            axis=axis,
            position=float(h),
            path_2d=path_2d,
            polylines_3d=polylines(section),
        )


def slice_mesh(
    mesh: trimesh.Trimesh,
    axis: str = "z",
    thickness: float = 1.0,
    start: float | None = None,
    end: float | None = None,
) -> list[Slice]:
    """Return the result of iter_slices as a list."""
    return list(iter_slices(mesh, axis=axis, thickness=thickness, start=start, end=end))


def polylines(path) -> list[np.ndarray]:
    """Extract every entity of a Path2D/Path3D as a list of polylines (Nx2 or Nx3 arrays).

    ``path.discrete`` only returns closed loops, so it drops open (non-closed) lines,
    such as those that occur in cross-sections of a non-watertight mesh. This function
    instead calls ``entity.discrete(path.vertices)`` per entity, so it picks up every
    segment, including open lines.
    """
    return [entity.discrete(path.vertices) for entity in path.entities]


def save_section(
    path_2d: "trimesh.path.Path2D",
    outpath: str | Path,
    fmt: str | None = None,
    *,
    polylines_3d: "list[np.ndarray] | None" = None,
    axis: str | None = None,
    bounds: "np.ndarray | None" = None,
) -> Path:
    """Save a single cross-section (Path2D) to a file.

    fmt: "svg" | "dxf" | "png" | "csv". If omitted, it's inferred from outpath's extension.

    When saving as fmt="png", passing ``polylines_3d`` (the world-coordinate polylines,
    i.e. ``Slice.polylines_3d``), ``axis``, and ``bounds`` (``mesh.bounds``) fixes the
    image's view range to the whole model's bounding box. If these are omitted, the
    image is auto-fit to that section's content alone, so the apparent scale ends up
    inconsistent from one section to another.
    """
    outpath = Path(outpath)
    fmt = (fmt or outpath.suffix.lstrip(".")).lower()

    if fmt in ("svg", "dxf"):
        data = path_2d.export(file_type=fmt)
        if isinstance(data, str):
            outpath.write_text(data)
        else:
            outpath.write_bytes(data)
    elif fmt == "png":
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        if polylines_3d is not None and axis is not None and bounds is not None:
            # Project world coordinates onto the two remaining axes as-is, and fix
            # the view range to the whole model's bounding box. This way, every
            # image is saved at the real scale relative to the original model,
            # regardless of how large that particular section is.
            axis_idx = AXES[axis]
            other = [i for i in range(3) if i != axis_idx]
            for polyline in polylines_3d:
                ax.plot(polyline[:, other[0]], polyline[:, other[1]], "-k")
            ax.set_xlim(bounds[0, other[0]], bounds[1, other[0]])
            ax.set_ylim(bounds[0, other[1]], bounds[1, other[1]])
            ax.set_aspect("equal")
            ax.axis("off")
            fig.savefig(outpath, dpi=150)
        else:
            # Fall back to auto-fitting the section's content alone (scale varies per section).
            for polyline in polylines(path_2d):
                ax.plot(polyline[:, 0], polyline[:, 1], "-k")
            ax.set_aspect("equal")
            ax.axis("off")
            fig.savefig(outpath, bbox_inches="tight", dpi=150)
        plt.close(fig)
    elif fmt == "csv":
        lines = ["polyline_id,x,y"]
        for i, polyline in enumerate(polylines(path_2d)):
            for x, y in polyline:
                lines.append(f"{i},{x},{y}")
        outpath.write_text("\n".join(lines))
    else:
        raise ValueError(f"Unsupported output format: {fmt!r} (supported: svg, dxf, png, csv)")

    return outpath


def print_volume(mesh: trimesh.Trimesh) -> float:
    """Print the mesh's volume to stdout and return the value.

    If the mesh is not watertight, prints a warning since the computed volume may be inaccurate.
    """
    if not mesh.is_watertight:
        print("Warning: mesh is not watertight, so the computed volume may be inaccurate")

    volume = float(mesh.volume)
    print(f"Volume: {volume}")
    return volume


def slice_file(
    model_path: str | Path,
    outdir: str | Path,
    axis: str = "z",
    thickness: float = 1.0,
    start: float | None = None,
    end: float | None = None,
    fmt: str = "svg",
) -> list[Path]:
    """Load a 3D model file, slice it, and write all slices to outdir.

    Returns the list of written file paths (slices with no intersection are skipped).
    """
    model_path = Path(model_path)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    mesh = load_mesh(model_path)
    stem = model_path.stem

    written: list[Path] = []
    for s in iter_slices(mesh, axis=axis, thickness=thickness, start=start, end=end):
        if s.is_empty:
            continue
        outpath = outdir / f"{stem}_{axis}{s.index:04d}_{s.position:.4f}.{fmt}"
        written.append(
            save_section(
                s.path_2d, outpath, fmt,
                polylines_3d=s.polylines_3d, axis=axis, bounds=mesh.bounds,
            )
        )
    return written
