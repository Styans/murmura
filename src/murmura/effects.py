"""Light effects.

An effect maps the state of the swarm at a moment of a scene to a colour per
drone. Effects receive the time elapsed since the start of the scene, the
current drone positions and the colours attached to the formation points the
drones occupy (if the formation defines any).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .colors import parse_color

__all__ = (
    "Effect",
    "Fade",
    "FormationColors",
    "Gradient",
    "Pulse",
    "Rainbow",
    "Solid",
    "Sparkle",
    "Wave",
    "make_effect",
)

_AXES = {"x": 0, "y": 1, "z": 2}


def _axis_values(positions: np.ndarray, axis: str) -> np.ndarray:
    if axis == "radial":
        centre = positions.mean(axis=0)
        return np.linalg.norm(positions - centre, axis=1)
    return positions[:, _AXES[axis]]


def _normalise(values: np.ndarray) -> np.ndarray:
    lo, hi = float(np.min(values)), float(np.max(values))
    if hi - lo < 1e-9:
        return np.zeros_like(values)
    return (values - lo) / (hi - lo)


def _palette(colors: Sequence[Any], x: np.ndarray) -> np.ndarray:
    """Interpolates a list of colours at positions ``x ∈ [0, 1]``."""
    cols = np.array([parse_color(c) for c in colors], dtype=float)
    if len(cols) == 1:
        return np.repeat(cols, len(x), axis=0)
    stops = np.linspace(0.0, 1.0, len(cols))
    return np.column_stack([np.interp(x, stops, cols[:, k]) for k in range(3)])


def _hsv(h: np.ndarray, s: float = 1.0, v: float = 1.0) -> np.ndarray:
    h = np.mod(h, 1.0) * 6.0
    i = np.floor(h).astype(int) % 6
    f = h - np.floor(h)
    p = np.full_like(h, v * (1 - s))
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    vv = np.full_like(h, v)
    r = np.choose(i, [vv, q, p, p, t, vv])
    g = np.choose(i, [t, vv, vv, q, p, p])
    b = np.choose(i, [p, p, t, vv, vv, q])
    return np.column_stack([r, g, b]) * 255.0


@dataclass
class Effect:
    brightness: float = field(default=1.0, kw_only=True)

    #: Effects whose output does not change over time for a static formation
    static: bool = field(default=False, init=False)

    def colors(self, t: float, positions: np.ndarray, base: np.ndarray | None) -> np.ndarray:
        raise NotImplementedError

    def __call__(
        self, t: float, positions: np.ndarray, base: np.ndarray | None = None
    ) -> np.ndarray:
        out = self.colors(t, np.asarray(positions, dtype=float), base) * self.brightness
        return np.clip(np.round(out), 0, 255)


@dataclass
class Solid(Effect):
    color: Any = "white"

    def __post_init__(self):
        self.static = True

    def colors(self, t, positions, base):
        return np.tile(np.array(parse_color(self.color), dtype=float), (len(positions), 1))


@dataclass
class FormationColors(Effect):
    """Uses the colours defined by the formation (SVG strokes, image pixels).
    Drones without a formation colour get ``fallback``."""

    fallback: Any = "white"

    def __post_init__(self):
        self.static = True

    def colors(self, t, positions, base):
        if base is None:
            return np.tile(np.array(parse_color(self.fallback), dtype=float), (len(positions), 1))
        return np.asarray(base, dtype=float)


@dataclass
class Gradient(Effect):
    colors_: list = field(default_factory=lambda: ["#ff0040", "#2050ff"])
    axis: str = "x"

    def __post_init__(self):
        self.static = True

    def colors(self, t, positions, base):
        return _palette(self.colors_, _normalise(_axis_values(positions, self.axis)))


@dataclass
class Rainbow(Effect):
    period: float = 6.0
    axis: str = "x"
    spread: float = 1.0
    saturation: float = 1.0

    def colors(self, t, positions, base):
        x = _normalise(_axis_values(positions, self.axis)) * self.spread
        return _hsv(x + t / max(self.period, 1e-6), self.saturation, 1.0)


@dataclass
class Pulse(Effect):
    color: Any = "white"
    period: float = 2.0
    minimum: float = 0.15
    use_formation_colors: bool = False

    def colors(self, t, positions, base):
        level = self.minimum + (1 - self.minimum) * 0.5 * (
            1 - np.cos(2 * np.pi * t / max(self.period, 1e-6))
        )
        if self.use_formation_colors and base is not None:
            col = np.asarray(base, dtype=float)
        else:
            col = np.tile(np.array(parse_color(self.color), dtype=float), (len(positions), 1))
        return col * level


@dataclass
class Wave(Effect):
    colors_: list = field(default_factory=lambda: ["#00e5ff", "#ff00aa"])
    speed: float = 6.0
    wavelength: float = 12.0
    axis: str = "x"

    def colors(self, t, positions, base):
        x = _axis_values(positions, self.axis)
        phase = (x - self.speed * t) / max(self.wavelength, 1e-6)
        return _palette(self.colors_, 0.5 * (1 + np.sin(2 * np.pi * phase)))


@dataclass
class Sparkle(Effect):
    color: Any = "white"
    background: Any = "#101020"
    rate: float = 0.6
    """Average number of sparkles per drone per second."""
    flash: float = 0.25
    seed: int = 7

    def colors(self, t, positions, base):
        n = len(positions)
        # deterministic: every flash-long time slot rolls its own random numbers
        slot = int(np.floor(max(t, 0.0) / max(self.flash, 1e-3)))
        probability = min(1.0, self.rate * self.flash)
        lit = np.random.default_rng([self.seed, slot]).random(n) < probability
        bg = np.array(parse_color(self.background), dtype=float)
        fg = np.array(parse_color(self.color), dtype=float)
        out = np.tile(bg, (n, 1))
        out[lit] = fg
        return out


@dataclass
class Fade(Effect):
    """Fades from ``start`` to ``end`` over ``duration`` seconds of the scene."""

    start: Any = "black"
    end: Any = "white"
    duration: float = 3.0

    def colors(self, t, positions, base):
        r = min(1.0, max(0.0, t / max(self.duration, 1e-6)))
        a = np.array(parse_color(self.start), dtype=float)
        b = np.array(parse_color(self.end), dtype=float)
        return np.tile(a + (b - a) * r, (len(positions), 1))


_EFFECTS = {
    "solid": Solid,
    "formation": FormationColors,
    "source": FormationColors,
    "gradient": Gradient,
    "rainbow": Rainbow,
    "pulse": Pulse,
    "wave": Wave,
    "sparkle": Sparkle,
    "fade": Fade,
}


def make_effect(spec: dict[str, Any] | str | None, *, default: Effect | None = None) -> Effect:
    """Creates an effect from a description such as ``{"effect": "rainbow",
    "period": 4}`` or a plain colour string (which yields a solid colour)."""
    if spec is None:
        return default or Solid("white")
    if isinstance(spec, str):
        if spec.lower() in _EFFECTS:
            return _EFFECTS[spec.lower()]()
        return Solid(color=spec)
    spec = dict(spec)
    kind = str(spec.pop("effect", spec.pop("type", "solid"))).lower()
    if kind not in _EFFECTS:
        raise ValueError(
            f"unknown light effect {kind!r}; known effects: {', '.join(sorted(_EFFECTS))}"
        )
    if "colors" in spec:
        spec["colors_"] = spec.pop("colors")
    if "min" in spec:
        spec["minimum"] = spec.pop("min")
    return _EFFECTS[kind](**spec)
