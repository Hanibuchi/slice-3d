"""3Dモデルの断面・体積を確認するGUIビューア。

専用ウィンドウを開き、3D表示でモデル全体と現在の切断位置を確認しながら、
スライダーで断面を切り替えられる。軸(x/y/z)とスライス間隔(thickness)はウィンドウ上で変更できる。

使い方::

    slice3d-gui model.stl
    slice3d-gui model.stl --axis x --thickness 0.01
    slice3d-gui model.glb              # glTF/GLBは仕様上メートル単位なので自動で"m"表示
    slice3d-gui model.stl --units mm   # STLなど単位不明な形式は明示的に指定

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

# glTF/GLBは仕様上メートル単位と定められているため、既定値として表示に使う。
# STL/OBJ/PLYなどは単位の情報を持たないファイル形式なので、既定は単位なし(空文字)。
_UNITS_BY_EXTENSION = {".glb": "m", ".gltf": "m"}

_AXIS_NAMES = ("x", "y", "z")


def _default_units(model_path: Path) -> str:
    return _UNITS_BY_EXTENSION.get(model_path.suffix.lower(), "")


def _nice_thickness(extent: float, target_slices: int = 30) -> float:
    """extentを約target_slices分割する、キリの良いthickness値(1/2/5 x 10^n)を選ぶ。"""
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
    """3D表示 + スライダーで断面を切り替えながら確認するmatplotlibウィンドウ。"""

    def __init__(
        self,
        model_path: str | Path,
        axis: str = "z",
        thickness: float | None = None,
        max_preview_faces: int = _MAX_PREVIEW_FACES,
        units: str | None = None,
    ):
        self.model_path = Path(model_path)
        self.mesh = core.load_mesh(self.model_path)
        self.axis = axis
        self.volume = float(self.mesh.volume)
        self.max_preview_faces = max_preview_faces
        self.units = _default_units(self.model_path) if units is None else units

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

    # ---- 表示用フォーマット ----
    # 有効数字3桁に丸める(生の浮動小数点をそのまま出すと桁数が多すぎて読みにくいため)。
    def _fmt_length(self, value: float) -> str:
        suffix = f" {self.units}" if self.units else ""
        return f"{value:.3g}{suffix}"

    def _fmt_volume(self, value: float) -> str:
        suffix = f" {self.units}³" if self.units else ""
        return f"{value:.3g}{suffix}"

    # ---- データ ----
    def _recompute_slices(self) -> None:
        self.heights = core.compute_heights(self.mesh, self.axis, self.thickness)
        self._rebuild_slider()

    def _section_at(self, index: int):
        """指定インデックスの断面を計算する。(path_2d, discrete_3d) を返す。

        path_2d は2D平面上のPath2D(交差なしならNone)、discrete_3d は
        3Dプレビュー用のポリライン(Nx3配列)のリスト。

        polylines()(core.pyのentityベースの抽出)を使うことで、非watertightな
        メッシュの断面のように閉じていない(開いた)線も欠落なく拾う。
        ``section.discrete`` は閉じたループしか返さないため使わない。
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
        self.ax_section.set_title("Cross-section (view along slicing axis)", fontsize=10)

        watertight_note = "" if self.mesh.is_watertight else "  (non-watertight: volume is approximate)"
        self.fig.text(
            0.02, 0.975,
            f"{self.model_path.name}   volume = {self._fmt_volume(self.volume)}{watertight_note}",
            fontsize=10, va="top",
        )
        self.pos_text = self.fig.text(0.02, 0.945, "", fontsize=10, va="top")
        self.fig.text(
            0.03, 0.905, "Full model (red = current slice plane)", fontsize=10, va="top"
        )

        # ラジオボタンは既定だと丸のサイズ・クリック領域が小さく押しづらいため、
        # 専用エリアを広めに取った上で radio_props/label_props でマーカーと
        # フォントを拡大している。
        ax_radio = self.fig.add_axes((0.01, 0.02, 0.13, 0.24))
        ax_radio.set_title("Axis", fontsize=11)
        self.radio = RadioButtons(
            ax_radio,
            ("x", "y", "z"),
            active="xyz".index(self.axis),
            radio_props={"s": 160},
            label_props={"fontsize": [14, 14, 14]},
        )
        self.radio.on_clicked(self._on_axis_change)

        thickness_label = f"Thickness ({self.units})  " if self.units else "Thickness  "
        ax_thickness = self.fig.add_axes((0.28, 0.09, 0.18, 0.07))
        self.thickness_box = TextBox(ax_thickness, thickness_label, initial=f"{self.thickness:g}")
        self.thickness_box.text_disp.set_fontsize(12)
        self.thickness_box.label.set_fontsize(11)
        self.thickness_box.on_submit(self._on_thickness_submit)

        ax_save = self.fig.add_axes((0.62, 0.09, 0.26, 0.07))
        self.save_button = Button(ax_save, "Save Slice (SVG)")
        self.save_button.label.set_fontsize(11)
        self.save_button.on_clicked(self._on_save)

        self.ax_slider = self.fig.add_axes((0.19, 0.2, 0.71, 0.05))
        # スライダーのつまみも既定サイズだと掴みづらいので大きくする
        # (トラック自体はどこをクリックしてもその位置へ移動できる)。
        self._slider_handle_style = {"size": 18}

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

    # ---- コールバック ----
    def _on_axis_change(self, label: str) -> None:
        self.axis = label
        self.thickness = _nice_thickness(self.mesh.extents[core.AXES[label]])
        self.thickness_box.set_val(f"{self.thickness:g}")
        self._recompute_slices()
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

    def _on_save(self, event) -> None:
        index = int(self.slider.val)
        path_2d, _discrete_3d = self._section_at(index)
        if path_2d is None:
            print("Cannot save: no intersection at this slice position")
            return
        outdir = self.model_path.parent / "slices_gui"
        outdir.mkdir(exist_ok=True)
        outpath = outdir / f"{self.model_path.stem}_{self.axis}{index:04d}_{self.heights[index]:.4f}.svg"
        core.save_section(path_2d, outpath)
        print(f"Saved: {outpath}")

    # ---- 描画 ----
    def _show_index(self, index: int) -> None:
        index = max(0, min(index, len(self.heights) - 1))
        position = self.heights[index]
        path_2d, discrete_3d = self._section_at(index)

        self._update_3d_highlight(index, discrete_3d)

        # 断面図は3Dハイライトと同じワールド座標(discrete_3d)をそのまま2軸に投影して描く。
        # path_2d(trimeshが断面ごとに独自に選ぶローカル2D座標系)を使うと、断面の形だけで
        # 自動スケーリングされてしまい、小さな断片がパネルいっぱいに拡大されて3D表示と
        # 対応が取れなくなる(特にthin方向の軸でスライスすると顕著)。
        # ここではモデル全体のバウンディングボックスに表示範囲を固定し、常に同じ縮尺で見せる。
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    viewer = SliceViewer(
        args.model,
        axis=args.axis,
        thickness=args.thickness,
        max_preview_faces=args.max_preview_faces,
        units=args.units,
    )
    viewer.show()


if __name__ == "__main__":
    main()
