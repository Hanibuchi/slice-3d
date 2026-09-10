"""slice3d: a library that slices a 3D model at regular intervals and exports the cross-sections.

Minimal usage::

    import slice3d

    mesh = slice3d.load_mesh("model.stl")
    for s in slice3d.iter_slices(mesh, axis="z", thickness=1.0):
        if not s.is_empty:
            slice3d.save_section(s.path_2d, f"out/{s.index:04d}.svg")

Or in one call::

    import slice3d

    slice3d.slice_file("model.stl", "out", axis="z", thickness=1.0, fmt="svg")
"""

from .core import (
    AXES,
    Slice,
    compute_heights,
    iter_slices,
    load_mesh,
    polylines,
    print_volume,
    save_section,
    slice_file,
    slice_mesh,
)

__version__ = "0.1.1"

__all__ = [
    "AXES",
    "Slice",
    "compute_heights",
    "iter_slices",
    "load_mesh",
    "polylines",
    "print_volume",
    "save_section",
    "slice_file",
    "slice_mesh",
    "__version__",
]
