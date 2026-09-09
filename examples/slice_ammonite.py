"""ライブラリ使用例: アンモナイトのGLBモデルをX軸方向にスライスする。

実行方法::

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
    print(f"{len(written)} 枚の断面を {HERE / 'output'} に出力しました")


if __name__ == "__main__":
    main()
