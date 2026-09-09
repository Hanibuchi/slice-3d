from pathlib import Path

import trimesh

import slice3d

AMMONITE_PATH = Path(__file__).parent.parent / "examples" / "ammonite.glb"


def make_sphere():
    return trimesh.creation.icosphere(subdivisions=2, radius=10.0)


def test_compute_heights_covers_range():
    mesh = make_sphere()
    heights = slice3d.compute_heights(mesh, axis="z", thickness=2.5)
    assert heights[0] == mesh.bounds[0, 2]
    assert heights[-1] <= mesh.bounds[1, 2]
    assert all(b - a for a, b in zip(heights, heights[1:]))


def test_iter_slices_middle_is_not_empty():
    mesh = make_sphere()
    slices = slice3d.slice_mesh(mesh, axis="z", thickness=2.5)
    middle = [s for s in slices if abs(s.position) < 1e-6]
    assert middle, "赤道付近のスライスが見つかりません"
    assert not middle[0].is_empty
    assert len(middle[0].path_2d.discrete) >= 1


def test_iter_slices_extremes_are_empty():
    mesh = make_sphere()
    slices = slice3d.slice_mesh(mesh, axis="z", thickness=2.5)
    assert slices[0].is_empty
    assert slices[-1].is_empty


def test_slice_file_writes_svg(tmp_path):
    model_path = tmp_path / "sphere.stl"
    make_sphere().export(model_path)

    outdir = tmp_path / "out"
    written = slice3d.slice_file(model_path, outdir, axis="z", thickness=2.5, fmt="svg")

    assert written
    assert all(p.exists() for p in written)
    assert all(p.suffix == ".svg" for p in written)


def test_print_volume_returns_sphere_volume(capsys):
    mesh = make_sphere()
    volume = slice3d.print_volume(mesh)

    assert volume == mesh.volume
    assert "体積" in capsys.readouterr().out


def test_save_section_infers_format_from_extension(tmp_path):
    mesh = make_sphere()
    s = next(s for s in slice3d.iter_slices(mesh, axis="z", thickness=2.5) if not s.is_empty)

    outpath = tmp_path / "section.csv"
    result = slice3d.save_section(s.path_2d, outpath)

    assert result == outpath
    assert outpath.exists()
    assert outpath.read_text().startswith("polyline_id,x,y")


def test_polylines_includes_open_curves_on_nonwatertight_mesh():
    """非watertightなメッシュでは、断面が閉じたループにならない(開いた線になる)
    位置がありうる。path.discrete はそれを取りこぼすが、polylines() は拾えることを
    確認する(実際にammonite.glbのy=0.15〜0.22付近で発生していた欠落の回帰テスト)。
    """
    mesh = slice3d.load_mesh(AMMONITE_PATH)
    assert not mesh.is_watertight

    origin = mesh.bounds[0].copy()
    origin[1] = 0.18
    section = mesh.section(plane_origin=origin, plane_normal=[0, 1, 0])

    assert section is not None
    assert len(section.discrete) == 0, "既知の制約: 開いた断面は discrete では拾えない"

    lines = slice3d.polylines(section)
    assert lines
    assert sum(len(p) for p in lines) > 0


def test_slice_file_png_covers_open_curve_region(tmp_path):
    """y=0.15〜0.22付近(閉じていない断面)を含む範囲でも、PNG出力が
    空になってしまわないことを確認する。"""
    written = slice3d.slice_file(
        AMMONITE_PATH, tmp_path, axis="y", thickness=0.01, start=0.17, end=0.19, fmt="png"
    )

    assert written
    for p in written:
        assert p.stat().st_size > 0


def test_slice_file_png_images_share_consistent_scale(tmp_path):
    """slice_file が生成するPNGは、断面の大きさに関わらず全て同じピクセルサイズ
    (=元モデルに対する同じ実寸スケール)で保存されることを確認する。以前は
    断面の内容だけに自動フィットしていたため、小さな断面ほど画像いっぱいに
    ズームされ、画像同士の縮尺が揃っていなかった。
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.image as mpimg

    written = slice3d.slice_file(AMMONITE_PATH, tmp_path, axis="x", thickness=0.02, fmt="png")

    assert len(written) >= 3
    shapes = {mpimg.imread(p).shape[:2] for p in written}
    assert len(shapes) == 1, f"画像サイズが断面ごとに異なっています: {shapes}"


def test_save_section_png_without_scale_hint_still_works(tmp_path):
    """polylines_3d/axis/bounds を渡さない場合は、従来どおり断面の内容に
    自動フィットして保存できる(後方互換性の確認)。"""
    mesh = make_sphere()
    s = next(s for s in slice3d.iter_slices(mesh, axis="z", thickness=2.5) if not s.is_empty)

    outpath = tmp_path / "section.png"
    result = slice3d.save_section(s.path_2d, outpath, "png")

    assert result == outpath
    assert outpath.exists()
    assert outpath.stat().st_size > 0
