"""ライブラリ使用例: アンモナイトのGLBモデルの体積を計算する。

実行方法::

    python examples/volume_ammonite.py
"""

from pathlib import Path

import trimesh

import slice3d

HERE = Path(__file__).parent


def main() -> None:
    mesh = slice3d.load_mesh(HERE / "ammonite.glb")

    print(f"頂点数: {len(mesh.vertices)}")
    print(f"面数: {len(mesh.faces)}")
    print(f"バウンディングボックス(m): {mesh.extents}")

    if not mesh.is_watertight:
        print("警告: メッシュが閉じていません (is_watertight=False)。穴埋め・法線修正を試みます…")
        mesh.merge_vertices()
        mesh.update_faces(mesh.unique_faces())
        mesh.remove_unreferenced_vertices()
        trimesh.repair.fix_normals(mesh)
        trimesh.repair.fill_holes(mesh)
        if mesh.is_watertight:
            print("修復に成功しました。")
        else:
            print("修復後も完全には閉じていません。以下の体積は近似値です。")

    volume_m3 = abs(mesh.volume)
    print(f"体積: {volume_m3:.6e} m^3 ({volume_m3 * 1e6:.4f} cm^3)")

    hull_volume_m3 = mesh.convex_hull.volume
    print(f"(参考) 凸包の体積: {hull_volume_m3:.6e} m^3 ({hull_volume_m3 * 1e6:.4f} cm^3)")


if __name__ == "__main__":
    main()
