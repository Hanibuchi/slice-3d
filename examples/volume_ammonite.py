"""Library usage example: compute the volume of an ammonite GLB model.

Run with::

    python examples/volume_ammonite.py
"""

from pathlib import Path

import trimesh

import slice3d

HERE = Path(__file__).parent


def main() -> None:
    mesh = slice3d.load_mesh(HERE / "ammonite.glb")

    print(f"Vertices: {len(mesh.vertices)}")
    print(f"Faces: {len(mesh.faces)}")
    print(f"Bounding box (m): {mesh.extents}")

    if not mesh.is_watertight:
        print("Warning: mesh is not closed (is_watertight=False). Attempting to fill holes and fix normals…")
        mesh.merge_vertices()
        mesh.update_faces(mesh.unique_faces())
        mesh.remove_unreferenced_vertices()
        trimesh.repair.fix_normals(mesh)
        trimesh.repair.fill_holes(mesh)
        if mesh.is_watertight:
            print("Repair succeeded.")
        else:
            print("Still not fully closed after repair. The volume below is an approximation.")

    volume_m3 = abs(mesh.volume)
    print(f"Volume: {volume_m3:.6e} m^3 ({volume_m3 * 1e6:.4f} cm^3)")

    hull_volume_m3 = mesh.convex_hull.volume
    print(f"(reference) Convex hull volume: {hull_volume_m3:.6e} m^3 ({hull_volume_m3 * 1e6:.4f} cm^3)")


if __name__ == "__main__":
    main()
