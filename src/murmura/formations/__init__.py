"""Formation generators and a declarative factory used by show scripts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .shapes import (
    circle,
    cube,
    disc,
    even_subset,
    grid,
    heart,
    helix,
    image,
    line,
    min_spacing,
    place_2d,
    polygon,
    rectangle,
    resample_polyline,
    scale_to_spacing,
    sphere,
    spiral,
    star,
    text,
    torus,
)
from .svg import parse_svg, svg_formation, svg_points

__all__ = (
    "SHAPES",
    "circle",
    "cube",
    "disc",
    "even_subset",
    "grid",
    "heart",
    "helix",
    "image",
    "line",
    "make_formation",
    "min_spacing",
    "parse_svg",
    "place_2d",
    "polygon",
    "rectangle",
    "resample_polyline",
    "scale_to_spacing",
    "sphere",
    "spiral",
    "star",
    "svg_formation",
    "svg_points",
    "text",
    "torus",
)

SHAPES = {
    "circle": circle,
    "cube": cube,
    "disc": disc,
    "grid": grid,
    "heart": heart,
    "helix": helix,
    "line": line,
    "polygon": polygon,
    "rectangle": rectangle,
    "sphere": sphere,
    "spiral": spiral,
    "star": star,
    "text": text,
    "torus": torus,
}


def make_formation(
    spec: dict[str, Any], n: int, *, base_dir: str | Path | None = None
) -> tuple[np.ndarray, np.ndarray | None]:
    """Creates a formation from a declarative description.

    ``spec`` must contain ``shape`` plus the keyword arguments of the
    corresponding generator, e.g. ``{"shape": "circle", "radius": 15,
    "center": [0, 0, 30]}``. ``svg`` and ``image`` shapes take a ``file``
    (relative to ``base_dir``) and also return per-point colours;
    ``points`` takes an explicit list of coordinates.

    Returns:
        the positions and, if the shape defines them, the colours
    """
    spec = dict(spec)
    shape = str(spec.pop("shape", "")).lower()
    base = Path(base_dir or ".")

    def resolve(name: str) -> Path:
        p = Path(name)
        return p if p.is_absolute() else base / p

    if shape == "svg":
        if "file" in spec:
            spec["source"] = resolve(spec.pop("file")).read_text(encoding="utf-8")
        points, colors = svg_formation(n, **spec)
        return points, colors
    if shape == "image":
        spec["path"] = resolve(spec.pop("file", spec.get("path", "")))
        return image(n, **spec)
    if shape == "points":
        pts = np.asarray(spec["points"], dtype=float).reshape(-1, 3)
        if len(pts) != n:
            raise ValueError(
                f"explicit formation has {len(pts)} points but the show has {n} drones"
            )
        return pts, None
    try:
        factory = SHAPES[shape]
    except KeyError:
        known = ", ".join(sorted([*SHAPES, "svg", "image", "points"]))
        raise ValueError(f"unknown formation shape {shape!r}; known shapes: {known}") from None
    return factory(n, **spec), None
