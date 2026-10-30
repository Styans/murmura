"""Drone trajectories represented as chains of time-parametrised Bézier segments."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np

from .bezier import (
    elevate_to_cubic,
    eval_cubic,
    eval_cubic_derivative,
    eval_cubic_second_derivative,
    fit_samples,
)

__all__ = ("Trajectory", "TrajectoryPoint")

Vec3 = tuple[float, float, float]


@dataclass
class TrajectoryPoint:
    """A single keypoint of a trajectory.

    ``controls`` holds the inner control points of the segment that *ends* at
    this point (0, 1 or 2 points). The first point of a trajectory never has
    control points.
    """

    t: float
    pos: Vec3
    controls: list[Vec3] = field(default_factory=list)


class Trajectory:
    """A continuous 3D trajectory with absolute (show-relative) timestamps.

    Positions before the first point are clamped to the first point and
    positions after the last point are clamped to the last point.
    """

    def __init__(self, points: Iterable[TrajectoryPoint] | None = None):
        self._points: list[TrajectoryPoint] = list(points or [])
        self._cache: tuple[np.ndarray, np.ndarray] | None = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_samples(
        cls,
        times: Sequence[float] | np.ndarray,
        positions: Sequence[Sequence[float]] | np.ndarray,
        *,
        tolerance: float = 0.03,
    ) -> Trajectory:
        """Creates a compact trajectory that approximates sampled positions."""
        return cls(
            TrajectoryPoint(t, _vec(p), [_vec(c) for c in cps])
            for t, p, cps in fit_samples(times, positions, tolerance=tolerance)
        )

    @classmethod
    def stationary(
        cls, pos: Sequence[float], start: float = 0.0, end: float | None = None
    ) -> Trajectory:
        traj = cls([TrajectoryPoint(float(start), _vec(pos))])
        if end is not None and end > start:
            traj.hold_until(end)
        return traj

    def _invalidate(self) -> None:
        self._cache = None

    def _require_points(self) -> TrajectoryPoint:
        if not self._points:
            raise ValueError("trajectory is empty; add a starting point first")
        return self._points[-1]

    def start_at(self, t: float, pos: Sequence[float]) -> Trajectory:
        if self._points:
            raise ValueError("trajectory already has a starting point")
        self._points.append(TrajectoryPoint(float(t), _vec(pos)))
        self._invalidate()
        return self

    def _append(self, t: float, pos: Sequence[float], controls: list[Vec3]) -> Trajectory:
        last = self._require_points()
        t = float(t)
        if t < last.t - 1e-9:
            raise ValueError(f"new point at t={t} precedes the end of the trajectory (t={last.t})")
        if t <= last.t + 1e-9:
            # Zero-length segment: only allowed if it does not move the drone
            if np.allclose(last.pos, pos, atol=1e-6):
                return self
            raise ValueError(f"cannot jump to a new position at t={t} without elapsed time")
        self._points.append(TrajectoryPoint(t, _vec(pos), controls))
        self._invalidate()
        return self

    def hold_until(self, t: float) -> Trajectory:
        """Keeps the drone hovering at its current position until ``t``."""
        last = self._require_points()
        if t > last.t + 1e-9:
            self._append(t, last.pos, [])
        return self

    def line_to(self, t: float, pos: Sequence[float]) -> Trajectory:
        """Moves to ``pos`` at constant velocity, arriving at ``t``."""
        return self._append(t, pos, [])

    def smooth_to(self, t: float, pos: Sequence[float], profile: str = "smooth") -> Trajectory:
        """Moves to ``pos`` along a straight line with the given velocity profile.

        Profiles:
            ``smooth``: starts and stops at rest (cubic ease-in-out, peak
            velocity 1.5x the average, peak acceleration 6·d/T²)
            ``linear``: constant velocity
            ``ease_in``: starts at rest, arrives at full speed
            ``ease_out``: starts at full speed, stops at rest
        """
        last = self._require_points()
        p0 = last.pos
        if profile == "smooth":
            controls = [p0, _vec(pos)]
        elif profile == "linear":
            controls = []
        elif profile == "ease_in":
            controls = [p0]
        elif profile == "ease_out":
            controls = [_vec(pos)]
        else:
            raise ValueError(f"unknown velocity profile: {profile!r}")
        if np.allclose(p0, pos, atol=1e-9):
            controls = []
        return self._append(t, pos, controls)

    def curve_to(self, t: float, pos: Sequence[float], *controls: Sequence[float]) -> Trajectory:
        """Appends a quadratic or cubic Bézier segment with explicit control points."""
        return self._append(t, pos, [_vec(c) for c in controls])

    def extend_with_samples(
        self,
        times: Sequence[float] | np.ndarray,
        positions: Sequence[Sequence[float]] | np.ndarray,
        *,
        tolerance: float = 0.03,
    ) -> Trajectory:
        """Appends a fitted approximation of sampled motion.

        The first sample must coincide with the end of the trajectory.
        """
        last = self._require_points()
        fitted = fit_samples(times, positions, tolerance=tolerance)
        if not fitted:
            return self
        t0, p0, _ = fitted[0]
        if abs(t0 - last.t) > 1e-6 or not np.allclose(p0, last.pos, atol=1e-3):
            raise ValueError("sampled motion must start where the trajectory ends")
        for t, p, cps in fitted[1:]:
            self._append(t, p, [_vec(c) for c in cps])
        return self

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def points(self) -> list[TrajectoryPoint]:
        return self._points

    def __len__(self) -> int:
        return len(self._points)

    def __bool__(self) -> bool:
        return bool(self._points)

    @property
    def start_time(self) -> float:
        return self._points[0].t if self._points else 0.0

    @property
    def end_time(self) -> float:
        return self._points[-1].t if self._points else 0.0

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def first_position(self) -> Vec3:
        self._require_points()
        return self._points[0].pos

    @property
    def last_position(self) -> Vec3:
        return self._require_points().pos

    def first_movement_time(self) -> float:
        """Returns the time when the drone first leaves its starting position."""
        if not self._points:
            return 0.0
        p0 = np.asarray(self._points[0].pos)
        for prev, point in zip(self._points, self._points[1:]):
            moved = not np.allclose(point.pos, p0, atol=1e-6) or any(
                not np.allclose(c, p0, atol=1e-6) for c in point.controls
            )
            if moved:
                return prev.t
        return self._points[0].t

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _segments(self) -> tuple[np.ndarray, np.ndarray]:
        if self._cache is None:
            pts = self._points
            times = np.array([p.t for p in pts], dtype=float)
            if len(pts) >= 2:
                cps = np.stack(
                    [elevate_to_cubic(a.pos, b.controls, b.pos) for a, b in zip(pts, pts[1:])]
                )
            else:
                cps = np.zeros((0, 4, 3))
            self._cache = (times, cps)
        return self._cache

    def _locate(self, t) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        times, cps = self._segments()
        t = np.atleast_1d(np.asarray(t, dtype=float))
        idx = np.clip(np.searchsorted(times, t, side="right") - 1, 0, len(times) - 2)
        dt = times[idx + 1] - times[idx]
        u = np.clip((t - times[idx]) / np.where(dt > 0, dt, 1.0), 0.0, 1.0)
        inside = (t >= times[0]) & (t <= times[-1])
        return cps[idx], u, dt, inside

    def position_at(self, t) -> np.ndarray:
        """Evaluates the position at time(s) ``t``; returns shape ``(k, 3)``."""
        self._require_points()
        if len(self._points) == 1:
            return np.tile(np.asarray(self._points[0].pos, float), (np.size(t), 1))
        cps, u, _, _ = self._locate(t)
        return eval_cubic(cps, u)

    def velocity_at(self, t) -> np.ndarray:
        """Evaluates the velocity (m/s) at time(s) ``t``; returns shape ``(k, 3)``."""
        self._require_points()
        if len(self._points) == 1:
            return np.zeros((np.size(t), 3))
        cps, u, dt, inside = self._locate(t)
        vel = eval_cubic_derivative(cps, u) / np.where(dt > 0, dt, np.inf)[:, None]
        vel[~inside] = 0.0
        return vel

    def acceleration_at(self, t) -> np.ndarray:
        """Evaluates the acceleration (m/s²) at time(s) ``t``; returns shape ``(k, 3)``."""
        self._require_points()
        if len(self._points) == 1:
            return np.zeros((np.size(t), 3))
        cps, u, dt, inside = self._locate(t)
        acc = eval_cubic_second_derivative(cps, u) / np.where(dt > 0, dt * dt, np.inf)[:, None]
        acc[~inside] = 0.0
        return acc

    # ------------------------------------------------------------------
    # Transformations
    # ------------------------------------------------------------------

    def copy(self) -> Trajectory:
        return Trajectory(TrajectoryPoint(p.t, p.pos, list(p.controls)) for p in self._points)

    def shifted(self, dt: float = 0.0, offset: Sequence[float] = (0.0, 0.0, 0.0)) -> Trajectory:
        """Returns a copy shifted in time by ``dt`` and in space by ``offset``."""
        o = np.asarray(offset, dtype=float)
        return Trajectory(
            TrajectoryPoint(
                p.t + dt,
                _vec(np.asarray(p.pos) + o),
                [_vec(np.asarray(c) + o) for c in p.controls],
            )
            for p in self._points
        )

    def sliced(
        self, start: float, end: float, *, tolerance: float = 0.01, fps: float = 20.0
    ) -> Trajectory:
        """Returns the part of the trajectory between ``start`` and ``end``,
        re-fitted from dense samples."""
        if end <= start:
            raise ValueError("slice end must be after slice start")
        times = np.linspace(start, end, max(2, int(np.ceil((end - start) * fps)) + 1))
        return Trajectory.from_samples(times, self.position_at(times), tolerance=tolerance)


def _vec(p: Sequence[float]) -> Vec3:
    x, y, z = (float(v) for v in p)
    return (x, y, z)
