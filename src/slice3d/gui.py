"""3Dモデルの断面・体積を確認するGUIビューア。

専用ウィンドウを開き、3D表示でモデル全体と現在の切断位置を確認しながら、
スライダーで断面を切り替えられる。軸(x/y/z)とスライス間隔(pitch)はウィンドウ上で変更できる。

使い方::

    slice3d-gui model.stl
    slice3d-gui model.stl --axis x --pitch 0.01

matplotlib が必要 (``pip install "slice3d[gui]"``)。
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
    """環境にインストールされているCJK対応フォントを1つ選ぶ(文字化け防止用)。"""
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

# 3Dプレビューが重くならないよう、面数がこれを超えたらメッシュを簡略化して表示する。
# mplot3dは面数に比例して回転・再描画が遅くなるため、数千面程度に抑えるとスムーズに動く。
# (スライス計算自体は元メッシュの精度で行われ、この簡略化は3D表示にのみ影響する)
_MAX_PREVIEW_FACES = 4_000


class SliceViewer:
    """3D表示 + スライダーで断面を切り替えながら確認するmatplotlibウィンドウ。"""

    def __init__(
        self,
        model_path: str | Path,
        axis: str = "z",
        pitch: float | None = None,
        max_preview_faces: int = _MAX_PREVIEW_FACES,
    ):
        self.model_path = Path(model_path)
        self.mesh = core.load_mesh(self.model_path)
        self.axis = axis
        self.volume = float(self.mesh.volume)
        self.max_preview_faces = max_preview_faces

        if pitch is None:
            extent = self.mesh.extents[core.AXES[axis]]
            pitch = max(extent / 30, 1e-9)
        self.pitch = pitch

        self.heights = None
        self.slider = None
        self._plane_artist = None
        self._curve_lines: list = []

        self._build_ui()
        self._recompute_slices()

    # ---- データ ----
    def _recompute_slices(self) -> None:
        self.heights = core.compute_heights(self.mesh, self.axis, self.pitch)
        self._rebuild_slider()

    def _section_at(self, index: int):
        """指定インデックスの断面を計算する。(path_2d, discrete_3d) を返す。

        path_2d は2D平面上のPath2D(交差なしならNone)、discrete_3d は
        3Dプレビュー用のポリライン(Nx3配列)のリスト。
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
        return path_2d, section.discrete

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

    # ---- UI構築 ----
    def _build_ui(self) -> None:
        self.fig = plt.figure(figsize=(11, 8))
        try:
            self.fig.canvas.manager.set_window_title(f"slice3d viewer - {self.model_path.name}")
        except AttributeError:
            pass

        self.ax_3d = self.fig.add_axes((0.03, 0.28, 0.45, 0.58), projection="3d")
        self._draw_static_mesh()

        self.ax_section = self.fig.add_axes((0.55, 0.28, 0.43, 0.58))
        self.ax_section.set_aspect("equal")
        self.ax_section.set_title("断面(この平面を真上から見た形)", fontsize=10)

        watertight_note = "" if self.mesh.is_watertight else "  (non-watertight: 近似値)"
        self.fig.text(
            0.02, 0.975,
            f"{self.model_path.name}   volume = {self.volume:.6g}{watertight_note}",
            fontsize=10, va="top",
        )
        self.pos_text = self.fig.text(0.02, 0.945, "", fontsize=10, va="top")
        self.fig.text(
            0.03, 0.905, "モデル全体(赤 = 現在の切断位置)", fontsize=10, va="top"
        )

        ax_radio = self.fig.add_axes((0.015, 0.08, 0.09, 0.15))
        ax_radio.set_title("axis", fontsize=9)
        self.radio = RadioButtons(ax_radio, ("x", "y", "z"), active="xyz".index(self.axis))
        self.radio.on_clicked(self._on_axis_change)

        ax_pitch = self.fig.add_axes((0.28, 0.1, 0.18, 0.05))
        self.pitch_box = TextBox(ax_pitch, "pitch  ", initial=f"{self.pitch:g}")
        self.pitch_box.on_submit(self._on_pitch_submit)

        ax_save = self.fig.add_axes((0.62, 0.1, 0.26, 0.05))
        self.save_button = Button(ax_save, "Save slice (svg)")
        self.save_button.on_clicked(self._on_save)

        self.ax_slider = self.fig.add_axes((0.14, 0.2, 0.76, 0.05))

    def _preview_mesh(self):
        """3D表示専用の軽量化されたメッシュを返す(スライス計算には使わない)。"""
        mesh = self.mesh
        if len(mesh.faces) <= self.max_preview_faces:
            return mesh
        try:
            return mesh.simplify_quadric_decimation(face_count=self.max_preview_faces)
        except Exception:
            # fast_simplification が無い環境などへのフォールバック: 単純間引き。
            # 形状の見え方は粗くなるが、表示が固まるよりはよい。
            step = math.ceil(len(mesh.faces) / self.max_preview_faces)
            faces = mesh.faces[::step]
            return trimesh.Trimesh(vertices=mesh.vertices, faces=faces, process=False)

    def _draw_static_mesh(self) -> None:
        """モデル全体を半透明の3Dサーフェスとして一度だけ描画する(スライス操作では再描画しない)。"""
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
        self.slider = Slider(self.ax_slider, "slice", 0, max(n - 1, 0), valinit=current, valstep=1)
        self.slider.on_changed(lambda val: self._show_index(int(val)))
        self._show_index(current)

    # ---- コールバック ----
    def _on_axis_change(self, label: str) -> None:
        self.axis = label
        self.pitch = max(self.mesh.extents[core.AXES[label]] / 30, 1e-9)
        self.pitch_box.set_val(f"{self.pitch:g}")
        self._recompute_slices()
        self.fig.canvas.draw_idle()

    def _on_pitch_submit(self, text: str) -> None:
        try:
            pitch = float(text)
        except ValueError:
            return
        if pitch <= 0:
            return
        self.pitch = pitch
        self._recompute_slices()
        self.fig.canvas.draw_idle()

    def _on_save(self, event) -> None:
        index = int(self.slider.val)
        path_2d, _discrete_3d = self._section_at(index)
        if path_2d is None:
            print("この位置は交差なしのため保存できません")
            return
        outdir = self.model_path.parent / "slices_gui"
        outdir.mkdir(exist_ok=True)
        outpath = outdir / f"{self.model_path.stem}_{self.axis}{index:04d}_{self.heights[index]:.4f}.svg"
        core.save_section(path_2d, outpath)
        print(f"保存しました: {outpath}")

    # ---- 描画 ----
    def _show_index(self, index: int) -> None:
        index = max(0, min(index, len(self.heights) - 1))
        position = self.heights[index]
        path_2d, discrete_3d = self._section_at(index)

        self._update_3d_highlight(index, discrete_3d)

        self.ax_section.clear()
        self.ax_section.set_aspect("equal")
        self.ax_section.set_title("断面(この平面を真上から見た形)", fontsize=10)
        if path_2d is None:
            self.ax_section.text(
                0.5, 0.5, "交差なし", ha="center", va="center", transform=self.ax_section.transAxes
            )
        else:
            for polyline in path_2d.discrete:
                self.ax_section.plot(polyline[:, 0], polyline[:, 1], "-k")

        self.pos_text.set_text(
            f"axis={self.axis}  pitch={self.pitch:g}  "
            f"index={index + 1}/{len(self.heights)}  position={position:.6g}"
        )
        self.fig.canvas.draw_idle()

    def show(self) -> None:
        plt.show()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="slice3d-gui", description="3Dモデルの断面・体積を確認するGUIビューア"
    )
    parser.add_argument("model", type=Path, help="入力3Dモデルファイル (STL/OBJ/PLY/GLBなど)")
    parser.add_argument("--axis", choices=tuple(core.AXES), default="z", help="初期のスライス軸")
    parser.add_argument("--pitch", type=float, default=None, help="初期のスライス間隔(既定: 全体を約30分割)")
    parser.add_argument(
        "--max-preview-faces",
        type=int,
        default=_MAX_PREVIEW_FACES,
        help=f"3D表示を間引く面数の上限(既定: {_MAX_PREVIEW_FACES})。動作が重い場合は小さくすると軽くなる",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    viewer = SliceViewer(
        args.model, axis=args.axis, pitch=args.pitch, max_preview_faces=args.max_preview_faces
    )
    viewer.show()


if __name__ == "__main__":
    main()
