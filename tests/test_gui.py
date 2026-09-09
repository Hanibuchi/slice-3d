from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pytest
import trimesh

from slice3d.gui import SliceViewer

AMMONITE_PATH = Path(__file__).parent.parent / "examples" / "ammonite.glb"


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


def test_viewer_shows_open_cross_section():
    """ammonite.glb の y=0.15〜0.22付近は非watertightで断面が閉じたループに
    ならないため、以前は3Dハイライトには見えるのに断面図には何も描かれない
    (discrete_3d が空になる)不具合があった。その回帰テスト。"""
    viewer = SliceViewer(AMMONITE_PATH, axis="y", thickness=0.01)

    index = int(round((0.18 - viewer.heights[0]) / viewer.thickness))
    viewer.slider.set_val(index)

    _path_2d, discrete_3d = viewer._section_at(index)
    assert discrete_3d, "y=0.18付近の断面が空になっています(開いた線の欠落)"
    assert len(viewer.ax_section.get_lines()) > 0


def test_viewer_save_writes_file(tmp_path):
    model_path = make_sphere_file(tmp_path)
    viewer = SliceViewer(model_path, axis="z", thickness=2.5)

    middle = len(viewer.heights) // 2
    viewer.slider.set_val(middle)
    viewer._on_save(None)

    outdir = model_path.parent / "slices_gui"
    assert outdir.exists()
    assert any(outdir.iterdir())


def test_viewer_default_format_is_svg(tmp_path):
    model_path = make_sphere_file(tmp_path)
    viewer = SliceViewer(model_path, axis="z", thickness=2.5)

    assert viewer.format == "svg"


def test_viewer_rejects_unknown_format(tmp_path):
    model_path = make_sphere_file(tmp_path)
    with pytest.raises(ValueError):
        SliceViewer(model_path, axis="z", thickness=2.5, fmt="bmp")


def test_viewer_format_change_updates_state_and_labels(tmp_path):
    model_path = make_sphere_file(tmp_path)
    viewer = SliceViewer(model_path, axis="z", thickness=2.5)

    viewer._on_format_change("png")

    assert viewer.format == "png"
    assert "PNG" in viewer.save_current_button.label.get_text()
    assert "PNG" in viewer.save_all_button.label.get_text()


def test_viewer_save_current_respects_selected_format(tmp_path):
    model_path = make_sphere_file(tmp_path)
    viewer = SliceViewer(model_path, axis="z", thickness=2.5)
    viewer._on_format_change("png")

    middle = len(viewer.heights) // 2
    viewer.slider.set_val(middle)
    viewer._on_save(None)

    outdir = model_path.parent / "slices_gui"
    saved = list(outdir.iterdir())
    assert saved
    assert all(p.suffix == ".png" for p in saved)


def test_viewer_save_all_writes_every_nonempty_slice(tmp_path):
    model_path = make_sphere_file(tmp_path)
    viewer = SliceViewer(model_path, axis="z", thickness=2.5)
    viewer._on_format_change("csv")

    viewer._on_save_all(None)

    outdir = model_path.parent / "slices_gui"
    saved = list(outdir.iterdir())
    n_nonempty = sum(1 for h in range(len(viewer.heights)) if viewer._section_at(h)[0] is not None)
    assert len(saved) == n_nonempty
    assert all(p.suffix == ".csv" for p in saved)


def test_viewer_save_all_covers_open_cross_sections():
    """save all が、開いた断面(閉じたループにならない位置)も欠落なく
    保存することを確認する回帰テスト。"""
    outdir_marker = AMMONITE_PATH.parent / "slices_gui"
    if outdir_marker.exists():
        for p in outdir_marker.iterdir():
            p.unlink()

    viewer = SliceViewer(AMMONITE_PATH, axis="y", thickness=0.01, fmt="png")
    try:
        viewer._on_save_all(None)
        saved_names = {p.name for p in outdir_marker.iterdir()}
        # y=0.18付近(開いた断面)のファイルが含まれていること
        assert any("0.1800" in name or "0.18" in name for name in saved_names)
    finally:
        if outdir_marker.exists():
            for p in outdir_marker.iterdir():
                p.unlink()
            outdir_marker.rmdir()
