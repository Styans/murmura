"""Formation generators.

Every generator returns an ``(n, 3)`` array of positions. 2D shapes are laid
out in a plane (``xz`` by default: X to the right, Z up, facing an audience
standing on the -Y side), centred on ``center``. ``rotation`` rotates a 2D
shape within its plane and ``yaw`` rotates the finished formation around the
vertical axis (both in degrees).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np

from .._compat import KDTree as cKDTree
from .font import render_text

__all__ = (
    "circle",
    "cube",
    "disc",
    "even_subset",
    "grid",
    "heart",
    "helix",
    "image",
    "line",
    "min_spacing",
    "place_2d",
    "polygon",
    "rectangle",
    "resample_polyline",
    "scale_to_spacing",
    "sphere",
    "spiral",
    "star",
    "text",
    "torus",
)

PLANES = {
    "xz": (np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])),
    "xy": (np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])),
    "yz": (np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, 1.0])),
}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _yaw(points: np.ndarray, center: np.ndarray, yaw: float) -> np.ndarray:
    if not yaw:
        return points
    a = np.radians(yaw)
    c, s = np.cos(a), np.sin(a)
    rel = points - center
    x = rel[:, 0] * c - rel[:, 1] * s
    y = rel[:, 0] * s + rel[:, 1] * c
    return np.column_stack([x, y, rel[:, 2]]) + center


def place_2d(
    uv: np.ndarray,
    *,
    center: Sequence[float] = (0.0, 0.0, 0.0),
    plane: str = "xz",
    rotation: float = 0.0,
    yaw: float = 0.0,
) -> np.ndarray:
    """Maps 2D coordinates (centred on the origin) into 3D."""
    uv = np.asarray(uv, dtype=float).reshape(-1, 2)
    if rotation:
        a = np.radians(rotation)
        c, s = np.cos(a), np.sin(a)
        uv = uv @ np.array([[c, s], [-s, c]])
    try:
        eu, ev = PLANES[plane]
    except KeyError:
        raise ValueError(f"unknown plane {plane!r}; use one of {sorted(PLANES)}") from None
    c3 = np.asarray(center, dtype=float)
    pts = c3 + uv[:, :1] * eu + uv[:, 1:2] * ev
    return _yaw(pts, c3, yaw)


def resample_polyline(points: np.ndarray, n: int, *, closed: bool = False) -> np.ndarray:
    """Places ``n`` points at equal arc-length spacing along a polyline.

    Open polylines include both endpoints; closed ones do not repeat the start.
    """
    pts = np.asarray(points, dtype=float)
    if n <= 0:
        return np.zeros((0, pts.shape[1]))
    if closed:
        pts = np.vstack([pts, pts[:1]])
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total <= 0:
        return np.repeat(pts[:1], n, axis=0)
    if closed:
        targets = np.arange(n) * total / n
    elif n == 1:
        targets = np.array([total / 2])
    else:
        targets = np.linspace(0.0, total, n)
    out = np.empty((n, pts.shape[1]))
    for k in range(pts.shape[1]):
        out[:, k] = np.interp(targets, cum, pts[:, k])
    return out


def even_subset(
    candidates: np.ndarray, n: int, *, seed_point: Sequence[float] | None = None
) -> np.ndarray:
    """Picks ``n`` well-spread points from ``candidates`` (farthest point sampling)."""
    cand = np.asarray(candidates, dtype=float)
    m = len(cand)
    if n >= m:
        return cand.copy()
    if n <= 0:
        return np.zeros((0, cand.shape[1]))
    if seed_point is None:
        centroid = cand.mean(axis=0)
        first = int(np.argmax(np.linalg.norm(cand - centroid, axis=1)))
    else:
        first = int(np.argmin(np.linalg.norm(cand - np.asarray(seed_point), axis=1)))
    chosen = [first]
    dist = np.linalg.norm(cand - cand[first], axis=1)
    for _ in range(n - 1):
        nxt = int(np.argmax(dist))
        chosen.append(nxt)
        dist = np.minimum(dist, np.linalg.norm(cand - cand[nxt], axis=1))
    return cand[np.sort(chosen)]


def min_spacing(points: np.ndarray) -> float:
    """Smallest distance between any two points (``inf`` for fewer than two)."""
    pts = np.asarray(points, dtype=float)
    if len(pts) < 2:
        return float("inf")
    d, _ = cKDTree(pts).query(pts, k=2)
    return float(np.min(d[:, 1]))


def scale_to_spacing(
    points: np.ndarray, spacing: float, *, center: Sequence[float] | None = None
) -> np.ndarray:
    """Scales a formation around its centre so that its minimum spacing is at
    least ``spacing``. Formations that are already sparse enough are returned
    unchanged."""
    pts = np.asarray(points, dtype=float)
    current = min_spacing(pts)
    if current >= spacing or current <= 0 or not np.isfinite(current):
        return pts
    c = pts.mean(axis=0) if center is None else np.asarray(center, dtype=float)
    return c + (pts - c) * (spacing / current)


# ----------------------------------------------------------------------
# Ground and simple shapes
# ----------------------------------------------------------------------


def grid(
    n: int,
    *,
    spacing: float | Sequence[float] = 3.0,
    columns: int | None = None,
    center: Sequence[float] = (0.0, 0.0, 0.0),
    yaw: float = 0.0,
) -> np.ndarray:
    """A rectangular grid in the horizontal plane (e.g. a takeoff grid)."""
    if n <= 0:
        return np.zeros((0, 3))
    sx, sy = (spacing, spacing) if np.isscalar(spacing) else tuple(spacing)  # type: ignore[misc]
    cols = columns or int(np.ceil(np.sqrt(n)))
    rows = int(np.ceil(n / cols))
    idx = np.arange(n)
    x = (idx % cols - (cols - 1) / 2) * sx
    y = (idx // cols - (rows - 1) / 2) * sy
    c = np.asarray(center, dtype=float)
    pts = np.column_stack([x, y, np.zeros(n)]) + c
    return _yaw(pts, c, yaw)


def line(n: int, *, length: float = 20.0, **placement) -> np.ndarray:
    u = np.linspace(-length / 2, length / 2, n) if n > 1 else np.zeros(n)
    return place_2d(np.column_stack([u, np.zeros(n)]), **placement)


def circle(n: int, *, radius: float = 10.0, start_angle: float = 90.0, **placement) -> np.ndarray:
    a = np.radians(start_angle) + 2 * np.pi * np.arange(n) / max(n, 1)
    return place_2d(np.column_stack([radius * np.cos(a), radius * np.sin(a)]), **placement)


def polygon(n: int, *, radius: float = 10.0, sides: int = 6, **placement) -> np.ndarray:
    a = np.pi / 2 + 2 * np.pi * np.arange(sides + 1) / sides
    outline = np.column_stack([radius * np.cos(a), radius * np.sin(a)])[:-1]
    return place_2d(_corners_first(outline, n), **placement)


def star(
    n: int, *, radius: float = 10.0, inner_ratio: float = 0.45, spikes: int = 5, **placement
) -> np.ndarray:
    k = 2 * spikes
    a = np.pi / 2 + 2 * np.pi * np.arange(k) / k
    r = np.where(np.arange(k) % 2 == 0, radius, radius * inner_ratio)
    outline = np.column_stack([r * np.cos(a), r * np.sin(a)])
    return place_2d(_spread_on_outline(outline, n), **placement)


def _spread_on_outline(outline: np.ndarray, n: int) -> np.ndarray:
    """Spreads points on a closed outline maximising their mutual distance.

    Plain arc-length spacing puts points of two converging branches (sharp
    spikes, cusps) too close to each other; farthest point sampling of a
    dense resampling avoids that.
    """
    dense = resample_polyline(outline, max(400, 24 * n), closed=True)
    return even_subset(dense, n)


def _corners_first(corners: np.ndarray, n: int) -> np.ndarray:
    """Distributes ``n`` points on a closed polygon, always including its
    corners when there are enough points."""
    k = len(corners)
    if n < k:
        return resample_polyline(corners, n, closed=True)
    closed = np.vstack([corners, corners[:1]])
    lengths = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    extra = _allocate(lengths, n - k)
    out = []
    for i in range(k):
        a, b = closed[i], closed[i + 1]
        m = extra[i]
        ts = np.arange(m + 1) / (m + 1)
        out.append(a + (b - a) * ts[:, None])
    return np.vstack(out)


def _allocate(weights: np.ndarray, total: int) -> np.ndarray:
    """Splits ``total`` into integers proportional to ``weights`` (largest remainder)."""
    w = np.asarray(weights, dtype=float)
    if total <= 0 or w.sum() <= 0:
        return np.zeros(len(w), dtype=int)
    exact = w / w.sum() * total
    base = np.floor(exact).astype(int)
    rest = total - base.sum()
    order = np.argsort(-(exact - base), kind="stable")
    base[order[:rest]] += 1
    return base


def heart(n: int, *, size: float = 20.0, **placement) -> np.ndarray:
    t = np.linspace(0, 2 * np.pi, 2000, endpoint=False)
    x = 16 * np.sin(t) ** 3
    y = 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)
    outline = np.column_stack([x, y])
    outline -= (outline.max(axis=0) + outline.min(axis=0)) / 2
    outline *= size / np.ptp(outline, axis=0).max()
    return place_2d(_spread_on_outline(outline, n), **placement)


def spiral(n: int, *, radius: float = 10.0, turns: float = 3.0, **placement) -> np.ndarray:
    t = np.linspace(0, 1, 4000)
    a = 2 * np.pi * turns * t
    curve = np.column_stack([radius * t * np.cos(a), radius * t * np.sin(a)])
    return place_2d(resample_polyline(curve, n), **placement)


def disc(n: int, *, radius: float = 10.0, **placement) -> np.ndarray:
    """A filled disc with evenly spread points (Vogel's sunflower pattern)."""
    k = np.arange(n) + 0.5
    r = radius * np.sqrt(k / max(n, 1))
    a = k * np.pi * (3 - np.sqrt(5))
    return place_2d(np.column_stack([r * np.cos(a), r * np.sin(a)]), **placement)


def rectangle(
    n: int, *, width: float = 20.0, height: float = 10.0, filled: bool = False, **placement
) -> np.ndarray:
    if not filled:
        corners = (
            np.array([[-width, height], [width, height], [width, -height], [-width, -height]]) / 2
        )
        return place_2d(_corners_first(corners, n), **placement)
    cols = max(1, int(round(np.sqrt(n * width / max(height, 1e-9)))))
    rows = int(np.ceil(n / cols))
    u = np.linspace(-width / 2, width / 2, cols) if cols > 1 else np.zeros(1)
    v = np.linspace(height / 2, -height / 2, rows) if rows > 1 else np.zeros(1)
    uu, vv = np.meshgrid(u, v)
    pts = np.column_stack([uu.ravel(), vv.ravel()])[:n]
    return place_2d(pts, **placement)


# ----------------------------------------------------------------------
# 3D shapes
# ----------------------------------------------------------------------


def sphere(
    n: int, *, radius: float = 10.0, center: Sequence[float] = (0.0, 0.0, 0.0)
) -> np.ndarray:
    """Points evenly spread on a sphere (Fibonacci lattice)."""
    k = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * k / max(n, 1))
    theta = np.pi * (1 + np.sqrt(5)) * k
    pts = np.column_stack([np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)])
    return np.asarray(center, dtype=float) + radius * pts


def helix(
    n: int,
    *,
    radius: float = 8.0,
    height: float = 20.0,
    turns: float = 3.0,
    center: Sequence[float] = (0.0, 0.0, 0.0),
) -> np.ndarray:
    t = np.linspace(0, 1, 4000)
    a = 2 * np.pi * turns * t
    curve = np.column_stack([radius * np.cos(a), radius * np.sin(a), height * (t - 0.5)])
    return resample_polyline(curve, n) + np.asarray(center, dtype=float)


def cube(
    n: int, *, size: float = 15.0, center: Sequence[float] = (0.0, 0.0, 0.0), yaw: float = 0.0
) -> np.ndarray:
    """Points evenly spread on the surface of a cube."""
    k = max(4, int(np.ceil(np.sqrt(n * 6))))
    g = np.linspace(-0.5, 0.5, k)
    uu, vv = np.meshgrid(g, g)
    uu, vv = uu.ravel(), vv.ravel()
    faces = []
    for axis in range(3):
        for sign in (-0.5, 0.5):
            f = np.empty((len(uu), 3))
            f[:, axis] = sign
            f[:, (axis + 1) % 3] = uu
            f[:, (axis + 2) % 3] = vv
            faces.append(f)
    cand = np.unique(np.round(np.vstack(faces), 9), axis=0) * size
    c = np.asarray(center, dtype=float)
    return _yaw(even_subset(cand, n) + c, c, yaw)


def torus(
    n: int,
    *,
    radius: float = 10.0,
    tube: float = 3.0,
    center: Sequence[float] = (0.0, 0.0, 0.0),
    plane: str = "xy",
) -> np.ndarray:
    ratio = 2 * np.pi * radius / (2 * np.pi * tube)
    rings = max(3, int(round(np.sqrt(n * ratio))))
    per_ring = max(3, int(np.ceil(n / rings)))
    u = 2 * np.pi * np.arange(rings) / rings
    v = 2 * np.pi * np.arange(per_ring) / per_ring
    uu, vv = np.meshgrid(u, v, indexing="ij")
    vv = vv + (np.arange(rings)[:, None] % 2) * np.pi / per_ring
    x = (radius + tube * np.cos(vv)) * np.cos(uu)
    y = (radius + tube * np.cos(vv)) * np.sin(uu)
    z = tube * np.sin(vv)
    pts = np.column_stack([x.ravel(), y.ravel(), z.ravel()])
    pts = even_subset(pts, n) if len(pts) > n else pts
    if plane == "xz":
        pts = pts[:, [0, 2, 1]]
    elif plane == "yz":
        pts = pts[:, [2, 0, 1]]
    return pts + np.asarray(center, dtype=float)


# ----------------------------------------------------------------------
# Text and images
# ----------------------------------------------------------------------


def text(n: int, *, text: str, height: float = 10.0, **placement) -> np.ndarray:
    """Renders ``text`` with the built-in 5x7 font; ``height`` is the height
    of one line of capital letters."""
    cells = np.asarray(render_text(text), dtype=float)
    if len(cells) == 0:
        raise ValueError("text produces no visible pixels")
    pitch = height / 7.0
    sub = 1
    while len(cells) * sub * sub < n:
        sub += 1
    offsets = (np.arange(sub) + 0.5) / sub - 0.5
    ox, oy = np.meshgrid(offsets, offsets)
    cand = (cells[:, None, :] + np.column_stack([ox.ravel(), oy.ravel()])[None, :, :]).reshape(
        -1, 2
    )
    cand[:, 1] *= -1
    cand *= pitch
    cand -= (cand.max(axis=0) + cand.min(axis=0)) / 2
    return place_2d(even_subset(cand, n), **placement)


def image(
    n: int,
    *,
    path: str | Path,
    size: float = 20.0,
    threshold: float = 0.2,
    invert: bool = False,
    **placement,
) -> tuple[np.ndarray, np.ndarray]:
    """Samples ``n`` points from the bright (or opaque) pixels of an image.

    Returns the points and their colours (0-255 RGB). Requires Pillow.
    """
    try:
        from PIL import Image
    except ImportError as ex:  # pragma: no cover - optional dependency
        raise RuntimeError("image formations require Pillow: pip install murmura[image]") from ex

    img = Image.open(path).convert("RGBA")
    scale = min(1.0, 400 / max(img.size))
    if scale < 1.0:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
    data = np.asarray(img, dtype=float) / 255.0
    rgb, alpha = data[..., :3], data[..., 3]
    luminance = rgb @ np.array([0.2126, 0.7152, 0.0722])
    if invert:
        luminance = 1.0 - luminance
    weight = luminance * alpha if np.any(alpha < 1.0) else luminance
    ys, xs = np.nonzero(weight > threshold)
    if len(xs) == 0:
        raise ValueError("no pixels above the threshold in the image")
    cand = np.column_stack([xs, -ys]).astype(float)
    colors = (rgb[ys, xs] * 255).round()
    cand -= (cand.max(axis=0) + cand.min(axis=0)) / 2
    extent = max(np.ptp(cand, axis=0).max(), 1.0)
    cand *= size / extent
    chosen = even_subset(cand, n)
    tree = cKDTree(cand)
    _, idx = tree.query(chosen)
    return place_2d(chosen, **placement), colors[idx].astype(int)
