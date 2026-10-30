"""Collision-aware return-to-home planning."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from .grouping import decompose_points
from .matching import as_points
from .transition import _candidate_pairs

__all__ = ("RTHPlan", "Path", "plan_smart_rth")


@dataclass
class Path:
    """A polyline travelled leg by leg, each leg with a trapezoidal velocity
    profile that starts and ends at rest."""

    waypoints: np.ndarray
    leg_durations: np.ndarray
    leg_accel_times: np.ndarray
    leg_peak_speeds: np.ndarray

    @property
    def duration(self) -> float:
        return float(np.sum(self.leg_durations))

    def position_at(self, t: np.ndarray) -> np.ndarray:
        t = np.atleast_1d(np.asarray(t, dtype=float))
        out = np.repeat(self.waypoints[-1][None, :], len(t), axis=0)
        start = 0.0
        out[t <= 0] = self.waypoints[0]
        for k in range(len(self.leg_durations)):
            dur = self.leg_durations[k]
            mask = (t > start) & (t <= start + dur)
            if np.any(mask):
                s = _trapezoid_distance(
                    t[mask] - start, dur, self.leg_accel_times[k], self.leg_peak_speeds[k]
                )
                a, b = self.waypoints[k], self.waypoints[k + 1]
                length = float(np.linalg.norm(b - a))
                ratio = s / length if length > 0 else np.ones_like(s)
                out[mask] = a + (b - a) * ratio[:, None]
            start += dur
        return out

    def keypoint_times(self, dt: float) -> np.ndarray:
        """Sampling times that capture every acceleration phase in detail."""
        times = [0.0]
        start = 0.0
        for k in range(len(self.leg_durations)):
            dur = float(self.leg_durations[k])
            ta = float(self.leg_accel_times[k])
            phases = [
                (start, start + ta, dt),
                (start + ta, start + dur - ta, max(dt * 4, 1.0)),
                (start + dur - ta, start + dur, dt),
            ]
            for a, b, step in phases:
                if b - a > 1e-9:
                    count = max(1, int(np.ceil((b - a) / step)))
                    times.extend(np.linspace(a, b, count + 1)[1:].tolist())
            start += dur
        return np.unique(np.round(np.asarray(times), 6))


def _trapezoid(length: float, vmax: float, acc: float) -> tuple[float, float, float]:
    """Returns ``(duration, accel_time, peak_speed)`` of a rest-to-rest move."""
    if length <= 1e-9:
        return 0.0, 0.0, 0.0
    if length >= vmax * vmax / acc:
        ta = vmax / acc
        return length / vmax + ta, ta, vmax
    ta = float(np.sqrt(length / acc))
    return 2 * ta, ta, acc * ta


def _trapezoid_distance(t: np.ndarray, duration: float, ta: float, vpeak: float) -> np.ndarray:
    acc = vpeak / ta if ta > 0 else 0.0
    t = np.clip(t, 0.0, duration)
    cruise = duration - 2 * ta
    s = np.where(
        t < ta,
        0.5 * acc * t * t,
        np.where(
            t < ta + cruise,
            0.5 * acc * ta * ta + vpeak * (t - ta),
            0.5 * acc * ta * ta
            + vpeak * cruise
            + vpeak * (t - ta - cruise)
            - 0.5 * acc * (t - ta - cruise) ** 2,
        ),
    )
    return s


def _make_path(waypoints: list[np.ndarray], vxy: float, vz: float, acc: float) -> Path:
    pts = [waypoints[0]]
    for p in waypoints[1:]:
        if np.linalg.norm(p - pts[-1]) > 1e-6:
            pts.append(p)
    durs, tas, peaks = [], [], []
    for a, b in zip(pts, pts[1:]):
        d = b - a
        length = float(np.linalg.norm(d))
        u = d / length
        uxy = float(np.hypot(u[0], u[1]))
        uz = abs(float(u[2]))
        vmax = min(vxy / uxy if uxy > 1e-9 else np.inf, vz / uz if uz > 1e-9 else np.inf)
        dur, ta, peak = _trapezoid(length, vmax, acc)
        durs.append(dur)
        tas.append(ta)
        peaks.append(peak)
    return Path(np.array(pts), np.array(durs), np.array(tas), np.array(peaks))


@dataclass
class RTHPlan:
    start_times: list[float] = field(default_factory=list)
    durations: list[float] = field(default_factory=list)
    inner_points: list[list[list[float]]] = field(default_factory=list)
    """Intermediate ``[t, x, y, z]`` points of each path, ``t`` relative to the
    drone's own start time."""

    @property
    def duration(self) -> float:
        return max((s + d for s, d in zip(self.start_times, self.durations)), default=0.0)

    def to_json(self) -> dict:
        return {
            "start_times": [round(v, 4) for v in self.start_times],
            "durations": [round(v, 4) for v in self.durations],
            "inner_points": self.inner_points,
            "version": 1,
        }


def plan_smart_rth(
    source: Sequence[Sequence[float]] | np.ndarray,
    target: Sequence[Sequence[float]] | np.ndarray,
    *,
    max_velocity_xy: float,
    max_velocity_z: float,
    max_acceleration: float,
    min_distance: float,
    rth_model: str = "straight_line_with_neck",
    neck_height: float | None = None,
    sample_dt: float = 0.2,
    delay_step: float = 1.0,
    max_delay: float = 120.0,
) -> RTHPlan:
    """Plans the return of every drone from ``source[i]`` to ``target[i]``.

    Each drone flies a straight line to a point above its target (the top of
    the "neck") and then descends vertically. With
    ``straight_line_with_neck_to_layers`` the neck tops of drones that land
    close to each other are placed on different altitude layers. Start times
    are staggered greedily (farthest drones first) so that no two drones come
    closer than ``min_distance`` while both are travelling.
    """
    src = as_points(source)
    dst = as_points(target)
    if len(src) != len(dst):
        raise ValueError("source and target must have the same number of points")
    n = len(src)
    if n == 0:
        return RTHPlan()
    if min(max_velocity_xy, max_velocity_z, max_acceleration) <= 0:
        raise ValueError("velocity and acceleration limits must be positive")

    neck = float(neck_height if neck_height is not None else max(min_distance, 2.0))
    layer = np.zeros(n)
    if rth_model == "straight_line_with_neck_to_layers":
        layer = np.asarray(decompose_points(dst[:, :2], min_distance=min_distance), dtype=float)
    elif rth_model != "straight_line_with_neck":
        raise ValueError(f"unknown RTH model: {rth_model!r}")

    paths: list[Path] = []
    for i in range(n):
        a, b = src[i], dst[i]
        if np.hypot(*(a[:2] - b[:2])) < 1e-3:
            waypoints = [a, b]
        else:
            top = b + np.array([0.0, 0.0, neck + layer[i] * min_distance])
            waypoints = [a, top, b]
        paths.append(_make_path(waypoints, max_velocity_xy, max_velocity_z, max_acceleration))

    durations = np.array([p.duration for p in paths])
    starts = np.zeros(n)

    if n > 1 and min_distance > 0:
        lo = np.array([p.waypoints.min(axis=0) for p in paths])
        hi = np.array([p.waypoints.max(axis=0) for p in paths])
        candidates = _candidate_pairs(lo, hi, min_distance)
        placed = np.zeros(n, dtype=bool)
        dt = 0.25
        for i in np.argsort(-durations, kind="stable"):
            neighbours = candidates[i][placed[candidates[i]]]
            placed[i] = True
            if len(neighbours) == 0:
                continue
            best_delay, best_sep = 0.0, -1.0
            delay = 0.0
            while delay <= max_delay + 1e-9:
                horizon = max(
                    delay + durations[i], float(np.max(starts[neighbours] + durations[neighbours]))
                )
                times = np.arange(0.0, horizon + dt, dt)
                # ignore the final metres of the neck where landing spots may be close
                mine = paths[i].position_at(times - delay)
                active_i = (times >= delay) & (mine[:, 2] > dst[i, 2] + 0.5)
                sep = np.inf
                for j in neighbours:
                    theirs = paths[j].position_at(times - starts[j])
                    active = active_i & (times >= starts[j]) & (theirs[:, 2] > dst[j, 2] + 0.5)
                    if np.any(active):
                        sep = min(
                            sep,
                            float(np.min(np.linalg.norm(mine[active] - theirs[active], axis=1))),
                        )
                if sep >= min_distance:
                    best_delay = delay
                    break
                if sep > best_sep:
                    best_delay, best_sep = delay, sep
                delay += delay_step
            starts[i] = best_delay

    inner: list[list[list[float]]] = []
    for p in paths:
        times = p.keypoint_times(sample_dt)
        times = times[(times > 1e-3) & (times < p.duration - 1e-3)]
        pos = p.position_at(times)
        inner.append(
            [[round(float(t), 4), *[round(float(v), 4) for v in xyz]] for t, xyz in zip(times, pos)]
        )

    return RTHPlan(
        start_times=[float(v) for v in starts],
        durations=[round(float(v), 4) for v in durations],
        inner_points=inner,
    )
