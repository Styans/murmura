"""Takeoff and landing in waves.

Drones standing closer than the minimum distance cannot climb side by side.
They are split into waves (a checkerboard on a square pad grid): the drones of
one wave are at least the minimum distance apart, so a whole wave can climb at
once. Waves climb one after the other, each to its own altitude layer - the
first wave highest - and a wave starts only when the drones above it are far
enough away. Landing is the same plan played backwards.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .._compat import KDTree as cKDTree
from .grouping import plan_takeoff
from .matching import as_points
from .transition import PROFILES, profile_progress

__all__ = ("plan_waves", "takeoff_layers")


def takeoff_layers(
    points: Sequence[Sequence[float]] | np.ndarray, *, min_distance: float
) -> tuple[np.ndarray, float]:
    """Splits pad positions into waves.

    Returns the wave of every drone (wave 0 is the largest) and the vertical
    gap between altitude layers that keeps drones of different waves at least
    ``min_distance`` apart. One wave and a zero gap mean that every drone can
    take off at once.
    """
    pts = as_points(points)
    groups = np.asarray(plan_takeoff(pts, min_distance=min_distance), dtype=int)
    if len(pts) < 2 or groups.max(initial=0) == 0:
        return groups, 0.0
    horizontal = pts[:, :2]
    pairs = np.array(sorted(cKDTree(horizontal).query_pairs(np.nextafter(min_distance, 0.0))))
    pairs = pairs[groups[pairs[:, 0]] != groups[pairs[:, 1]]]
    closest = float(
        np.min(np.linalg.norm(horizontal[pairs[:, 0]] - horizontal[pairs[:, 1]], axis=1))
    )
    gap = float(np.sqrt(max(min_distance**2 - closest**2, 0.0)))
    # a little margin, rounded up to whole decimetres
    return groups, float(np.ceil(gap * 1.05 * 10.0 - 1e-9) / 10.0)


def plan_waves(
    heights: Sequence[float],
    *,
    gap: float,
    velocity: float,
    max_acceleration: float,
    min_offset: float = 0.0,
    profile: str = "smooth",
) -> tuple[np.ndarray, np.ndarray]:
    """Schedules the climb of waves that leave the ground one after another.

    ``heights[k]`` is the climb of wave ``k`` (waves leave in this order, so
    the heights should decrease by at least ``gap``). Wave ``k`` starts as
    soon as it stays at least ``gap`` below every earlier wave for the whole
    climb, and not earlier than ``min_offset`` seconds after the previous
    wave.

    Returns the start time and the duration of every wave. Played backwards
    the same schedule is a landing: wave ``k`` touches down at
    ``total - start[k]``.
    """
    if velocity <= 0:
        raise ValueError("climb velocity must be positive")
    kv, ka = PROFILES[profile]
    h = np.maximum(np.asarray(heights, dtype=float), 0.0)
    durations = kv * h / velocity
    if ka > 0 and max_acceleration > 0:
        durations = np.maximum(durations, np.sqrt(ka * h / max_acceleration))
    starts = np.zeros(len(h))

    def altitude(k: int, t: np.ndarray) -> np.ndarray:
        if durations[k] <= 0:
            return np.full_like(t, h[k])
        return h[k] * profile_progress((t - starts[k]) / durations[k], profile)

    def safe(k: int) -> bool:
        t = np.linspace(starts[k], starts[k] + durations[k], 257)
        z = altitude(k, t)
        return all(np.all(altitude(j, t) - z >= gap - 1e-6) for j in range(k))

    for k in range(1, len(h)):
        lo = starts[k - 1] + min_offset
        hi = max(lo, float(np.max(starts[:k] + durations[:k])))
        starts[k] = lo
        if gap <= 0 or safe(k):
            continue
        # a later start only increases the separation: bisect
        for _ in range(40):
            starts[k] = 0.5 * (lo + hi)
            if safe(k):
                hi = starts[k]
            else:
                lo = starts[k]
        starts[k] = hi
    return starts, durations
