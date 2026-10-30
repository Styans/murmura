"""Staggered landing planning."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .._compat import KDTree as cKDTree
from .matching import as_points
from .transition import PROFILES, profile_progress

__all__ = ("plan_landing",)


def plan_landing(
    points: Sequence[Sequence[float]] | np.ndarray,
    *,
    min_distance: float,
    velocity: float,
    target_altitude: float = 0.0,
    spindown_time: float = 0.0,
    profile: str = "linear",
) -> tuple[list[float], list[float]]:
    """Plans a vertical landing for drones hovering above their landing spots.

    Each drone descends vertically to ``target_altitude``. Drones that are
    horizontally closer than ``min_distance`` are sequenced so that

    * while both are airborne, their 3D distance never drops below
      ``min_distance``, and
    * the later one touches down at least ``spindown_time`` seconds after the
      earlier one.

    Lower drones land first.

    Returns:
        the start time and the duration of the descent of every drone
    """
    if velocity <= 0:
        raise ValueError("landing velocity must be positive")
    pts = as_points(points)
    n = len(pts)
    if n == 0:
        return [], []

    kv = PROFILES[profile][0]
    heights = np.maximum(pts[:, 2] - target_altitude, 0.0)
    durations = kv * heights / velocity
    starts = np.zeros(n)
    if n == 1 or min_distance <= 0:
        return starts.tolist(), durations.tolist()

    tree = cKDTree(pts[:, :2])
    neighbours = tree.query_ball_point(pts[:, :2], np.nextafter(min_distance, 0.0))
    done = np.zeros(n, dtype=bool)

    def altitude(i: int, t: np.ndarray) -> np.ndarray:
        if durations[i] <= 0:
            return np.full_like(t, pts[i, 2])
        s = profile_progress((t - starts[i]) / durations[i], profile)
        return pts[i, 2] - heights[i] * s

    for i in np.lexsort((np.arange(n), heights)):
        s = 0.0
        for j in neighbours[i]:
            if j == i or not done[j]:
                continue
            h = float(np.hypot(*(pts[i, :2] - pts[j, :2])))
            gap = float(np.sqrt(max(0.0, min_distance**2 - h**2)))
            # touchdown separation
            s = max(s, starts[j] + durations[j] + spindown_time - durations[i])
            # vertical separation while both are airborne
            if profile == "linear":
                dz0 = pts[i, 2] - pts[j, 2]
                s = max(s, starts[j] + (gap - dz0) / velocity)
            else:
                t = np.linspace(starts[j], starts[j] + durations[j], 64)
                for _ in range(400):
                    starts[i] = s
                    if np.all(altitude(i, t) - altitude(j, t) >= gap - 1e-6):
                        break
                    s += 0.05
        starts[i] = max(0.0, s)
        done[i] = True

    return [float(v) for v in starts], [float(v) for v in durations]
