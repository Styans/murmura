import numpy as np
import pytest

from murmura.formations import (
    circle,
    cube,
    disc,
    grid,
    heart,
    make_formation,
    min_spacing,
    scale_to_spacing,
    sphere,
    star,
    svg_points,
    text,
)

SVG_POLYLINE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
    '<polyline points="0,0 100,0 100,50" fill="none" stroke="#ff0000"/></svg>'
)


@pytest.mark.parametrize(
    "factory, kwargs",
    [
        (grid, {"spacing": 2}),
        (circle, {"radius": 10}),
        (heart, {"size": 20}),
        (star, {"radius": 10}),
        (sphere, {"radius": 10}),
        (cube, {"size": 10}),
        (disc, {"radius": 10}),
        (text, {"text": "Привет 2026", "height": 10}),
    ],
)
def test_generators_return_requested_count(factory, kwargs):
    pts = factory(57, **kwargs)
    assert pts.shape == (57, 3)
    assert np.all(np.isfinite(pts))
    assert min_spacing(pts) > 0


def test_circle_is_evenly_spaced_in_the_vertical_plane():
    pts = circle(12, radius=10, center=(0, 0, 30))
    assert np.allclose(pts[:, 1], 0)
    assert np.allclose(np.linalg.norm(pts - [0, 0, 30], axis=1), 10)
    assert min_spacing(pts) == pytest.approx(2 * 10 * np.sin(np.pi / 12))


def test_outlines_with_spikes_keep_spacing():
    # sharp spikes must not put points of two branches close to each other
    pts = star(100, radius=36)
    assert min_spacing(pts) > 1.5


def test_scale_to_spacing():
    pts = circle(50, radius=5)
    scaled = scale_to_spacing(pts, 3.0)
    assert min_spacing(scaled) == pytest.approx(3.0)


def test_svg_sampling_keeps_corners_and_orientation():
    uv, colors = svg_points(SVG_POLYLINE, 4, size=10)
    # u to the right, v up, centred, larger extent equals size
    assert np.allclose(uv, [[-5, 2.5], [0, 2.5], [5, 2.5], [5, -2.5]])
    assert colors == [(255, 0, 0)] * 4


def test_svg_arcs_transforms_and_colours():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<g transform="translate(10,0)"><path d="M10 50 a40 40 0 1 1 80 0 a40 40 0 1 1 -80 0z" '
        'style="stroke: rgb(0,128,255); fill:none"/></g></svg>'
    )
    uv, colors = svg_points(svg, 16, size=20)
    assert uv.shape == (16, 2)
    assert np.allclose(np.linalg.norm(uv, axis=1), 10, atol=0.05)
    assert colors[0] == (0, 128, 255)


def test_make_formation_factory(tmp_path):
    pts, colors = make_formation({"shape": "circle", "radius": 5, "center": [0, 0, 20]}, 10)
    assert colors is None and pts.shape == (10, 3)
    path = tmp_path / "shape.svg"
    path.write_text(SVG_POLYLINE, encoding="utf-8")
    pts, colors = make_formation(
        {"shape": "svg", "file": "shape.svg", "size": 10}, 7, base_dir=tmp_path
    )
    assert pts.shape == (7, 3) and colors.shape == (7, 3)
    with pytest.raises(ValueError):
        make_formation({"shape": "dodecahedron"}, 5)
