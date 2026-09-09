import trimesh

import slice3d


def make_sphere():
    return trimesh.creation.icosphere(subdivisions=2, radius=10.0)


def test_compute_heights_covers_range():
    mesh = make_sphere()
    heights = slice3d.compute_heights(mesh, axis="z", pitch=2.5)
    assert heights[0] == mesh.bounds[0, 2]
    assert heights[-1] <= mesh.bounds[1, 2]
    assert all(b - a for a, b in zip(heights, heights[1:]))


def test_iter_slices_middle_is_not_empty():
    mesh = make_sphere()
    slices = slice3d.slice_mesh(mesh, axis="z", pitch=2.5)
    middle = [s for s in slices if abs(s.position) < 1e-6]
    assert middle, "赤道付近のスライスが見つかりません"
    assert not middle[0].is_empty
    assert len(middle[0].path_2d.discrete) >= 1


def test_iter_slices_extremes_are_empty():
    mesh = make_sphere()
    slices = slice3d.slice_mesh(mesh, axis="z", pitch=2.5)
    assert slices[0].is_empty
    assert slices[-1].is_empty


def test_slice_file_writes_svg(tmp_path):
    model_path = tmp_path / "sphere.stl"
    make_sphere().export(model_path)

    outdir = tmp_path / "out"
    written = slice3d.slice_file(model_path, outdir, axis="z", pitch=2.5, fmt="svg")

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
    s = next(s for s in slice3d.iter_slices(mesh, axis="z", pitch=2.5) if not s.is_empty)

    outpath = tmp_path / "section.csv"
    result = slice3d.save_section(s.path_2d, outpath)

    assert result == outpath
    assert outpath.exists()
    assert outpath.read_text().startswith("polyline_id,x,y")
