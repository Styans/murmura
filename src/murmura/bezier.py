"""Time-parametrised Bézier curves and curve fitting.

A drone trajectory is a chain of Bézier segments. Every segment starts where
the previous one ended and is parametrised *by time*: for a segment spanning
``[t0, t1]`` the curve parameter is ``u = (t - t0) / (t1 - t0)``. A segment can
be linear (no inner control points), quadratic (one) or cubic (two).

The fitter in this module converts densely sampled positions into a compact
chain of cubic Hermite segments whose velocity is continuous at every joint
and whose position error stays below a user-defined tolerance.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

__all__ = (
    "elevate_to_cubic",
    "eval_cubic",
    "eval_cubic_derivative",
    "eval_cubic_second_derivative",
    "fit_samples",
)

_STATIONARY_EPS = 1e-4
"""Two samples closer than this (in metres) are treated as the same position."""


def elevate_to_cubic(
    p0: np.ndarray, controls: Sequence[Sequence[float]], p3: np.ndarray
) -> np.ndarray:
    """Returns the four control points of the cubic curve equivalent to a
    linear, quadratic or cubic segment.
    """
    p0 = np.asarray(p0, dtype=float)
    p3 = np.asarray(p3, dtype=float)
    k = len(controls)
    if k == 0:
        d = p3 - p0
        return np.array([p0, p0 + d / 3.0, p0 + 2.0 * d / 3.0, p3])
    if k == 1:
        q = np.asarray(controls[0], dtype=float)
        return np.array([p0, p0 + 2.0 / 3.0 * (q - p0), p3 + 2.0 / 3.0 * (q - p3), p3])
    if k == 2:
        return np.array([p0, np.asarray(controls[0], float), np.asarray(controls[1], float), p3])
    raise ValueError(f"segments may have at most 2 inner control points, got {k}")


def eval_cubic(cps: np.ndarray, u: np.ndarray) -> np.ndarray:
    """Evaluates cubic Bézier curves.

    Args:
        cps: control points, shape ``(4, 3)`` or ``(m, 4, 3)``
        u: curve parameters in ``[0, 1]``, shape ``()`` / ``(k,)`` for a single
            curve or ``(m,)`` for ``m`` curves evaluated pairwise
    """
    u = np.asarray(u, dtype=float)[..., None]
    v = 1.0 - u
    if cps.ndim == 2:
        p0, p1, p2, p3 = cps
    else:
        p0, p1, p2, p3 = cps[:, 0], cps[:, 1], cps[:, 2], cps[:, 3]
    return v * v * v * p0 + 3.0 * v * v * u * p1 + 3.0 * v * u * u * p2 + u * u * u * p3


def eval_cubic_derivative(cps: np.ndarray, u: np.ndarray) -> np.ndarray:
    """First derivative of cubic Bézier curves with respect to ``u``."""
    u = np.asarray(u, dtype=float)[..., None]
    v = 1.0 - u
    if cps.ndim == 2:
        p0, p1, p2, p3 = cps
    else:
        p0, p1, p2, p3 = cps[:, 0], cps[:, 1], cps[:, 2], cps[:, 3]
    return 3.0 * (v * v * (p1 - p0) + 2.0 * v * u * (p2 - p1) + u * u * (p3 - p2))


def eval_cubic_second_derivative(cps: np.ndarray, u: np.ndarray) -> np.ndarray:
    """Second derivative of cubic Bézier curves with respect to ``u``."""
    u = np.asarray(u, dtype=float)[..., None]
    v = 1.0 - u
    if cps.ndim == 2:
        p0, p1, p2, p3 = cps
    else:
        p0, p1, p2, p3 = cps[:, 0], cps[:, 1], cps[:, 2], cps[:, 3]
    return 6.0 * (v * (p2 - 2.0 * p1 + p0) + u * (p3 - 2.0 * p2 + p1))


def _estimate_velocities(t: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Estimates the velocity of the sampled motion at every sample.

    Interior samples use the non-uniform three-point central difference.
    Samples that touch a stationary interval get zero velocity so that hover
    sections are reproduced exactly instead of wobbling around the hover point.
    """
    n = len(t)
    v = np.zeros_like(q)
    if n < 2:
        return v

    h = np.diff(t)
    dq = np.diff(q, axis=0)
    slopes = dq / h[:, None]
    moving = np.linalg.norm(dq, axis=1) > _STATIONARY_EPS

    v[0] = slopes[0]
    v[-1] = slopes[-1]
    if n > 2:
        h0 = h[:-1, None]
        h1 = h[1:, None]
        v[1:-1] = (slopes[:-1] * h1 + slopes[1:] * h0) / (h0 + h1)

    still = np.zeros(n, dtype=bool)
    still[:-1] |= ~moving
    still[1:] |= ~moving
    v[still] = 0.0
    return v


def _hermite_controls(t, q, v, i: int, j: int) -> np.ndarray:
    dt = t[j] - t[i]
    p0 = q[i]
    p3 = q[j]
    return np.array([p0, p0 + v[i] * (dt / 3.0), p3 - v[j] * (dt / 3.0), p3])


def _fit_error(t, q, v, i: int, j: int) -> float:
    if j - i < 2:
        return 0.0
    cps = _hermite_controls(t, q, v, i, j)
    u = (t[i + 1 : j] - t[i]) / (t[j] - t[i])
    diff = eval_cubic(cps, u) - q[i + 1 : j]
    return float(np.sqrt(np.max(np.einsum("ij,ij->i", diff, diff))))


def _longest_fit(t, q, v, i: int, tolerance: float, max_samples: int) -> int:
    n = len(t)
    limit = min(n - 1, i + max_samples)

    # Fast path for hover sections: extend over every stationary sample.
    if np.all(np.abs(q[i + 1] - q[i]) <= _STATIONARY_EPS):
        j = i + 1
        while j < limit and np.all(np.abs(q[j + 1] - q[i]) <= _STATIONARY_EPS):
            j += 1
        return j

    best = i + 1
    step = 2
    candidate = min(i + step, limit)
    while candidate > best:
        if _fit_error(t, q, v, i, candidate) <= tolerance:
            best = candidate
            step *= 2
            candidate = min(i + step, limit)
        else:
            break
    else:
        return best

    lo, hi = best, candidate
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _fit_error(t, q, v, i, mid) <= tolerance:
            lo = mid
        else:
            hi = mid
    return lo


def _classify(cps: np.ndarray, eps: float = 1e-6) -> list[list[float]]:
    """Returns the inner control points to store for a cubic segment, dropping
    them when the segment is a hover or a constant-velocity line."""
    p0, p1, p2, p3 = cps
    linear1 = p0 + (p3 - p0) / 3.0
    linear2 = p0 + 2.0 * (p3 - p0) / 3.0
    if np.allclose(p1, linear1, atol=eps) and np.allclose(p2, linear2, atol=eps):
        return []
    return [p1.tolist(), p2.tolist()]


def fit_samples(
    times: Sequence[float] | np.ndarray,
    positions: Sequence[Sequence[float]] | np.ndarray,
    *,
    tolerance: float = 0.03,
    max_samples_per_segment: int = 512,
) -> list[tuple[float, list[float], list[list[float]]]]:
    """Fits a chain of time-parametrised Bézier segments to sampled positions.

    Args:
        times: sample timestamps in seconds, strictly increasing
        positions: sampled positions, shape ``(n, 3)``
        tolerance: maximum allowed deviation from the samples, in metres
        max_samples_per_segment: upper bound on the number of samples covered
            by a single segment

    Returns:
        trajectory points ``(t, position, inner_controls)``; the first point
        never has inner control points
    """
    t = np.asarray(times, dtype=float).reshape(-1)
    q = np.asarray(positions, dtype=float).reshape(-1, 3)
    if len(t) != len(q):
        raise ValueError("times and positions must have the same length")
    if len(t) == 0:
        return []

    # Drop samples with duplicate timestamps, keeping the last one
    keep = np.ones(len(t), dtype=bool)
    keep[:-1] = np.diff(t) > 1e-9
    if np.any(np.diff(t) < -1e-9):
        raise ValueError("timestamps must be non-decreasing")
    t, q = t[keep], q[keep]

    result: list[tuple[float, list[float], list[list[float]]]] = [(float(t[0]), q[0].tolist(), [])]
    if len(t) == 1:
        return result

    v = _estimate_velocities(t, q)
    i = 0
    n = len(t)
    while i < n - 1:
        j = _longest_fit(t, q, v, i, tolerance, max_samples_per_segment)
        cps = _hermite_controls(t, q, v, i, j)
        result.append((float(t[j]), q[j].tolist(), _classify(cps)))
        i = j
    return result
