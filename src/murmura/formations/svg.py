"""Static formations from SVG drawings.

Supported elements: ``path`` (all commands including arcs), ``line``,
``polyline``, ``polygon``, ``rect``, ``circle`` and ``ellipse``, with nested
``transform`` attributes. The stroke colour of an element (or its fill colour
if it has no stroke) becomes the colour of the drones placed on it.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np

from ..colors import RGB, parse_color
from .shapes import _allocate, place_2d, resample_polyline

__all__ = ("SvgShape", "parse_svg", "svg_points", "svg_formation")

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_COMMAND = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]")
_SKIP_TAGS = {
    "defs",
    "clipPath",
    "mask",
    "symbol",
    "marker",
    "pattern",
    "style",
    "title",
    "desc",
    "metadata",
    "text",
}


@dataclass
class SvgShape:
    points: np.ndarray
    """Dense polyline in SVG user units, shape ``(k, 2)``."""
    closed: bool
    color: RGB


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_transform(value: str | None) -> np.ndarray:
    m = np.eye(3)
    if not value:
        return m
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", value):
        a = [float(x) for x in _NUMBER.findall(args)]
        t = np.eye(3)
        if name == "matrix" and len(a) == 6:
            t = np.array([[a[0], a[2], a[4]], [a[1], a[3], a[5]], [0, 0, 1]])
        elif name == "translate" and a:
            t = np.array([[1, 0, a[0]], [0, 1, a[1] if len(a) > 1 else 0], [0, 0, 1]])
        elif name == "scale" and a:
            sx = a[0]
            sy = a[1] if len(a) > 1 else sx
            t = np.diag([sx, sy, 1.0])
        elif name == "rotate" and a:
            r = math.radians(a[0])
            c, s = math.cos(r), math.sin(r)
            t = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
            if len(a) == 3:
                pre = np.array([[1, 0, a[1]], [0, 1, a[2]], [0, 0, 1]])
                post = np.array([[1, 0, -a[1]], [0, 1, -a[2]], [0, 0, 1]])
                t = pre @ t @ post
        elif name == "skewX" and a:
            t = np.array([[1, math.tan(math.radians(a[0])), 0], [0, 1, 0], [0, 0, 1]])
        elif name == "skewY" and a:
            t = np.array([[1, 0, 0], [math.tan(math.radians(a[0])), 1, 0], [0, 0, 1]])
        m = m @ t
    return m


def _style(el: ET.Element, inherited: dict[str, str]) -> dict[str, str]:
    style = dict(inherited)
    for key in ("stroke", "fill"):
        if el.get(key) is not None:
            style[key] = el.get(key, "")
    for item in (el.get("style") or "").split(";"):
        if ":" in item:
            k, v = item.split(":", 1)
            if k.strip() in ("stroke", "fill"):
                style[k.strip()] = v.strip()
    return style


def _color(style: dict[str, str]) -> RGB:
    for key in ("stroke", "fill"):
        value = style.get(key)
        if value and value.lower() not in ("none", "transparent") and not value.startswith("url("):
            try:
                return parse_color(value)
            except ValueError:
                continue
    return (255, 255, 255)


def _cubic(p0, p1, p2, p3, k=24):
    t = np.linspace(0, 1, k + 1)[1:, None]
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3 * p3


def _quad(p0, p1, p2, k=16):
    t = np.linspace(0, 1, k + 1)[1:, None]
    return (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t**2 * p2


def _arc(p0, rx, ry, phi, large, sweep, p1):
    """Endpoint-parametrised elliptical arc to a polyline (SVG spec F.6.5)."""
    if np.allclose(p0, p1):
        return np.zeros((0, 2))
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return np.array([p1])
    phi = math.radians(phi)
    c, s = math.cos(phi), math.sin(phi)
    dx, dy = (p0 - p1) / 2
    x1 = c * dx + s * dy
    y1 = -s * dx + c * dy
    lam = (x1 / rx) ** 2 + (y1 / ry) ** 2
    if lam > 1:
        rx *= math.sqrt(lam)
        ry *= math.sqrt(lam)
    num = rx**2 * ry**2 - rx**2 * y1**2 - ry**2 * x1**2
    den = rx**2 * y1**2 + ry**2 * x1**2
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        coef = -coef
    cx1 = coef * rx * y1 / ry
    cy1 = -coef * ry * x1 / rx
    cx = c * cx1 - s * cy1 + (p0[0] + p1[0]) / 2
    cy = s * cx1 + c * cy1 + (p0[1] + p1[1]) / 2

    def angle(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    t1 = angle(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dt = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    k = max(8, int(abs(dt) / (math.pi / 32)))
    ts = t1 + dt * np.linspace(0, 1, k + 1)[1:]
    xs = cx + rx * np.cos(ts) * c - ry * np.sin(ts) * s
    ys = cy + rx * np.cos(ts) * s + ry * np.sin(ts) * c
    return np.column_stack([xs, ys])


def _tokenize_path(d: str):
    """Yields commands and their numeric arguments, handling compact arc flags."""
    pos = 0
    cmd = None
    while pos < len(d):
        m = _COMMAND.match(d, pos)
        if m:
            cmd = m.group()
            pos = m.end()
            if cmd in "Zz":
                yield cmd, []
            continue
        if d[pos] in " \t\r\n,":
            pos += 1
            continue
        if cmd is None:
            raise ValueError("path data must start with a command")
        arity = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}[
            cmd.upper()
        ]
        args: list[float] = []
        while len(args) < arity:
            while pos < len(d) and d[pos] in " \t\r\n,":
                pos += 1
            if cmd.upper() == "A" and len(args) in (3, 4):
                if pos >= len(d) or d[pos] not in "01":
                    raise ValueError("invalid arc flag in path data")
                args.append(float(d[pos]))
                pos += 1
                continue
            m = _NUMBER.match(d, pos)
            if not m:
                raise ValueError(f"invalid path data near {d[pos : pos + 20]!r}")
            args.append(float(m.group()))
            pos = m.end()
        yield cmd, args
        if cmd == "M":
            cmd = "L"
        elif cmd == "m":
            cmd = "l"


def _path_to_polylines(d: str) -> list[tuple[np.ndarray, bool]]:
    result: list[tuple[np.ndarray, bool]] = []
    current: list[np.ndarray] = []
    pos = np.zeros(2)
    start = np.zeros(2)
    last_ctrl = None
    last_cmd = ""

    def flush(closed: bool):
        nonlocal current
        if len(current) >= 2:
            result.append((np.vstack(current), closed))
        current = []

    for cmd, a in _tokenize_path(d):
        rel = cmd.islower()
        c = cmd.upper()
        base = pos if rel else np.zeros(2)
        if c == "M":
            flush(False)
            pos = base + a[:2]
            start = pos.copy()
            current = [pos[None, :]]
        elif c == "Z":
            if current:
                current.append(start[None, :])
                flush(True)
            pos = start.copy()
            current = [pos[None, :]]
        else:
            if not current:
                current = [pos[None, :]]
            if c == "L":
                pos = base + a[:2]
                current.append(pos[None, :])
            elif c == "H":
                pos = np.array([(pos[0] if rel else 0) + a[0], pos[1]])
                current.append(pos[None, :])
            elif c == "V":
                pos = np.array([pos[0], (pos[1] if rel else 0) + a[0]])
                current.append(pos[None, :])
            elif c in ("C", "S"):
                if c == "C":
                    c1, c2, end = base + a[0:2], base + a[2:4], base + a[4:6]
                else:
                    c1 = (
                        2 * pos - last_ctrl
                        if last_cmd in ("C", "S") and last_ctrl is not None
                        else pos
                    )
                    c2, end = base + a[0:2], base + a[2:4]
                current.append(_cubic(pos, c1, c2, end))
                last_ctrl = c2
                pos = end
            elif c in ("Q", "T"):
                if c == "Q":
                    c1, end = base + a[0:2], base + a[2:4]
                else:
                    c1 = (
                        2 * pos - last_ctrl
                        if last_cmd in ("Q", "T") and last_ctrl is not None
                        else pos
                    )
                    end = base + a[0:2]
                current.append(_quad(pos, c1, end))
                last_ctrl = c1
                pos = end
            elif c == "A":
                end = base + a[5:7]
                current.append(_arc(pos, a[0], a[1], a[2], bool(a[3]), bool(a[4]), end))
                pos = end
        last_cmd = c
    flush(False)
    return result


def _ellipse(cx, cy, rx, ry, k=128):
    t = np.linspace(np.pi, 3 * np.pi, k, endpoint=False)
    return np.column_stack([cx + rx * np.cos(t), cy + ry * np.sin(t)])


def _attr(el: ET.Element, name: str, default: float = 0.0) -> float:
    m = _NUMBER.match((el.get(name) or "").strip())
    return float(m.group()) if m else default


def parse_svg(source: str) -> list[SvgShape]:
    """Parses SVG source into dense polylines with colours."""
    root = ET.fromstring(source.encode("utf-8") if isinstance(source, str) else source)
    shapes: list[SvgShape] = []

    def visit(el: ET.Element, matrix: np.ndarray, style: dict[str, str]):
        tag = _local(el.tag)
        if tag in _SKIP_TAGS:
            return
        matrix = matrix @ _parse_transform(el.get("transform"))
        style = _style(el, style)
        polylines: list[tuple[np.ndarray, bool]] = []
        if tag == "path" and el.get("d"):
            polylines = _path_to_polylines(el.get("d", ""))
        elif tag == "line":
            polylines = [
                (
                    np.array(
                        [[_attr(el, "x1"), _attr(el, "y1")], [_attr(el, "x2"), _attr(el, "y2")]]
                    ),
                    False,
                )
            ]
        elif tag in ("polyline", "polygon"):
            nums = [float(v) for v in _NUMBER.findall(el.get("points") or "")]
            pts = np.array(nums[: len(nums) // 2 * 2]).reshape(-1, 2)
            if len(pts) >= 2:
                polylines = [(pts, tag == "polygon")]
        elif tag == "rect":
            x, y, w, h = _attr(el, "x"), _attr(el, "y"), _attr(el, "width"), _attr(el, "height")
            if w > 0 and h > 0:
                polylines = [(np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]]), True)]
        elif tag == "circle":
            r = _attr(el, "r")
            if r > 0:
                polylines = [(_ellipse(_attr(el, "cx"), _attr(el, "cy"), r, r), True)]
        elif tag == "ellipse":
            rx, ry = _attr(el, "rx"), _attr(el, "ry")
            if rx > 0 and ry > 0:
                polylines = [(_ellipse(_attr(el, "cx"), _attr(el, "cy"), rx, ry), True)]

        color = _color(style)
        for pts, closed in polylines:
            if closed and len(pts) > 2 and np.allclose(pts[0], pts[-1]):
                pts = pts[:-1]
            homo = np.column_stack([pts, np.ones(len(pts))]) @ matrix.T
            shapes.append(SvgShape(homo[:, :2], closed, color))
        for child in el:
            visit(child, matrix, style)

    visit(root, np.eye(3), {})
    return shapes


def _corner_indices(pts: np.ndarray, closed: bool, angle: float) -> list[int]:
    n = len(pts)
    idx = []
    rng = range(n) if closed else range(1, n - 1)
    for i in rng:
        a = pts[i] - pts[i - 1]
        b = pts[(i + 1) % n] - pts[i]
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na < 1e-9 or nb < 1e-9:
            continue
        turn = math.degrees(math.acos(max(-1.0, min(1.0, float(a @ b) / (na * nb)))))
        if turn > angle:
            idx.append(i)
    return idx


def _sample_shape(shape: SvgShape, count: int, angle: float) -> np.ndarray:
    pts = shape.points
    if count <= 0:
        return np.zeros((0, 2))
    corners = _corner_indices(pts, shape.closed, angle)
    anchors = sorted(set(corners + ([] if shape.closed else [0, len(pts) - 1])))
    if not anchors or count < len(anchors) + (0 if shape.closed else 0):
        return resample_polyline(pts, count, closed=shape.closed)
    # split into sections between consecutive anchors
    if shape.closed:
        sections = [
            np.vstack([pts[a : b + 1]]) if b > a else np.vstack([pts[a:], pts[: b + 1]])
            for a, b in zip(anchors, anchors[1:] + anchors[:1])
        ]
    else:
        sections = [pts[a : b + 1] for a, b in zip(anchors, anchors[1:])]
    lengths = np.array([np.sum(np.linalg.norm(np.diff(s, axis=0), axis=1)) for s in sections])
    extra = _allocate(lengths, count - len(anchors))
    out = []
    for sec, m in zip(sections, extra):
        dense = resample_polyline(sec, m + 2)
        out.append(dense[:-1])
    result = np.vstack(out)
    if not shape.closed:
        result = np.vstack([result, pts[-1:]])
    return result


def svg_points(
    source: str, n: int, *, size: float = 20.0, angle: float = 30.0
) -> tuple[np.ndarray, list[RGB]]:
    """Samples ``n`` points from an SVG drawing.

    The result is centred on the origin and scaled so that its larger extent
    equals ``size``. Points are returned as 2D ``(u, v)`` coordinates with
    ``u`` pointing right and ``v`` pointing up, together with their colours.
    Corners sharper than ``angle`` degrees are always kept when possible.
    """
    shapes = parse_svg(source)
    if not shapes:
        raise ValueError("the SVG file contains no drawable shapes")
    if n <= 0:
        return np.zeros((0, 2)), []

    lengths = np.array(
        [
            np.sum(
                np.linalg.norm(
                    np.diff(np.vstack([s.points, s.points[:1]]) if s.closed else s.points, axis=0),
                    axis=1,
                )
            )
            for s in shapes
        ]
    )
    counts = _allocate(lengths, n)
    pts_list, colors = [], []
    for shape, count in zip(shapes, counts):
        sampled = _sample_shape(shape, int(count), angle)
        pts_list.append(sampled)
        colors.extend([shape.color] * len(sampled))
    pts = np.vstack(pts_list)

    everything = np.vstack([s.points for s in shapes])
    lo, hi = everything.min(axis=0), everything.max(axis=0)
    centre = (lo + hi) / 2
    extent = float(max(hi - lo)) or 1.0
    scale = size / extent
    uv = np.column_stack([(pts[:, 0] - centre[0]) * scale, -(pts[:, 1] - centre[1]) * scale])
    return uv, colors


def svg_formation(n: int, *, source: str, size: float = 20.0, angle: float = 30.0, **placement):
    """Returns ``(points, colors)`` of an SVG drawing placed in 3D."""
    uv, colors = svg_points(source, n, size=size, angle=angle)
    return place_2d(uv, **placement), np.asarray(colors, dtype=int)
