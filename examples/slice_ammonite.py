"""Library usage example: slice an ammonite GLB model along the X axis.

Run with::

    python examples/slice_ammonite.py
"""

from pathlib import Path

import slice3d

HERE = Path(__file__).parent


def main() -> None:
    written = slice3d.slice_file(
        HERE / "ammonite.glb",
        outdir=HERE / "output",
        axis="x",
        thickness=0.007,
        fmt="png",
    )
    print(f"Wrote {len(written)} cross-sections to {HERE / 'output'}")


if __name__ == "__main__":
    main()
