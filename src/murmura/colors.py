"""Colour parsing and conversion helpers. Colours are RGB triplets of ints in 0-255."""

from __future__ import annotations

import colorsys
import re
from collections.abc import Sequence

import numpy as np

__all__ = ("RGB", "NAMED_COLORS", "parse_color", "hsv_to_rgb", "blend", "to_rgb_array")

RGB = tuple[int, int, int]

NAMED_COLORS: dict[str, RGB] = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "orange": (255, 128, 0),
    "purple": (128, 0, 255),
    "pink": (255, 64, 160),
    "gold": (255, 180, 20),
    "warmwhite": (255, 200, 140),
    "coolwhite": (200, 220, 255),
    "off": (0, 0, 0),
}

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_FUNC = re.compile(r"^rgba?\(\s*([^)]*)\)$")


def _clamp(v: float) -> int:
    return int(min(255, max(0, round(v))))


def parse_color(value: str | Sequence[float] | None, default: RGB = (255, 255, 255)) -> RGB:
    """Parses a colour given as a name, ``#rgb`` / ``#rrggbb``, ``rgb(r, g, b)``
    (ints or percentages) or a sequence of three numbers.

    Sequences whose components are all within ``[0, 1]`` and contain a
    non-integer value are treated as normalised floats.
    """
    if value is None:
        return default
    if isinstance(value, str):
        s = value.strip().lower().replace(" ", "")
        if s in ("", "none", "transparent", "currentcolor", "inherit"):
            return default
        if s in NAMED_COLORS:
            return NAMED_COLORS[s]
        m = _HEX.match(s)
        if m:
            h = m.group(1)
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        m = _FUNC.match(s)
        if m:
            parts = [p for p in m.group(1).split(",") if p]
            if len(parts) < 3:
                raise ValueError(f"invalid colour: {value!r}")
            comps = []
            for p in parts[:3]:
                if p.endswith("%"):
                    comps.append(_clamp(float(p[:-1]) * 2.55))
                else:
                    comps.append(_clamp(float(p)))
            return (comps[0], comps[1], comps[2])
        raise ValueError(f"invalid colour: {value!r}")

    comps = [float(c) for c in value]
    if len(comps) < 3:
        raise ValueError(f"invalid colour: {value!r}")
    comps = comps[:3]
    if all(0.0 <= c <= 1.0 for c in comps) and any(c != int(c) for c in comps):
        comps = [c * 255.0 for c in comps]
    return (_clamp(comps[0]), _clamp(comps[1]), _clamp(comps[2]))


def hsv_to_rgb(h: float, s: float = 1.0, v: float = 1.0) -> RGB:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (_clamp(r * 255), _clamp(g * 255), _clamp(b * 255))


def blend(a: Sequence[float], b: Sequence[float], ratio: float) -> RGB:
    ratio = min(1.0, max(0.0, ratio))
    return tuple(_clamp(x + (y - x) * ratio) for x, y in zip(a, b))  # type: ignore[return-value]


def to_rgb_array(colors) -> np.ndarray:
    """Converts a sequence of colours into an ``(n, 3)`` float array."""
    return np.asarray(
        [parse_color(c) if not isinstance(c, np.ndarray) else c for c in colors], dtype=float
    )
