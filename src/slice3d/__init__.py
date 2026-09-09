"""slice3d: 3Dモデルを一定間隔でスライスして断面を出力するライブラリ。

最小の使用例::

    import slice3d

    mesh = slice3d.load_mesh("model.stl")
    for s in slice3d.iter_slices(mesh, axis="z", thickness=1.0):
        if not s.is_empty:
            slice3d.save_section(s.path_2d, f"out/{s.index:04d}.svg")

または一括処理::

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

__version__ = "0.1.0"

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
