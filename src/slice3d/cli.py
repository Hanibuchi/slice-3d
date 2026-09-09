"""slice3d のコマンドラインインターフェース。"""

from __future__ import annotations

import argparse
from pathlib import Path

from .core import AXES, load_mesh, compute_heights, iter_slices, save_section


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="slice3d",
        description="3Dモデルを一定幅でスライスして断面を出力する",
    )
    parser.add_argument("model", type=Path, help="入力3Dモデルファイル (STL/OBJ/PLY/GLBなど)")
    parser.add_argument("--axis", choices=tuple(AXES), default="z", help="スライスする軸 (既定: z)")
    parser.add_argument("--thickness", type=float, default=1.0, help="スライス間隔 [モデル単位] (既定: 1.0)")
    parser.add_argument("--start", type=float, default=None, help="開始位置 (既定: モデルの最小値)")
    parser.add_argument("--end", type=float, default=None, help="終了位置 (既定: モデルの最大値)")
    parser.add_argument("--outdir", type=Path, default=Path("slices"), help="出力先ディレクトリ (既定: ./slices)")
    parser.add_argument(
        "--format",
        choices=("svg", "dxf", "png", "csv"),
        default="svg",
        help="断面の出力形式 (既定: svg)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    mesh = load_mesh(args.model)
    if not mesh.is_watertight:
        print(f"警告: メッシュが閉じていません (is_watertight=False)。断面が欠ける場合があります: {args.model}")

    heights = compute_heights(mesh, args.axis, args.thickness, args.start, args.end)
    print(f"{len(heights)} 枚の断面を axis={args.axis}, thickness={args.thickness} で生成します")

    args.outdir.mkdir(parents=True, exist_ok=True)
    stem = args.model.stem

    n_ok = 0
    for s in iter_slices(mesh, axis=args.axis, thickness=args.thickness, start=args.start, end=args.end):
        if s.is_empty:
            print(f"  [{s.index:04d}] {args.axis}={s.position:.4f}: 交差なし (スキップ)")
            continue
        outpath = args.outdir / f"{stem}_{args.axis}{s.index:04d}_{s.position:.4f}.{args.format}"
        save_section(s.path_2d, outpath, args.format)
        print(f"  [{s.index:04d}] {args.axis}={s.position:.4f}: {outpath.name}")
        n_ok += 1

    print(f"完了: {n_ok}/{len(heights)} 断面を {args.outdir} に出力しました")


if __name__ == "__main__":
    main()
