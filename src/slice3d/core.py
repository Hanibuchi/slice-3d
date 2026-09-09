"""3Dメッシュを一定間隔でスライスし、断面(2Dパス)を得るためのコア機能。"""

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
    """1枚の断面を表す。"""

    index: int
    axis: str
    position: float
    path_2d: "trimesh.path.Path2D | None"
    # 断面のワールド座標での点列(Nx3配列のリスト)。png保存時に実寸スケールを
    # 揃えるために使う(path_2d はtrimeshが断面ごとに選ぶローカル2D座標系のため、
    # 複数断面間でスケールが揃わない)。
    polylines_3d: list = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return self.path_2d is None


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    """3Dモデルファイルを読み込み、単一の Trimesh として返す。

    STL / OBJ / PLY / GLB / GLTF など、trimesh が対応する形式を扱える。
    """
    mesh = trimesh.load(path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError(f"単一のメッシュとして読み込めませんでした: {path}")
    return mesh


def compute_heights(
    mesh: trimesh.Trimesh,
    axis: str,
    thickness: float,
    start: float | None = None,
    end: float | None = None,
) -> np.ndarray:
    """指定した軸に沿って、一定間隔(thickness)でスライスする位置の配列を計算する。"""
    if axis not in AXES:
        raise ValueError(f"axis は {list(AXES)} のいずれかである必要があります: {axis!r}")
    if thickness <= 0:
        raise ValueError("thickness は正の値である必要があります")

    axis_idx = AXES[axis]
    bounds_min, bounds_max = mesh.bounds[:, axis_idx]
    lo = bounds_min if start is None else start
    hi = bounds_max if end is None else end
    if hi <= lo:
        raise ValueError(f"終了位置は開始位置より大きい必要があります (start={lo}, end={hi})")

    n = int(np.floor((hi - lo) / thickness)) + 1
    return lo + np.arange(n) * thickness


def iter_slices(
    mesh: trimesh.Trimesh,
    axis: str = "z",
    thickness: float = 1.0,
    start: float | None = None,
    end: float | None = None,
) -> Iterator[Slice]:
    """メッシュを一定間隔でスライスし、Sliceオブジェクトを1枚ずつ生成する。

    交差しない位置では ``path_2d=None`` の Slice を返す(呼び出し側でスキップ判定できる)。
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
    """iter_slices の結果をリストとして返す。"""
    return list(iter_slices(mesh, axis=axis, thickness=thickness, start=start, end=end))


def polylines(path) -> list[np.ndarray]:
    """Path2D/Path3D の全エンティティを点列(Nx2 または Nx3 配列)のリストとして取り出す。

    ``path.discrete`` は閉じたループしか返さないため、非watertightなメッシュの
    断面のように閉じていない(開いた)線が含まれていると取りこぼしてしまう。
    この関数は entity 単位で ``entity.discrete(path.vertices)`` を呼ぶことで、
    開いた線も含めてすべての線分を取得する。
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
    """1枚の断面 (Path2D) をファイルへ保存する。

    fmt: "svg" | "dxf" | "png" | "csv"。省略時は outpath の拡張子から判定する。

    fmt="png" で保存する場合は、``polylines_3d``(ワールド座標の点列。
    ``Slice.polylines_3d`` を渡す)、``axis``、``bounds``(``mesh.bounds``)を
    指定すると、画像の表示範囲をモデル全体のバウンディングボックスに固定できる。
    これらを省略すると各断面の内容だけに自動フィットして保存されるため、
    断面ごとに画像の縮尺(見た目の大きさ)がバラバラになってしまう点に注意。
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
            # ワールド座標をそのまま2軸に投影し、表示範囲をモデル全体のバウンディング
            # ボックスに固定する。これにより、断面の大きさに関わらずどの画像も
            # 元モデルに対する実際の縮尺(比率)を保って保存される。
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
            # 従来どおり: 断面の内容だけに自動フィットする(スケールは断面ごとに異なる)。
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
        raise ValueError(f"未対応の出力形式です: {fmt!r} (対応形式: svg, dxf, png, csv)")

    return outpath


def print_volume(mesh: trimesh.Trimesh) -> float:
    """メッシュの体積を標準出力に表示し、その値を返す。

    メッシュが水密(watertight)でない場合、体積の計算結果が不正確になりうるため警告を表示する。
    """
    if not mesh.is_watertight:
        print("警告: メッシュが水密でないため、体積の計算結果は不正確な可能性があります")

    volume = float(mesh.volume)
    print(f"体積: {volume}")
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
    """3Dモデルファイルを読み込み、スライスして outdir へ一括出力する。

    戻り値は書き出したファイルパスのリスト(交差しないスライスはスキップされる)。
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
