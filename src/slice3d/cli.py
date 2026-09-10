"""Command-line interface for slice3d."""

from __future__ import annotations

import argparse
from pathlib import Path

from .core import AXES, load_mesh, compute_heights, iter_slices, save_section


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="slice3d",
        description="Slice a 3D model at regular intervals and export the cross-sections",
    )
    parser.add_argument("model", type=Path, help="input 3D model file (STL/OBJ/PLY/GLB, etc.)")
    parser.add_argument("--axis", choices=tuple(AXES), default="z", help="axis to slice along (default: z)")
    parser.add_argument("--thickness", type=float, default=1.0, help="slice spacing [model units] (default: 1.0)")
    parser.add_argument("--start", type=float, default=None, help="start position (default: model's minimum)")
    parser.add_argument("--end", type=float, default=None, help="end position (default: model's maximum)")
    parser.add_argument("--outdir", type=Path, default=Path("slices"), help="output directory (default: ./slices)")
    parser.add_argument(
        "--format",
        choices=("svg", "dxf", "png", "csv"),
        default="svg",
        help="cross-section output format (default: svg)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    mesh = load_mesh(args.model)
    if not mesh.is_watertight:
        print(f"Warning: mesh is not closed (is_watertight=False). Some cross-sections may be incomplete: {args.model}")

    heights = compute_heights(mesh, args.axis, args.thickness, args.start, args.end)
    print(f"Generating {len(heights)} cross-sections with axis={args.axis}, thickness={args.thickness}")

    args.outdir.mkdir(parents=True, exist_ok=True)
    stem = args.model.stem

    n_ok = 0
    for s in iter_slices(mesh, axis=args.axis, thickness=args.thickness, start=args.start, end=args.end):
        if s.is_empty:
            print(f"  [{s.index:04d}] {args.axis}={s.position:.4f}: no intersection (skipped)")
            continue
        outpath = args.outdir / f"{stem}_{args.axis}{s.index:04d}_{s.position:.4f}.{args.format}"
        save_section(s.path_2d, outpath, args.format)
        print(f"  [{s.index:04d}] {args.axis}={s.position:.4f}: {outpath.name}")
        n_ok += 1

    print(f"Done: wrote {n_ok}/{len(heights)} cross-sections to {args.outdir}")


if __name__ == "__main__":
    main()
