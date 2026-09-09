import matplotlib

matplotlib.use("Agg")

import pytest
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


def test_viewer_thickness_change_updates_slice_count(tmp_path):
    model_path = make_sphere_file(tmp_path)
    viewer = SliceViewer(model_path, axis="z", thickness=5.0)

    n_coarse = len(viewer.heights)
    viewer._on_thickness_submit("1.0")
    n_fine = len(viewer.heights)

    assert n_fine > n_coarse


def test_viewer_3d_highlight_updates_with_slider(tmp_path):
    model_path = make_sphere_file(tmp_path)
    viewer = SliceViewer(model_path, axis="z", thickness=2.5)

    middle = len(viewer.heights) // 2
    viewer.slider.set_val(middle)

    assert viewer._plane_artist is not None
    assert len(viewer._curve_lines) >= 1


def test_viewer_section_panel_matches_3d_scale(tmp_path):
    """断面図がpath_2dの自動スケーリングでズームされず、常にモデル全体の
    バウンディングボックスに固定表示されることを確認する(3D表示との対応が
    取れなくなる回帰を防ぐ)。"""
    model_path = make_sphere_file(tmp_path)
    viewer = SliceViewer(model_path, axis="z", thickness=2.5)

    b = viewer.mesh.bounds
    for index in (0, len(viewer.heights) // 2, len(viewer.heights) - 1):
        viewer.slider.set_val(index)
        assert viewer.ax_section.get_xlim() == pytest.approx((b[0, 0], b[1, 0]))
        assert viewer.ax_section.get_ylim() == pytest.approx((b[0, 1], b[1, 1]))


def test_viewer_section_uses_world_coordinates(tmp_path):
    """断面図に描く座標が、3Dハイライト(discrete_3d)と同じワールド座標系の
    値であることを確認する(trimeshの断面ごとに異なるローカル2D座標系を
    そのまま使うと、3D側と対応しない見た目になる)。"""
    model_path = make_sphere_file(tmp_path)
    viewer = SliceViewer(model_path, axis="x", thickness=2.5)

    middle = len(viewer.heights) // 2
    viewer.slider.set_val(middle)
    _path_2d, discrete_3d = viewer._section_at(middle)

    lines = [ln for ln in viewer.ax_section.get_lines()]
    assert lines, "断面が描画されていません"
    plotted_x = lines[0].get_xdata()
    # axis="x" のとき、断面図の横軸はワールドのy座標に対応する。
    assert plotted_x.min() == pytest.approx(discrete_3d[0][:, 1].min())
    assert plotted_x.max() == pytest.approx(discrete_3d[0][:, 1].max())


def test_viewer_save_writes_file(tmp_path):
    model_path = make_sphere_file(tmp_path)
    viewer = SliceViewer(model_path, axis="z", thickness=2.5)

    middle = len(viewer.heights) // 2
    viewer.slider.set_val(middle)
    viewer._on_save(None)

    outdir = model_path.parent / "slices_gui"
    assert outdir.exists()
    assert any(outdir.iterdir())
