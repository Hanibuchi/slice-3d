import matplotlib

matplotlib.use("Agg")

import trimesh

from slice3d.gui import SliceViewer


def make_sphere_file(tmp_path):
    mesh = trimesh.creation.icosphere(subdivisions=2, radius=10.0)
    path = tmp_path / "sphere.stl"
    mesh.export(path)
    return path


def test_viewer_loads_and_shows_volume(tmp_path):
    model_path = make_sphere_file(tmp_path)
    viewer = SliceViewer(model_path, axis="z")

    assert viewer.volume > 0
    assert len(viewer.heights) > 0


def test_viewer_axis_change_recomputes_heights(tmp_path):
    model_path = make_sphere_file(tmp_path)
    viewer = SliceViewer(model_path, axis="z")

    n_before = len(viewer.heights)
    viewer._on_axis_change("x")

    assert viewer.axis == "x"
    assert len(viewer.heights) > 0
    assert n_before > 0  # z軸でもスライスが生成されていたことの確認


def test_viewer_pitch_change_updates_slice_count(tmp_path):
    model_path = make_sphere_file(tmp_path)
    viewer = SliceViewer(model_path, axis="z", pitch=5.0)

    n_coarse = len(viewer.heights)
    viewer._on_pitch_submit("1.0")
    n_fine = len(viewer.heights)

    assert n_fine > n_coarse


def test_viewer_3d_highlight_updates_with_slider(tmp_path):
    model_path = make_sphere_file(tmp_path)
    viewer = SliceViewer(model_path, axis="z", pitch=2.5)

    middle = len(viewer.heights) // 2
    viewer.slider.set_val(middle)

    assert viewer._plane_artist is not None
    assert len(viewer._curve_lines) >= 1


def test_viewer_save_writes_file(tmp_path):
    model_path = make_sphere_file(tmp_path)
    viewer = SliceViewer(model_path, axis="z", pitch=2.5)

    middle = len(viewer.heights) // 2
    viewer.slider.set_val(middle)
    viewer._on_save(None)

    outdir = model_path.parent / "slices_gui"
    assert outdir.exists()
    assert any(outdir.iterdir())
